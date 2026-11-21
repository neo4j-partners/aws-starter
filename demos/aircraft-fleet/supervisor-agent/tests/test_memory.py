"""Tests for the supervisor memory settings and session manager factory."""

from __future__ import annotations

import threading
import time

import pytest
from neo4j.exceptions import AuthError
from neo4j_agent_memory.config.settings import ExtractorType
from neo4j_agent_memory.core.exceptions import ConnectionError as MemoryConnectionError
from neo4j_agent_memory.integrations.strands import Neo4jSessionManager
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


def test_session_manager_uses_settings_and_retrieval_config(memory_on) -> None:
    manager = memory.build_session_manager("s1", "u1", memory.memory_settings())
    try:
        assert isinstance(manager, Neo4jSessionManager)
        assert manager.session_id == "s1"
        assert manager._user_id == "u1"
        assert manager._retrieval_config.min_score == memory.RETRIEVAL_MIN_SCORE
        assert manager._extract_entities is True
        assert manager._record_tool_calls is False
    finally:
        # Never connected, so close only stops the unused bridge.
        manager.close()


def test_each_request_gets_its_own_manager(memory_on) -> None:
    first = memory.build_session_manager("s1", "u1", memory.memory_settings())
    second = memory.build_session_manager("s1", "u1", memory.memory_settings())
    try:
        assert first is not second
    finally:
        first.close()
        second.close()


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
    """Call memory_settings from ``count`` threads at once.

    Returns each thread's result or exception, and the seconds until the
    last one finished.
    """
    results: list[object] = [None] * count
    start = threading.Barrier(count)

    def call(index: int) -> None:
        start.wait(timeout=10)
        try:
            results[index] = memory.memory_settings()
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
