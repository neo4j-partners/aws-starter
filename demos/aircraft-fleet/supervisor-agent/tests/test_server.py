"""The AgentCore entrypoint, with the runtime and supervisor stubbed."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from strands.types.exceptions import ToolProviderException

from fleet_supervisor import server
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
    """Install a fake supervisor and a fake runtime; return the supervisor."""
    fake = FakeSupervisor(
        events=[
            {"current_tool_use": {"toolUseId": "t1", "name": "operations_specialist"}},
            {"data": "42 flights"},
        ]
    )

    calls: list[str] = []

    class FakeGateway:
        async def prepare_request(self):
            calls.append("prepare_request")

    async def fake_runtime():
        calls.append("get_runtime")
        return SimpleNamespace(model=object(), tools=[])

    monkeypatch.setattr(server, "gateway_auth", FakeGateway)
    monkeypatch.setattr(server, "get_runtime", fake_runtime)
    fake.calls = calls
    monkeypatch.setattr(server, "build_supervisor", lambda model, tools, manager=None: fake)
    monkeypatch.setattr(server, "build_session_manager", lambda session_id, user_id: None)
    return fake


class FakeManager:
    def __init__(self, close_error: Exception | None = None):
        self.close_error = close_error
        self.closed = 0

    def close(self) -> None:
        self.closed += 1
        if self.close_error:
            raise self.close_error


@pytest.fixture
def manager(monkeypatch, supervisor):
    """Turn memory on with a fake manager; record what the supervisor gets."""
    fake = FakeManager()
    built: dict = {}

    def fake_build_session_manager(session_id, user_id):
        built["session_id"], built["user_id"] = session_id, user_id
        return fake

    def fake_build_supervisor(model, tools, manager=None):
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
    assert manager.built == {"session_id": "s1", "user_id": "u1", "manager": manager}
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


def test_close_error_is_logged_not_sent(supervisor, manager, caplog):
    manager.close_error = RuntimeError("bolt://user:pw@host")
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events[-1] == {"type": "complete"}
    assert "pw@host" not in str(events)
    assert "Error while closing the memory session manager" in caplog.text


def test_no_memory_manager_when_memory_is_off(supervisor, monkeypatch):
    seen: dict = {}

    def fake_build_supervisor(model, tools, manager=None):
        seen["manager"] = manager
        return supervisor

    monkeypatch.setattr(server, "build_supervisor", fake_build_supervisor)
    collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert seen == {"manager": None}


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


def test_gateway_token_is_prepared_on_the_request_path(supervisor):
    collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert supervisor.calls == ["prepare_request", "get_runtime"]


def test_gateway_token_failure_sends_generic_error(supervisor, monkeypatch, caplog):
    class BrokenGateway:
        async def prepare_request(self):
            raise RuntimeError("AccessDenied for provider fleet-gateway")

    monkeypatch.setattr(server, "gateway_auth", BrokenGateway)
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events == [{"type": "error", "error": server.GENERIC_ERROR}]
    assert "AccessDenied" in caplog.text


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


def test_startup_error_text_stays_in_the_log(supervisor, monkeypatch, caplog):
    async def failing_runtime():
        raise RuntimeError("bolt://user:pw@host")

    monkeypatch.setattr(server, "get_runtime", failing_runtime)
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events == [{"type": "error", "error": server.GENERIC_ERROR}]
    assert "bolt://user:pw@host" in caplog.text


class FakeClient:
    """Stands in for MCPClient. ``pages`` is the tool list the server returns."""

    def __init__(self, tools=("t",), list_error=None, stop_error=None):
        self.tools = list(tools)
        self.list_error = list_error
        self.stop_error = stop_error
        self.active = False
        self.stopped = False

    def start(self):
        self.active = True
        return self

    def list_tools_sync(self, pagination_token=None):
        if self.list_error:
            raise self.list_error
        page = [SimpleNamespace(tool_name=t, tool_spec={"name": t}) for t in self.tools]
        return Page(page)

    async def load_tools(self):
        """Mirror MCPClient.load_tools: start, wrap a start failure, list every page."""
        try:
            self.start()
        except Exception as error:
            raise ToolProviderException(f"Failed to start MCP client: {error}") from error
        tools, token = [], None
        while True:
            page = self.list_tools_sync(pagination_token=token)
            tools.extend(page)
            token = page.pagination_token
            if token is None:
                return tools

    def _is_session_active(self):
        return self.active

    def stop(self, *exc_info):
        self.stopped = True
        self.active = False
        if self.stop_error:
            raise self.stop_error


class Page(list):
    pagination_token = None


@pytest.fixture
def clients(monkeypatch):
    """Hand out the queued FakeClients in order and stub the model."""
    queue: list[FakeClient] = []
    monkeypatch.setattr(server, "_runtime", None)
    monkeypatch.setattr(server, "build_model", lambda: "model")
    monkeypatch.setattr(server, "gateway_auth", lambda: "gateway")
    monkeypatch.setattr(server, "build_mcp_client", lambda gateway: queue.pop(0))
    return queue


def test_runtime_is_reused_while_the_session_is_up(clients):
    clients.append(FakeClient())
    first = server._start_runtime()
    assert server._start_runtime() is first


def test_dead_session_is_rebuilt(clients):
    old, new = FakeClient(), FakeClient()
    clients.extend([old, new])
    first = server._start_runtime()
    old.active = False  # the Gateway dropped the session
    second = server._start_runtime()
    assert second.connection.client is new
    assert second.model == first.model
    assert second.tools == first.tools  # the tool wrappers and their specs are kept
    assert old.stopped


def test_get_runtime_rebuilds_a_dead_session(clients):
    import asyncio

    old, new = FakeClient(), FakeClient()
    clients.extend([old, new])
    asyncio.run(server.get_runtime())
    old.active = False
    assert asyncio.run(server.get_runtime()).connection.client is new


def test_startup_failure_stops_client_and_retries(clients):
    bad, good = FakeClient(list_error=ConnectionError("gateway down")), FakeClient()
    clients.extend([bad, good])
    with pytest.raises(ConnectionError):
        server._start_runtime()
    assert bad.stopped
    assert server._runtime is None
    assert server._start_runtime().connection.client is good


def test_empty_tool_list_is_an_error(clients):
    client = FakeClient(tools=())
    clients.append(client)
    with pytest.raises(RuntimeError, match="none of the specialist tools"):
        server._start_runtime()
    assert client.stopped
    assert server._runtime is None


def test_stop_error_does_not_mask_the_startup_error(clients, caplog):
    clients.append(FakeClient(list_error=ConnectionError("gateway down"), stop_error=OSError("x")))
    with pytest.raises(ConnectionError, match="gateway down"):
        server._start_runtime()
    assert "Error while stopping the MCP client" in caplog.text


def test_model_error_starts_no_client(monkeypatch, clients):
    def broken_model():
        raise ValueError("bad model id")

    monkeypatch.setattr(server, "build_model", broken_model)
    with pytest.raises(ValueError):
        server._start_runtime()
    assert clients == []  # build_mcp_client was never called


def test_session_check_uses_the_strands_private_method():
    # gateway_tools.session_is_running relies on MCPClient._is_session_active. If Strands
    # renames it, this test fails before the runtime does.
    from strands.tools.mcp import MCPClient

    assert callable(getattr(MCPClient, "_is_session_active", None))


def test_gateway_auth_is_built_once_and_failures_are_retried(monkeypatch):
    built: list[str] = []
    results = [ValueError("no credentials file"), "creds"]

    def fake_load_credentials():
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(server, "load_credentials", fake_load_credentials)
    monkeypatch.setattr(server, "build_gateway_auth", lambda c: built.append(c) or object())
    server.gateway_auth.cache_clear()
    try:
        with pytest.raises(ValueError):
            server.gateway_auth()
        assert server.gateway_auth() is server.gateway_auth()
        assert built == ["creds"]
    finally:
        server.gateway_auth.cache_clear()
