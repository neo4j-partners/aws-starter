"""The AgentCore entrypoint, with the model, schema, and supervisor stubbed."""

import asyncio
import threading
import uuid
from types import SimpleNamespace

import anyio
import pytest
from neo4j.exceptions import AuthError
from neo4j_agent_memory.core.exceptions import ConnectionError as MemoryConnectionError

from fleet_supervisor import server
from fleet_supervisor.core.config import ConfigError
from tests.conftest import collect


class FakeSupervisor:
    def __init__(self, events: list[dict] | None = None, error: Exception | None = None):
        self.events = events or []
        self.error = error
        self.prompts: list[str] = []

    async def stream_async(self, prompt: str):
        self.prompts.append(prompt)
        for event in self.events:
            yield event
        if self.error:
            raise self.error


@pytest.fixture
def supervisor(monkeypatch):
    """Install a fake supervisor, model, and schema; return the supervisor."""
    fake = FakeSupervisor(
        events=[
            {"current_tool_use": {"toolUseId": "t1", "name": "operations_specialist"}},
            {"data": "42 flights"},
        ]
    )

    calls: list[str] = []
    model = object()

    def fake_get_model():
        calls.append("get_model")
        return model

    def fake_get_graph_schema():
        calls.append("get_graph_schema")
        return "SCHEMA"

    monkeypatch.setattr(server, "get_model", fake_get_model)
    monkeypatch.setattr(server, "get_graph_schema", fake_get_graph_schema)
    fake.calls = calls
    fake.model = model
    monkeypatch.setattr(server, "build_supervisor", lambda model, schema, manager=None: fake)
    monkeypatch.setattr(server, "memory_settings", lambda: None)
    monkeypatch.setattr(
        server, "build_session_manager", lambda session_id, user_id, settings, background_hook: None
    )
    return fake


class FakeManager:
    def __init__(self, close_error: Exception | None = None, settings=None):
        self.close_error = close_error
        self.settings = settings
        self.closed = 0

    @property
    def manager(self) -> "FakeManager":
        """The fake is its own session and manager."""
        return self

    def close(self) -> None:
        self.closed += 1
        if self.close_error:
            raise self.close_error


@pytest.fixture
def manager(monkeypatch, supervisor):
    """Turn memory on with a fake manager; record what the supervisor gets."""
    fake = FakeManager()
    built: dict = {}

    def fake_build_session_manager(session_id, user_id, settings, background_hook):
        built["session_id"], built["user_id"] = session_id, user_id
        built["hook"] = background_hook
        return fake

    def fake_build_supervisor(model, schema, manager=None):
        built["manager"] = manager
        return supervisor

    monkeypatch.setattr(server, "build_session_manager", fake_build_session_manager)
    monkeypatch.setattr(server, "build_supervisor", fake_build_supervisor)
    fake.built = built
    return fake


def test_memory_manager_goes_to_the_supervisor_and_is_closed(supervisor, manager):
    events = collect(
        server.invoke({"prompt": "q", "user_id": "u1"}, SimpleNamespace(session_id="s1"))
    )
    assert events[-1] == {"type": "complete"}
    assert manager.built == {
        "session_id": "s1",
        "user_id": "u1",
        "hook": server.track_background_task,
        "manager": manager,
    }
    assert manager.closed == 1


def test_memory_manager_is_closed_after_a_failure(supervisor, manager):
    supervisor.error = RuntimeError("boom")
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events[-1] == {"type": "error", "error": server.GENERIC_ERROR}
    assert manager.closed == 1


def test_memory_manager_is_closed_when_the_client_disconnects(supervisor, manager):
    async def first_event_then_disconnect():
        stream = server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1"))
        first = await anext(stream)
        await stream.aclose()
        return first

    assert asyncio.run(first_event_then_disconnect())["type"] == "agent"
    assert manager.closed == 1


def test_the_stream_finishes_before_the_manager_closes_on_a_disconnect(supervisor, manager):
    """Strands flushes memory in the stream's finally, through a hook.

    On a disconnect the stream must be closed in place, so that flush ends
    before the manager closes. A dropped stream is closed later by the event
    loop, after or during the close.
    """
    order: list[str] = []

    async def stream_with_flush(prompt):
        try:
            for i in range(1000):
                yield {"data": f"t{i}"}
                await asyncio.sleep(0)
        finally:
            order.append("flushed")

    supervisor.stream_async = stream_with_flush
    manager.close = lambda: order.append("closed")

    async def disconnect_mid_answer():
        stream = server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1"))
        for _ in range(3):
            await anext(stream)
        await stream.aclose()
        await asyncio.sleep(0.1)

    asyncio.run(disconnect_mid_answer())
    assert order == ["flushed", "closed"]


def test_a_flush_error_on_a_disconnect_still_closes_the_manager(supervisor, manager, caplog):
    """The flush can raise while the stream closes, for example with Neo4j down.

    That error must not replace GeneratorExit, or invoke would yield inside a
    closing generator, aclose would raise, and the manager would stay open
    until a garbage collection.
    """

    async def stream_with_failing_flush(prompt):
        try:
            for i in range(1000):
                yield {"data": f"t{i}"}
                await asyncio.sleep(0)
        finally:
            raise RuntimeError("flush failed")

    supervisor.stream_async = stream_with_failing_flush
    closed_after_aclose: list[int] = []

    async def disconnect_mid_answer():
        stream = server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1"))
        for _ in range(3):
            await anext(stream)
        await stream.aclose()
        closed_after_aclose.append(manager.closed)

    asyncio.run(disconnect_mid_answer())
    assert closed_after_aclose == [1]
    assert "The agent stream failed while closing" in caplog.text
    assert "flush failed" in caplog.text


def test_memory_manager_is_closed_when_the_request_is_cancelled(supervisor, manager):
    async def slow_stream(prompt):
        yield {"data": "partial"}
        await asyncio.sleep(10)

    supervisor.stream_async = slow_stream

    async def cancel_mid_stream():
        async def drain():
            async for _ in server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")):
                pass

        task = asyncio.create_task(drain())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_mid_stream())
    assert manager.closed == 1


@pytest.fixture
def blocked_build(monkeypatch, supervisor, manager):
    """Block the supervisor constructor until ``release`` is set.

    Returns ``(started, release, order)``. ``order`` records "built" when
    the constructor returns and "closed" when the manager closes.
    """
    started, release = threading.Event(), threading.Event()
    order: list[str] = []

    def blocking_build(model, schema, session_manager=None):
        started.set()
        release.wait(5)
        order.append("built")
        return supervisor

    def recording_close():
        order.append("closed")
        manager.closed += 1

    monkeypatch.setattr(server, "build_supervisor", blocking_build)
    monkeypatch.setattr(manager, "close", recording_close)
    return started, release, order


async def _drain_invoke() -> None:
    async for _ in server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")):
        pass


def test_anyio_cancel_during_the_build_closes_the_manager_after_the_build(manager, blocked_build):
    """Starlette cancels through an anyio cancel scope while the build runs.

    The scope cancels every await again, so the finally block cannot wait
    in place. The close must still run after the constructor, which
    connects the manager, so the connection it opens is closed.
    """
    started, release, order = blocked_build

    async def disconnect_during_build():
        async with anyio.create_task_group() as group:
            group.start_soon(_drain_invoke)
            await anyio.to_thread.run_sync(started.wait)
            group.cancel_scope.cancel()
        release.set()
        with anyio.fail_after(5):
            while not manager.closed:
                await anyio.sleep(0.01)

    anyio.run(disconnect_during_build)
    assert order == ["built", "closed"]


def test_task_cancel_during_the_build_closes_the_manager_after_the_build(manager, blocked_build):
    """The AgentCore SDK cancels the handler task once on a disconnect.

    It runs the handler as a plain asyncio task on its worker loop and calls
    ``task.cancel()`` once. The finally block then waits for the build and
    closes the manager before the task ends.
    """
    started, release, order = blocked_build

    async def disconnect_during_build():
        task = asyncio.create_task(_drain_invoke())
        await asyncio.to_thread(started.wait)
        task.cancel()
        await asyncio.sleep(0.05)
        assert order == []
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)

    asyncio.run(disconnect_during_build())
    assert order == ["built", "closed"]


def test_a_failed_build_closes_the_manager_once(supervisor, manager, monkeypatch):
    def failing_build(model, schema, session_manager=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "build_supervisor", failing_build)
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events[-1] == {"type": "error", "error": server.GENERIC_ERROR}
    assert manager.closed == 1


def password_rejected_error() -> Exception:
    """The chain a rejected memory password raises from the Agent constructor."""
    connection = MemoryConnectionError("Authentication failed")
    connection.__cause__ = AuthError("The client is unauthorized due to authentication failure.")
    error = RuntimeError("Failed to initialize session 's1'")
    error.__cause__ = connection
    return error


@pytest.fixture
def password_retry(monkeypatch, supervisor):
    """Hand out a new FakeManager per build; record attempts and cache resets."""
    managers: list[FakeManager] = []
    forgotten: list[bool] = []

    def new_manager(session_id, user_id, settings, background_hook):
        managers.append(FakeManager(settings=settings))
        return managers[-1]

    monkeypatch.setattr(server, "build_session_manager", new_manager)
    monkeypatch.setattr(server, "forget_memory_settings", lambda settings: forgotten.append(True))
    return managers, forgotten


def test_a_rejected_password_is_read_again_once(supervisor, password_retry, monkeypatch):
    managers, forgotten = password_retry
    errors = [password_rejected_error()]

    def build(model, schema, session_manager=None):
        if errors:
            raise errors.pop()
        return supervisor

    monkeypatch.setattr(server, "build_supervisor", build)
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events[-1] == {"type": "complete"}
    assert forgotten == [True]
    assert [m.closed for m in managers] == [1, 1]


def test_concurrent_rejections_of_one_password_read_it_again_once(supervisor, monkeypatch):
    from fleet_supervisor.core import memory

    monkeypatch.setenv("MEM_NEO4J_URI", "bolt://127.0.0.1:37687")
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "old-pw")
    monkeypatch.setattr(memory, "_settings", None)
    monkeypatch.setattr(server, "memory_settings", memory.memory_settings)
    monkeypatch.setattr(server, "forget_memory_settings", memory.forget_memory_settings)
    forgotten: list[bool] = []
    monkeypatch.setattr(memory, "forget_secrets", lambda: forgotten.append(True))

    def new_manager(session_id, user_id, settings, background_hook):
        manager = FakeManager(settings=settings)
        manager.password = settings.neo4j.password.get_secret_value()
        return manager

    # Both requests build with the old password before either fails, and the
    # secret rotates in between.
    both_built = threading.Barrier(
        2, action=lambda: monkeypatch.setenv("MEM_NEO4J_PASSWORD", "new-pw")
    )

    def build(model, schema, session_manager=None):
        if session_manager.password == "old-pw":
            both_built.wait(timeout=10)
            raise password_rejected_error()
        return supervisor

    monkeypatch.setattr(server, "build_session_manager", new_manager)
    monkeypatch.setattr(server, "build_supervisor", build)

    async def two_requests():
        async def one(session_id):
            context = SimpleNamespace(session_id=session_id)
            return [event async for event in server.invoke({"prompt": "q"}, context)]

        return await asyncio.gather(one("s1"), one("s2"))

    results = asyncio.run(two_requests())
    assert [events[-1] for events in results] == [{"type": "complete"}] * 2
    # The second rejection finds the old password already dropped.
    assert forgotten == [True]


class FakeMemoryClient:
    """A shared memory client whose session managers know its password."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.password = settings.neo4j.password.get_secret_value()
        self.closes = 0

    def session_manager(self, session_id, **kwargs):
        return SimpleNamespace(password=self.password, close=lambda: None)

    def close(self, timeout: float = 30.0) -> None:
        self.closes += 1


def test_a_rejected_restore_forgets_the_password_its_client_used(supervisor, monkeypatch):
    """A request with new settings can still get a client opened with old ones.

    Another request dropped the p1 settings but has not yet retired the p1
    client. R reads p2, takes the p1 client, and Neo4j rejects the restore.
    R must forget p1, so the p2 settings stay and R opens a p2 client.
    """
    from fleet_supervisor.core import memory

    for name, value in [
        ("_settings", None),
        ("_settings_build", None),
        ("_shared", None),
        ("_shared_open", None),
        ("_retired", set()),
        ("_closers", set()),
        ("_shutting_down", False),
    ]:
        monkeypatch.setattr(memory, name, value)
    monkeypatch.delenv("MEM_NEO4J_PASSWORD_SECRET_ARN", raising=False)
    monkeypatch.setenv("MEM_NEO4J_URI", "bolt://127.0.0.1:37687")
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "p1")
    monkeypatch.setattr(memory, "forget_secrets", lambda: None)
    for name in ("memory_settings", "forget_memory_settings", "build_session_manager"):
        monkeypatch.setattr(server, name, getattr(memory, name))
    clients: list[FakeMemoryClient] = []

    def fake_open(settings, *, background_hook=None):
        clients.append(FakeMemoryClient(settings))
        return clients[-1]

    monkeypatch.setattr(memory, "SharedMemory", SimpleNamespace(open=fake_open))
    p1 = memory.memory_settings()
    memory.build_session_manager("s0", "u1", p1, None).close()
    # Another request dropped p1, but has not retired the p1 client yet.
    with monkeypatch.context() as paused:
        paused.setattr(memory, "_retire_shared", lambda failed: None)
        memory.forget_memory_settings(p1)
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "p2")
    p2 = memory.memory_settings()

    def build(model, schema, session_manager=None):
        if session_manager.password == "p1":
            raise password_rejected_error()
        return supervisor

    monkeypatch.setattr(server, "build_supervisor", build)
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))

    assert events[-1] == {"type": "complete"}
    assert memory.memory_settings() is p2
    [old, new] = clients
    assert old.password == "p1" and new.password == "p2"
    assert memory._shared is not None and memory._shared.memory is new
    assert new.closes == 0
    memory.close_shared_memory()
    assert old.closes == 1


def test_a_password_rejected_twice_fails_without_a_third_try(
    supervisor, password_retry, monkeypatch, caplog
):
    managers, forgotten = password_retry

    def build(model, schema, session_manager=None):
        raise password_rejected_error()

    monkeypatch.setattr(server, "build_supervisor", build)
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events[-1] == {"type": "error", "error": server.GENERIC_ERROR}
    assert forgotten == [True]
    assert [m.closed for m in managers] == [1, 1]
    # The second failure is raised on its own, not chained to the first.
    [failed] = [r for r in caplog.records if r.getMessage() == "Request failed"]
    assert failed.exc_info is not None
    raised = failed.exc_info[1]
    assert isinstance(raised, server.MemorySessionError)
    chain = []
    error = raised
    while error is not None:
        chain.append(error)
        error = error.__cause__ or error.__context__
    assert sum(str(e) == "Failed to initialize session 's1'" for e in chain) == 1


def test_a_rejected_open_forgets_the_password_the_open_used(supervisor, monkeypatch):
    """The open that failed may have used another request's older password."""
    from fleet_supervisor.core.memory import SharedMemoryOpenError

    ours = SimpleNamespace(name="ours")
    opener = SimpleNamespace(name="opener")
    monkeypatch.setattr(server, "memory_settings", lambda: ours)
    forgotten: list[object] = []
    monkeypatch.setattr(server, "forget_memory_settings", forgotten.append)
    managers: list[FakeManager] = []

    def build_session(session_id, user_id, settings, background_hook):
        if not managers:
            managers.append(FakeManager())
            error = SharedMemoryOpenError(opener)
            error.__cause__ = AuthError("unauthorized")
            raise error
        managers.append(FakeManager())
        return managers[-1]

    monkeypatch.setattr(server, "build_session_manager", build_session)
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events[-1] == {"type": "complete"}
    assert forgotten == [opener]


def test_other_build_errors_keep_the_cached_password(supervisor, password_retry, monkeypatch):
    managers, forgotten = password_retry

    def build(model, schema, session_manager=None):
        raise MemoryConnectionError("Neo4j service unavailable")

    monkeypatch.setattr(server, "build_supervisor", build)
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events[-1] == {"type": "error", "error": server.GENERIC_ERROR}
    assert forgotten == []
    assert [m.closed for m in managers] == [1]


def test_close_error_is_logged_not_sent(supervisor, manager, caplog):
    manager.close_error = RuntimeError("bolt://user:pw@host")
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events[-1] == {"type": "complete"}
    assert "pw@host" not in str(events)
    assert "Error while closing the memory session manager" in caplog.text


def test_no_memory_manager_when_memory_is_off(supervisor, monkeypatch):
    seen: dict = {}

    def fake_build_supervisor(model, schema, manager=None):
        seen["manager"] = manager
        return supervisor

    monkeypatch.setattr(server, "build_supervisor", fake_build_supervisor)
    collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert seen == {"manager": None}


# Deferred extraction outlives the request. The hook marks the server busy
# while it runs, so AgentCore Runtime does not reclaim the session.
def test_the_background_hook_marks_the_server_busy_until_done():
    before = server.app.get_async_task_info()["active_count"]
    done = server.track_background_task("extract:s1")
    assert server.app.get_async_task_info()["active_count"] == before + 1
    done()
    assert server.app.get_async_task_info()["active_count"] == before


def test_shutdown_closes_the_shared_memory_and_the_graph_driver(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(server, "close_shared_memory", lambda: calls.append("memory"))
    monkeypatch.setattr(server, "close", lambda: calls.append("graph"))

    async def serve_then_stop():
        async with server.app.router.lifespan_context(server.app):
            assert calls == []
        assert calls == ["memory", "graph"]

    asyncio.run(serve_then_stop())


def test_shutdown_closes_the_graph_driver_when_the_memory_close_fails(monkeypatch):
    calls: list[str] = []

    def failing_close():
        raise RuntimeError("memory close failed")

    monkeypatch.setattr(server, "close_shared_memory", failing_close)
    monkeypatch.setattr(server, "close", lambda: calls.append("graph"))

    async def serve_then_stop():
        async with server.app.router.lifespan_context(server.app):
            pass

    with pytest.raises(RuntimeError, match="memory close failed"):
        asyncio.run(serve_then_stop())
    assert calls == ["graph"]


def test_streams_agent_chunk_and_complete(supervisor):
    events = collect(
        server.invoke({"prompt": "How many flights?"}, SimpleNamespace(session_id="s1"))
    )
    assert events == [
        {"type": "agent", "name": "Operations Agent"},
        {"type": "chunk", "data": "42 flights"},
        {"type": "complete"},
    ]
    assert supervisor.prompts == ["How many flights?"]


def test_model_and_schema_are_read_on_every_request(supervisor):
    collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s2")))
    assert supervisor.calls == ["get_model", "get_graph_schema"] * 2


def test_the_model_and_schema_go_to_the_supervisor(supervisor, monkeypatch):
    built: list[tuple] = []

    def fake_build_supervisor(model, schema, manager=None):
        built.append((model, schema))
        return supervisor

    monkeypatch.setattr(server, "build_supervisor", fake_build_supervisor)
    collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert built == [(supervisor.model, "SCHEMA")]


def test_the_schema_is_read_off_the_event_loop(supervisor, monkeypatch):
    threads: list[int] = []

    def fake_get_graph_schema():
        threads.append(threading.get_ident())
        return "SCHEMA"

    monkeypatch.setattr(server, "get_graph_schema", fake_get_graph_schema)
    collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert threads and threads[0] != threading.get_ident()


@pytest.mark.parametrize("key", ["prompt", "message", "query", "inputText", "input"])
def test_accepts_common_prompt_keys(supervisor, key):
    collect(server.invoke({key: "hi"}, SimpleNamespace(session_id="s1")))
    assert supervisor.prompts == ["hi"]


def test_missing_prompt_is_an_error(supervisor):
    events = collect(server.invoke({}, SimpleNamespace(session_id="s1")))
    assert [e["type"] for e in events] == ["error"]
    assert supervisor.prompts == []


def test_failure_sends_generic_error(supervisor, caplog):
    supervisor.error = RuntimeError("secret connection string")
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events[-1] == {"type": "error", "error": server.GENERIC_ERROR}
    assert "secret connection string" not in str(events)
    assert "secret connection string" in caplog.text


def test_session_id_comes_from_context(supervisor, caplog):
    caplog.set_level("INFO")
    collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="abc-123")))
    assert "session=abc-123" in caplog.text


def test_prompt_text_is_logged_only_at_debug(supervisor, caplog):
    caplog.set_level("DEBUG", logger="fleet_supervisor.server")
    prompt = "Which aircraft has tail number N12345?"
    collect(server.invoke({"prompt": prompt}, SimpleNamespace(session_id="s9")))
    info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    debug = [r.getMessage() for r in caplog.records if r.levelname == "DEBUG"]
    assert f"Request session=s9 user=anonymous prompt_chars={len(prompt)}" in info
    assert not [line for line in info if "N12345" in line]
    assert f"Request session=s9 prompt={prompt}" in debug


def test_missing_session_id_gets_a_fresh_uuid(supervisor, caplog):
    caplog.set_level("INFO")
    collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id=None)))
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("Request "))
    session = line.split("session=")[1].split()[0]
    assert uuid.UUID(session)
    assert "default" not in line


@pytest.mark.parametrize(
    "payload", [None, "a string", ["prompt"], {"prompt": 42}, {"prompt": "  "}]
)
def test_bad_payload_gets_a_fixed_message(supervisor, payload):
    events = collect(server.invoke(payload, SimpleNamespace(session_id="s1")))
    assert events == [{"type": "error", "error": server.NO_PROMPT_ERROR}]
    assert supervisor.prompts == []


def test_non_string_user_id_does_not_raise(supervisor):
    events = collect(
        server.invoke({"prompt": "q", "user_id": {"x": 1}}, SimpleNamespace(session_id="s1"))
    )
    assert events[-1] == {"type": "complete"}


def test_schema_error_text_stays_in_the_log(supervisor, monkeypatch, caplog):
    def failing_schema():
        raise RuntimeError("bolt://user:pw@host")

    monkeypatch.setattr(server, "get_graph_schema", failing_schema)
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events == [{"type": "error", "error": server.GENERIC_ERROR}]
    assert "bolt://user:pw@host" in caplog.text
    assert supervisor.prompts == []


def test_model_is_built_once_and_failures_are_retried(monkeypatch):
    results: list = [ValueError("no region"), "model"]

    def fake_build_model():
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(server, "build_model", fake_build_model)
    server.get_model.cache_clear()
    try:
        with pytest.raises(ValueError, match="no region"):
            server.get_model()
        # A third build would find the list empty and raise IndexError.
        assert server.get_model() == "model"
        assert server.get_model() == "model"
    finally:
        server.get_model.cache_clear()


@pytest.fixture
def startup(monkeypatch):
    """Stub what main() calls; return the order of the calls."""
    calls: list[str] = []
    monkeypatch.delenv("AGENT_PORT", raising=False)
    monkeypatch.setattr(server, "neo4j_login", lambda: calls.append("neo4j_login"))
    monkeypatch.setattr(server, "memory_settings", lambda: calls.append("memory_settings"))
    monkeypatch.setattr(server.app, "run", lambda port: calls.append(f"run:{port}"))
    return calls


def test_main_reads_the_graph_login_before_serving(startup):
    server.main(default_port=8080)
    assert startup == ["neo4j_login", "memory_settings", "run:8080"]


def test_a_missing_graph_login_stops_startup(startup, monkeypatch):
    def missing_login():
        raise ConfigError("Set NEO4J_PASSWORD_SECRET_ARN")

    monkeypatch.setattr(server, "neo4j_login", missing_login)
    with pytest.raises(ConfigError):
        server.main()
    assert startup == []
