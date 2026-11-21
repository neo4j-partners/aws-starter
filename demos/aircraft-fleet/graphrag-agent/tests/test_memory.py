"""Tests for the memory settings, the shared memory, and the session manager.

Nothing here connects to Neo4j or Bedrock. ``SharedMemory.open`` is replaced
with a fake, and the real ``SharedMemory`` is built on a stub client.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterator

import pytest
from neo4j_agent_memory import ExtractorType
from neo4j_agent_memory.integrations.base import AsyncBridge
from neo4j_agent_memory.integrations.strands import SharedMemory
from neo4j_agent_memory.llm.adapters.bedrock import (
    BedrockEmbeddingProvider,
    BedrockProvider,
)

from fleet_graphrag.agent import memory
from fleet_graphrag.agent.config import ConfigError


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    memory.memory_settings.cache_clear()
    yield
    memory.memory_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_shared() -> Iterator[None]:
    """Each test starts and ends with no shared memory, no open in flight, and not closed."""
    _reset_memory()
    yield
    _reset_memory()


def _reset_memory() -> None:
    memory._shared = None
    memory._opening = None
    memory._open_thread = None
    memory._closed = False


@pytest.fixture
def mem_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_URI", "neo4j+s://memory.example.io")
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "local-only")


@pytest.mark.usefixtures("mem_env")
def test_settings_come_from_mem_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_USERNAME", "mem_user")
    monkeypatch.setenv("MEM_NEO4J_DATABASE", "memory")
    built = memory.memory_settings()
    assert built.backend == "bolt"
    assert built.neo4j.uri == "neo4j+s://memory.example.io"
    assert built.neo4j.username == "mem_user"
    assert built.neo4j.database == "memory"
    assert built.neo4j.password.get_secret_value() == "local-only"


@pytest.mark.usefixtures("mem_env")
def test_username_and_database_default_to_neo4j(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_USERNAME", "")
    built = memory.memory_settings()
    assert (built.neo4j.username, built.neo4j.database) == ("neo4j", "neo4j")


@pytest.mark.usefixtures("mem_env")
def test_extraction_and_embeddings_are_set_in_code() -> None:
    built = memory.memory_settings()
    assert isinstance(built.embedding, BedrockEmbeddingProvider)
    assert built.embedding.model == "bedrock/amazon.titan-embed-text-v2:0"
    assert built.embedding.dimensions == 1024
    assert isinstance(built.llm, BedrockProvider)
    assert built.llm.model == "bedrock/global.anthropic.claude-sonnet-5-5"
    assert built.llm._send_temperature is False
    assert built.llm._tool_choice == "auto"
    assert built.extraction.extractor_type is ExtractorType.LLM


@pytest.mark.usefixtures("mem_env")
def test_hosted_backend_key_does_not_switch_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_API_KEY", "not-used")
    assert memory.memory_settings().backend == "bolt"


@pytest.mark.usefixtures("mem_env")
def test_settings_are_built_once() -> None:
    assert memory.memory_settings() is memory.memory_settings()


def test_missing_uri_is_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "local-only")
    with pytest.raises(ConfigError, match="MEM_NEO4J_URI is not set"):
        memory.memory_settings()


def test_missing_password_is_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_URI", "neo4j+s://memory.example.io")
    with pytest.raises(ConfigError, match="MEM_NEO4J_PASSWORD_SECRET_ARN"):
        memory.memory_settings()


def test_secret_arn_wins_over_the_local_password(
    monkeypatch: pytest.MonkeyPatch, mem_env: None
) -> None:
    arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mem-AbCdEf"
    monkeypatch.setenv("MEM_NEO4J_PASSWORD_SECRET_ARN", arn)
    read: list[str] = []

    def fake_read(secret_arn: str, secret_arn_var: str) -> str:
        read.append(secret_arn_var)
        return "from-secret"

    monkeypatch.setattr("fleet_graphrag.agent.secrets._read_secret", fake_read)
    built = memory.memory_settings()
    assert built.neo4j.password.get_secret_value() == "from-secret"
    assert read == ["MEM_NEO4J_PASSWORD_SECRET_ARN"]


def _hook(name: str) -> Callable[[], None]:
    return lambda: None


class _StubClient:
    """A memory client that reports itself connected and does no I/O."""

    is_nams = False
    is_connected = True

    async def close(self) -> None:
        pass


def test_session_manager_options() -> None:
    shared = SharedMemory(_StubClient(), AsyncBridge(), 30.0, _hook)
    try:
        manager = memory.session_manager(shared, "s-1", "pilot-7")
        assert manager.session_id == "s-1"
        assert manager._user_id == "pilot-7"
        assert manager._retrieval_config.min_score == 0.75
        assert manager._extract_entities is True
        assert manager._defer_extraction is True
        assert manager._record_tool_calls is False
        # Built on the shared client and loop, which the manager does not own.
        assert manager._client is shared.client
        assert manager._bridge is shared._bridge
        assert manager._owns_bridge is False
        assert manager._background_hook is _hook
        manager.close()
    finally:
        shared.close()


class _FakeShared:
    """Stands in for ``SharedMemory``. ``open`` blocks until ``release`` is set."""

    opened: list[_FakeShared]
    release: threading.Event
    fail: list[Exception]

    def __init__(self, settings: object, background_hook: object) -> None:
        self.settings = settings
        self.background_hook = background_hook
        self.closes = 0

    @classmethod
    def open(cls, settings: object, *, background_hook: object) -> _FakeShared:
        assert cls.release.wait(5)
        if cls.fail:
            raise cls.fail.pop(0)
        cls.opened.append(cls(settings, background_hook))
        return cls.opened[-1]

    async def aclose(self) -> None:
        self.closes += 1


@pytest.fixture
def fake_shared(monkeypatch: pytest.MonkeyPatch, mem_env: None) -> type[_FakeShared]:
    class Fake(_FakeShared):
        opened = []
        release = threading.Event()
        fail = []

    Fake.release.set()
    monkeypatch.setattr(memory, "SharedMemory", Fake)
    return Fake


def test_open_gets_the_settings_and_the_hook(fake_shared: type[_FakeShared]) -> None:
    shared = asyncio.run(memory.shared_memory(_hook))
    assert fake_shared.opened == [shared]
    assert shared.settings is memory.memory_settings()
    assert shared.background_hook is _hook


def test_later_calls_reuse_the_open_memory(fake_shared: type[_FakeShared]) -> None:
    async def twice() -> tuple[object, object]:
        return await memory.shared_memory(_hook), await memory.shared_memory(_hook)

    first, second = asyncio.run(twice())
    assert first is second
    assert len(fake_shared.opened) == 1


def test_concurrent_first_callers_open_once(fake_shared: type[_FakeShared]) -> None:
    fake_shared.release.clear()

    async def many() -> list[object]:
        calls = asyncio.gather(*(memory.shared_memory(_hook) for _ in range(5)))
        await asyncio.sleep(0.05)
        fake_shared.release.set()
        return await calls

    results = asyncio.run(many())
    assert len(fake_shared.opened) == 1
    assert all(r is fake_shared.opened[0] for r in results)


def test_failed_open_is_not_cached(fake_shared: type[_FakeShared]) -> None:
    fake_shared.fail.append(RuntimeError("memory is down"))

    async def fail_then_open() -> object:
        with pytest.raises(RuntimeError, match="memory is down"):
            await memory.shared_memory(_hook)
        return await memory.shared_memory(_hook)

    shared = asyncio.run(fail_then_open())
    assert fake_shared.opened == [shared]


def test_failed_open_is_logged_without_a_traceback(
    fake_shared: type[_FakeShared], caplog: pytest.LogCaptureFixture
) -> None:
    """A failed open is logged even when no caller is left to see its error."""
    fake_shared.fail.append(RuntimeError("memory is down"))
    with pytest.raises(RuntimeError):
        asyncio.run(memory.shared_memory(_hook))
    [record] = [r for r in caplog.records if r.name == memory.__name__]
    assert record.levelname == "WARNING"
    assert record.getMessage() == "Memory open failed: memory is down"
    assert record.exc_info is None


def test_cancelled_first_caller_keeps_the_open(fake_shared: type[_FakeShared]) -> None:
    """A disconnect during the open must not lose the client it opens."""
    fake_shared.release.clear()

    async def cancel_then_call() -> object:
        first = asyncio.create_task(memory.shared_memory(_hook))
        await asyncio.sleep(0.05)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        fake_shared.release.set()
        return await memory.shared_memory(_hook)

    shared = asyncio.run(cancel_then_call())
    assert fake_shared.opened == [shared]


def test_close_without_an_open_does_nothing(fake_shared: type[_FakeShared]) -> None:
    asyncio.run(memory.close_memory())
    assert fake_shared.opened == []


def test_close_waits_for_an_open_in_flight(fake_shared: type[_FakeShared]) -> None:
    fake_shared.release.clear()

    async def close_during_open() -> None:
        opening = asyncio.create_task(memory.shared_memory(_hook))
        await asyncio.sleep(0.05)
        closing = asyncio.create_task(memory.close_memory())
        await asyncio.sleep(0.05)
        assert not closing.done()
        fake_shared.release.set()
        await opening
        await closing

    asyncio.run(close_during_open())
    [shared] = fake_shared.opened
    assert shared.closes == 1
    assert memory._shared is None


def test_second_close_does_nothing(fake_shared: type[_FakeShared]) -> None:
    async def open_then_close_twice() -> None:
        await memory.shared_memory(_hook)
        await memory.close_memory()
        await memory.close_memory()

    asyncio.run(open_then_close_twice())
    [shared] = fake_shared.opened
    assert shared.closes == 1


def _in_new_loop(coro_fn: Callable[[], object], results: list[object]) -> threading.Thread:
    """Run ``coro_fn()`` with ``asyncio.run`` on a new thread, as on a second loop."""

    def run() -> None:
        try:
            results.append(asyncio.run(coro_fn()))
        except Exception as e:
            results.append(e)

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_close_on_another_loop_waits_for_the_open(fake_shared: type[_FakeShared]) -> None:
    """AgentCore runs requests on a worker loop and the lifespan on the main loop."""
    fake_shared.release.clear()
    opened: list[object] = []
    request = _in_new_loop(lambda: memory.shared_memory(_hook), opened)

    async def close_during_open() -> None:
        await asyncio.sleep(0.1)
        closing = asyncio.create_task(memory.close_memory())
        await asyncio.sleep(0.1)
        assert not closing.done()
        fake_shared.release.set()
        await closing

    asyncio.run(close_during_open())
    request.join(5)
    [shared] = fake_shared.opened
    assert opened == [shared]
    assert shared.closes == 1
    assert memory._shared is None


def test_callers_on_two_loops_open_once(fake_shared: type[_FakeShared]) -> None:
    fake_shared.release.clear()
    results: list[object] = []
    callers = [_in_new_loop(lambda: memory.shared_memory(_hook), results) for _ in range(2)]
    threading.Event().wait(0.1)
    fake_shared.release.set()
    for caller in callers:
        caller.join(5)
    [shared] = fake_shared.opened
    assert results == [shared, shared]


def test_no_open_after_close(fake_shared: type[_FakeShared]) -> None:
    """A request that arrives after shutdown must not open a client nothing closes."""

    async def close_then_call() -> None:
        await memory.close_memory()
        with pytest.raises(memory.MemoryClosedError):
            await memory.shared_memory(_hook)

    asyncio.run(close_then_call())
    assert fake_shared.opened == []
