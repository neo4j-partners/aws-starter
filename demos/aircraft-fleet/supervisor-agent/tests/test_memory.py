"""Tests for the supervisor memory settings and session manager factory."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from neo4j.exceptions import AuthError
from neo4j_agent_memory.config.settings import ExtractorType
from neo4j_agent_memory.core.exceptions import ConnectionError as MemoryConnectionError
from neo4j_agent_memory.llm.adapters.bedrock import BedrockEmbeddingProvider, BedrockProvider

from fleet_supervisor.core import memory, secrets
from fleet_supervisor.core.config import ConfigError

MEM_VARS = (
    "MEM_NEO4J_URI",
    "MEM_NEO4J_USERNAME",
    "MEM_NEO4J_PASSWORD",
    "MEM_NEO4J_PASSWORD_SECRET_ARN",
    "MEM_NEO4J_DATABASE",
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    for name in MEM_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(memory, "_settings", None)
    monkeypatch.setattr(memory, "_settings_build", None)
    monkeypatch.setattr(memory, "_shared", None)
    monkeypatch.setattr(memory, "_shared_open", None)
    monkeypatch.setattr(memory, "_retired", set())
    monkeypatch.setattr(memory, "_closers", set())
    secrets._read_secret.cache_clear()


@pytest.fixture
def memory_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_URI", "bolt://127.0.0.1:37687")
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "local-pw")


def test_missing_uri_raises() -> None:
    with pytest.raises(ConfigError, match="MEM_NEO4J_URI is not set"):
        memory.memory_settings()


def test_missing_uri_failure_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError):
        memory.memory_settings()
    monkeypatch.setenv("MEM_NEO4J_URI", "bolt://127.0.0.1:37687")
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "local-pw")
    assert memory.memory_settings().neo4j.uri == "bolt://127.0.0.1:37687"


def test_uri_without_a_password_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_URI", "bolt://127.0.0.1:37687")
    with pytest.raises(ConfigError, match="MEM_NEO4J_PASSWORD_SECRET_ARN.*MEM_NEO4J_PASSWORD"):
        memory.memory_settings()


def test_settings_come_from_the_mem_vars(monkeypatch: pytest.MonkeyPatch, memory_on) -> None:
    monkeypatch.setenv("MEM_NEO4J_USERNAME", "mem_user")
    monkeypatch.setenv("MEM_NEO4J_DATABASE", "memdb")
    settings = memory.memory_settings()
    assert settings.backend == "bolt"
    assert settings.neo4j.uri == "bolt://127.0.0.1:37687"
    assert settings.neo4j.username == "mem_user"
    assert settings.neo4j.database == "memdb"
    assert settings.neo4j.password.get_secret_value() == "local-pw"
    assert settings.extraction.extractor_type is ExtractorType.LLM


def test_bedrock_providers_are_explicit(memory_on) -> None:
    settings = memory.memory_settings()
    assert isinstance(settings.embedding, BedrockEmbeddingProvider)
    assert settings.embedding.model == memory.EMBEDDING_MODEL
    assert settings.embedding.dimensions == memory.EMBEDDING_DIMENSIONS == 1024
    assert settings.embedding._aws_region == memory.AWS_REGION
    assert isinstance(settings.llm, BedrockProvider)
    assert settings.llm._aws_region == memory.AWS_REGION


# Sonnet 5.5 rejects a temperature and a forced toolChoice, so the extractor
# sends neither.
def test_the_extractor_runs_on_sonnet_5_5_without_a_temperature(memory_on) -> None:
    llm = memory.memory_settings().llm
    assert llm.model == "bedrock/global.anthropic.claude-sonnet-5-5"
    assert llm._tool_choice == "auto"
    assert llm._inference_config(0.0, 100) == {"maxTokens": 100}


def test_memory_api_key_does_not_switch_backends(
    monkeypatch: pytest.MonkeyPatch, memory_on
) -> None:
    monkeypatch.setenv("MEMORY_API_KEY", "not-used")
    assert memory.memory_settings().backend == "bolt"


def test_username_and_database_default_to_neo4j(memory_on) -> None:
    settings = memory.memory_settings()
    assert (settings.neo4j.username, settings.neo4j.database) == ("neo4j", "neo4j")


def test_nam_env_file_is_not_read(monkeypatch: pytest.MonkeyPatch, tmp_path, memory_on) -> None:
    (tmp_path / ".env").write_text("NAM_NEO4J__URI=bolt://from-dotenv:7687\n")
    monkeypatch.chdir(tmp_path)
    assert memory.memory_settings().neo4j.uri == "bolt://127.0.0.1:37687"


def test_settings_are_built_once(memory_on) -> None:
    assert memory.memory_settings() is memory.memory_settings()


class FakeManager:
    def __init__(self, close_error: Exception | None = None) -> None:
        self.close_error = close_error
        self.closes = 0

    def close(self) -> None:
        self.closes += 1
        if self.close_error:
            raise self.close_error


class FakeShared:
    """Stands in for SharedMemory. Records its managers and its closes."""

    def __init__(self, settings, background_hook) -> None:
        self.settings = settings
        self.background_hook = background_hook
        self.managers: list[dict] = []
        self.closes = 0
        self.closed = threading.Event()
        self.manager_close_error: Exception | None = None

    def session_manager(self, session_id: str, **kwargs) -> FakeManager:
        self.managers.append({"session_id": session_id, **kwargs})
        return FakeManager(self.manager_close_error)

    def close(self) -> None:
        self.closes += 1
        self.closed.set()


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[FakeShared]:
    """Replace SharedMemory.open; return every object it opened, in order."""
    opened: list[FakeShared] = []

    def fake_open(settings, *, background_hook=None):
        opened.append(FakeShared(settings, background_hook))
        return opened[-1]

    monkeypatch.setattr(memory, "SharedMemory", SimpleNamespace(open=fake_open))
    return opened


def hook(name: str):
    return lambda: None


def _closes_settle() -> None:
    """Give a close started on a background thread time to run."""
    time.sleep(0.1)


def test_a_session_runs_on_the_shared_client(memory_on, opened) -> None:
    settings = memory.memory_settings()
    session = memory.build_session_manager("s1", "u1", settings, hook)
    [shared] = opened
    assert shared.settings is settings
    assert shared.background_hook is hook
    [kwargs] = shared.managers
    assert kwargs.pop("retrieval_config").min_score == memory.RETRIEVAL_MIN_SCORE
    assert kwargs == {
        "session_id": "s1",
        "user_id": "u1",
        "extract_entities": True,
        "defer_extraction": True,
        "record_tool_calls": False,
    }
    assert isinstance(session.manager, FakeManager)


def test_requests_share_one_client(memory_on, opened) -> None:
    first = memory.build_session_manager("s1", "u1", memory.memory_settings(), hook)
    second = memory.build_session_manager("s2", "u1", memory.memory_settings(), hook)
    assert len(opened) == 1
    assert first.manager is not second.manager


def test_closing_a_session_closes_its_manager_but_not_the_client(memory_on, opened) -> None:
    session = memory.build_session_manager("s1", "u1", memory.memory_settings(), hook)
    session.close()
    _closes_settle()
    assert session.manager.closes == 1
    assert opened[0].closes == 0


def test_concurrent_first_requests_open_one_client(memory_on, monkeypatch) -> None:
    opened: list[FakeShared] = []

    def slow_open(settings, *, background_hook=None):
        time.sleep(BUILD_SECONDS)
        opened.append(FakeShared(settings, background_hook))
        return opened[-1]

    monkeypatch.setattr(memory, "SharedMemory", SimpleNamespace(open=slow_open))
    settings = memory.memory_settings()

    results, elapsed = _concurrent(
        5, lambda: memory.build_session_manager("s1", "u1", settings, hook)
    )

    assert len(opened) == 1
    assert len(opened[0].managers) == 5
    assert elapsed < 2 * BUILD_SECONDS


def test_concurrent_requests_share_one_failed_open(memory_on, monkeypatch) -> None:
    attempts: list[bool] = []

    def rejected_open(settings, *, background_hook=None):
        attempts.append(True)
        time.sleep(BUILD_SECONDS)
        raise AuthError("unauthorized")

    monkeypatch.setattr(memory, "SharedMemory", SimpleNamespace(open=rejected_open))
    settings = memory.memory_settings()

    results, elapsed = _concurrent(
        3, lambda: memory.build_session_manager("s1", "u1", settings, hook)
    )

    assert len(attempts) == 1
    assert elapsed < 2 * BUILD_SECONDS
    waiters = [result for result in results if not isinstance(result, AuthError)]
    assert len(waiters) == 2
    assert all(isinstance(waiter, RuntimeError) for waiter in waiters)
    # Each waiter still sees the rejected password, so it reads it again.
    assert all(memory.password_rejected(waiter) for waiter in waiters)


def test_a_failed_open_is_not_cached(memory_on, monkeypatch) -> None:
    outcomes: list[object] = [MemoryConnectionError("Neo4j service unavailable")]

    def open_once_failing(settings, *, background_hook=None):
        if outcomes:
            raise outcomes.pop()
        return FakeShared(settings, background_hook)

    monkeypatch.setattr(memory, "SharedMemory", SimpleNamespace(open=open_once_failing))

    with pytest.raises(MemoryConnectionError):
        memory.build_session_manager("s1", "u1", memory.memory_settings(), hook)
    session = memory.build_session_manager("s1", "u1", memory.memory_settings(), hook)
    assert isinstance(session.manager, FakeManager)


def test_a_failed_manager_build_releases_the_client(memory_on, opened, monkeypatch) -> None:
    settings = memory.memory_settings()
    memory.build_session_manager("s1", "u1", settings, hook).close()

    def failing_manager(session_id, **kwargs):
        raise TypeError("bad keyword")

    monkeypatch.setattr(opened[0], "session_manager", failing_manager)
    with pytest.raises(TypeError):
        memory.build_session_manager("s2", "u1", settings, hook)
    # No session holds the client, so retiring it closes it at once.
    memory.forget_memory_settings(settings)
    assert opened[0].closed.wait(5)


def test_a_rejected_password_retires_an_idle_client_at_once(memory_on, opened) -> None:
    settings = memory.memory_settings()
    memory.build_session_manager("s1", "u1", settings, hook).close()

    memory.forget_memory_settings(settings)

    assert opened[0].closed.wait(5)
    _closes_settle()
    assert opened[0].closes == 1
    memory.build_session_manager("s1", "u1", memory.memory_settings(), hook)
    assert len(opened) == 2


def test_a_retired_client_closes_once_after_its_last_session(memory_on, opened) -> None:
    settings = memory.memory_settings()
    session = memory.build_session_manager("s1", "u1", settings, hook)

    memory.forget_memory_settings(settings)
    _closes_settle()
    assert opened[0].closes == 0

    session.close()
    assert opened[0].closed.wait(5)
    # A second close of the session releases nothing more.
    session.close()
    memory.close_shared_memory()
    _closes_settle()
    assert opened[0].closes == 1


def test_a_late_rejection_of_the_old_password_keeps_the_new_client(
    monkeypatch: pytest.MonkeyPatch, memory_on, opened
) -> None:
    old = memory.memory_settings()
    memory.forget_memory_settings(old)
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "rotated-pw")
    memory.build_session_manager("s1", "u1", memory.memory_settings(), hook).close()

    memory.forget_memory_settings(old)

    _closes_settle()
    assert opened[0].closes == 0
    memory.build_session_manager("s2", "u1", memory.memory_settings(), hook)
    assert len(opened) == 1


def test_a_failed_manager_close_still_releases_the_client(memory_on, opened) -> None:
    settings = memory.memory_settings()
    memory.build_session_manager("s0", "u1", settings, hook).close()
    opened[0].manager_close_error = RuntimeError("flush failed")
    session = memory.build_session_manager("s1", "u1", settings, hook)
    memory.forget_memory_settings(settings)

    with pytest.raises(RuntimeError, match="flush failed"):
        session.close()

    assert opened[0].closed.wait(5)


def test_shutdown_closes_the_current_and_the_retired_clients(
    monkeypatch: pytest.MonkeyPatch, memory_on, opened, caplog
) -> None:
    monkeypatch.setattr(memory, "SHUTDOWN_WAIT_SECONDS", 0.2)
    old = memory.memory_settings()
    old_session = memory.build_session_manager("s1", "u1", old, hook)
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "rotated-pw")
    memory.forget_memory_settings(old)
    memory.build_session_manager("s2", "u1", memory.memory_settings(), hook).close()

    memory.close_shared_memory()

    assert [shared.closes for shared in opened] == [1, 1]
    # The old session was still open, so shutdown waited for it, then closed anyway.
    assert "1 memory session(s) still open" in caplog.text
    old_session.close()
    _closes_settle()
    assert [shared.closes for shared in opened] == [1, 1]


def test_shutdown_waits_for_open_sessions(memory_on, opened) -> None:
    session = memory.build_session_manager("s1", "u1", memory.memory_settings(), hook)
    order: list[str] = []
    real_close = opened[0].close

    def recording_close() -> None:
        order.append("client")
        real_close()

    opened[0].close = recording_close

    def close_session_later() -> None:
        time.sleep(0.2)
        order.append("session")
        session.close()

    closer = threading.Thread(target=close_session_later)
    closer.start()
    memory.close_shared_memory()
    closer.join(5)

    assert order == ["session", "client"]


def test_shutdown_with_no_client_does_nothing(memory_on) -> None:
    memory.close_shared_memory()


def test_forget_memory_settings_reads_the_password_again(
    monkeypatch: pytest.MonkeyPatch, memory_on
) -> None:
    failed = memory.memory_settings()
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "rotated-pw")
    assert memory.memory_settings().neo4j.password.get_secret_value() == "local-pw"
    memory.forget_memory_settings(failed)
    assert memory.memory_settings().neo4j.password.get_secret_value() == "rotated-pw"


def test_a_late_failure_with_the_old_password_keeps_the_new_settings(
    monkeypatch: pytest.MonkeyPatch, memory_on
) -> None:
    # Two requests fail with the old password. The first drops it and the
    # next build reads the new one. The second must not drop that.
    failed = memory.memory_settings()
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "rotated-pw")
    memory.forget_memory_settings(failed)
    rebuilt = memory.memory_settings()
    forgotten: list[bool] = []
    monkeypatch.setattr(memory, "forget_secrets", lambda: forgotten.append(True))

    memory.forget_memory_settings(failed)

    assert memory.memory_settings() is rebuilt
    assert forgotten == []


def test_a_failure_after_another_request_dropped_the_settings_does_nothing(
    monkeypatch: pytest.MonkeyPatch, memory_on
) -> None:
    failed = memory.memory_settings()
    memory.forget_memory_settings(failed)
    forgotten: list[bool] = []
    monkeypatch.setattr(memory, "forget_secrets", lambda: forgotten.append(True))

    memory.forget_memory_settings(failed)

    assert forgotten == []


def test_password_rejected_finds_an_auth_error_in_the_cause_chain() -> None:
    connection = MemoryConnectionError("Authentication failed")
    connection.__cause__ = AuthError("unauthorized")
    error = RuntimeError("Failed to initialize session")
    error.__cause__ = connection
    assert memory.password_rejected(error)


def test_password_rejected_follows_an_implicit_context() -> None:
    error = RuntimeError("raised while handling the auth error")
    error.__context__ = AuthError("unauthorized")
    assert memory.password_rejected(error)


def test_other_connection_errors_are_not_a_rejected_password() -> None:
    error = MemoryConnectionError("Neo4j service unavailable")
    assert not memory.password_rejected(error)


BUILD_SECONDS = 0.5


def _concurrent_calls(count: int) -> tuple[list[object], float]:
    """Call memory_settings from ``count`` threads at once. See ``_concurrent``."""
    return _concurrent(count, memory.memory_settings)


def _concurrent(count: int, target: Callable[[], object]) -> tuple[list[object], float]:
    """Call ``target`` from ``count`` threads at once.

    Returns each thread's result or exception, and the seconds until the
    last one finished.
    """
    results: list[object] = [None] * count
    start = threading.Barrier(count)

    def call(index: int) -> None:
        start.wait(timeout=10)
        try:
            results[index] = target()
        except Exception as error:
            results[index] = error

    threads = [threading.Thread(target=call, args=(i,)) for i in range(count)]
    began = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results, time.monotonic() - began


def test_concurrent_callers_share_one_failed_build(monkeypatch: pytest.MonkeyPatch) -> None:
    builds: list[bool] = []

    def failing_build():
        builds.append(True)
        time.sleep(BUILD_SECONDS)
        raise ConfigError("cannot read the secret")

    monkeypatch.setattr(memory, "_build_memory_settings", failing_build)

    results, elapsed = _concurrent_calls(5)

    assert len(builds) == 1
    assert all(isinstance(result, ConfigError) for result in results)
    # The caller that built raises the build's error. Each other caller
    # raises its own error, caused by it.
    (error,) = (result for result in results if result.__cause__ is None)
    waiters = [result for result in results if result is not error]
    assert len(waiters) == 4
    assert len({id(waiter) for waiter in waiters}) == 4
    assert all(waiter.__cause__ is error for waiter in waiters)
    assert all(str(waiter) == "cannot read the secret" for waiter in waiters)
    # Raising one object in every thread would add each thread's frames to
    # its traceback.
    assert _frames_named(error, "memory_settings") == 1
    # One build's time, not one per caller in turn.
    assert elapsed < 2 * BUILD_SECONDS


def _frames_named(error: BaseException, name: str) -> int:
    count = 0
    tb = error.__traceback__
    while tb is not None:
        count += tb.tb_frame.f_code.co_name == name
        tb = tb.tb_next
    return count


def test_a_waiter_still_finds_an_auth_error_from_the_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def rejected_build():
        time.sleep(BUILD_SECONDS)
        raise AuthError("unauthorized")

    monkeypatch.setattr(memory, "_build_memory_settings", rejected_build)

    results, _ = _concurrent_calls(3)

    waiters = [result for result in results if not isinstance(result, AuthError)]
    assert len(waiters) == 2
    assert all(isinstance(waiter, RuntimeError) for waiter in waiters)
    assert all(isinstance(waiter.__cause__, AuthError) for waiter in waiters)
    assert all(memory.password_rejected(waiter) for waiter in waiters)


def test_concurrent_callers_share_one_successful_build(monkeypatch: pytest.MonkeyPatch) -> None:
    builds: list[bool] = []
    built = object()

    def slow_build():
        builds.append(True)
        time.sleep(BUILD_SECONDS)
        return built

    monkeypatch.setattr(memory, "_build_memory_settings", slow_build)

    results, elapsed = _concurrent_calls(5)

    assert len(builds) == 1
    assert results == [built] * 5
    assert elapsed < 2 * BUILD_SECONDS


def test_a_call_after_a_failed_build_builds_again(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes: list[object] = [ConfigError("cannot read the secret"), object()]

    def build():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(memory, "_build_memory_settings", build)

    with pytest.raises(ConfigError):
        memory.memory_settings()
    rebuilt = memory.memory_settings()

    assert outcomes == []
    assert memory.memory_settings() is rebuilt


def test_shutdown_waits_for_an_open_in_progress(memory_on, monkeypatch) -> None:
    opened: list[FakeShared] = []
    started = threading.Event()

    def slow_open(settings, *, background_hook=None):
        started.set()
        time.sleep(0.2)
        opened.append(FakeShared(settings, background_hook))
        return opened[-1]

    monkeypatch.setattr(memory, "SharedMemory", SimpleNamespace(open=slow_open))
    settings = memory.memory_settings()

    def request() -> None:
        memory.build_session_manager("s1", "u1", settings, hook).close()

    worker = threading.Thread(target=request)
    worker.start()
    assert started.wait(5)
    memory.close_shared_memory()
    worker.join(5)

    assert [shared.closes for shared in opened] == [1]
