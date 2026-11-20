"""The AgentCore entrypoint, with the runtime and supervisor stubbed."""

import uuid
from types import SimpleNamespace

import pytest

from server import runtime_app
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

    async def fake_runtime():
        return SimpleNamespace(model=object(), tools=[])

    monkeypatch.setattr(runtime_app, "get_runtime", fake_runtime)
    monkeypatch.setattr(runtime_app, "build_supervisor", lambda model, tools: fake)
    return fake


def test_streams_agent_chunk_and_complete(supervisor):
    events = collect(
        runtime_app.invoke({"prompt": "How many flights?"}, SimpleNamespace(session_id="s1"))
    )
    assert events == [
        {"type": "agent", "name": "Operations Agent"},
        {"type": "chunk", "data": "42 flights"},
        {"type": "complete"},
    ]
    assert supervisor.prompts == ["How many flights?"]


@pytest.mark.parametrize("key", ["prompt", "message", "query", "inputText", "input"])
def test_accepts_common_prompt_keys(supervisor, key):
    collect(runtime_app.invoke({key: "hi"}, SimpleNamespace(session_id="s1")))
    assert supervisor.prompts == ["hi"]


def test_missing_prompt_is_an_error(supervisor):
    events = collect(runtime_app.invoke({}, SimpleNamespace(session_id="s1")))
    assert [e["type"] for e in events] == ["error"]
    assert supervisor.prompts == []


def test_failure_sends_generic_error(supervisor, caplog):
    supervisor.error = RuntimeError("secret connection string")
    events = collect(runtime_app.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events[-1] == {"type": "error", "error": runtime_app.GENERIC_ERROR}
    assert "secret connection string" not in str(events)
    assert "secret connection string" in caplog.text


def test_session_id_comes_from_context(supervisor, caplog):
    caplog.set_level("INFO")
    collect(runtime_app.invoke({"prompt": "q"}, SimpleNamespace(session_id="abc-123")))
    assert "session=abc-123" in caplog.text


def test_missing_session_id_gets_a_fresh_uuid(supervisor, caplog):
    caplog.set_level("INFO")
    collect(runtime_app.invoke({"prompt": "q"}, SimpleNamespace(session_id=None)))
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("Request "))
    session = line.split("session=")[1].split()[0]
    assert uuid.UUID(session)
    assert "default" not in line


@pytest.mark.parametrize(
    "payload", [None, "a string", ["prompt"], {"prompt": 42}, {"prompt": "  "}]
)
def test_bad_payload_gets_a_fixed_message(supervisor, payload):
    events = collect(runtime_app.invoke(payload, SimpleNamespace(session_id="s1")))
    assert events == [{"type": "error", "error": runtime_app.NO_PROMPT_ERROR}]
    assert supervisor.prompts == []


def test_non_string_user_id_does_not_raise(supervisor):
    events = collect(
        runtime_app.invoke({"prompt": "q", "user_id": {"x": 1}}, SimpleNamespace(session_id="s1"))
    )
    assert events[-1] == {"type": "complete"}


def test_startup_error_text_stays_in_the_log(monkeypatch, caplog):
    async def failing_runtime():
        raise RuntimeError("bolt://user:pw@host")

    monkeypatch.setattr(runtime_app, "get_runtime", failing_runtime)
    events = collect(runtime_app.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events == [{"type": "error", "error": runtime_app.GENERIC_ERROR}]
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
        page = [SimpleNamespace(tool_name=t) for t in self.tools]
        return Page(page)

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
    monkeypatch.setattr(runtime_app, "_runtime", None)
    monkeypatch.setattr(runtime_app, "build_model", lambda: "model")
    monkeypatch.setattr(runtime_app, "load_credentials", lambda: "creds")
    monkeypatch.setattr(runtime_app, "build_mcp_client", lambda credentials: queue.pop(0))
    return queue


def test_runtime_is_reused_while_the_session_is_up(clients):
    clients.append(FakeClient())
    first = runtime_app._start_runtime()
    assert runtime_app._start_runtime() is first


def test_dead_session_is_rebuilt(clients):
    old, new = FakeClient(), FakeClient()
    clients.extend([old, new])
    first = runtime_app._start_runtime()
    old.active = False  # the Gateway dropped the session
    second = runtime_app._start_runtime()
    assert second.mcp_client is new
    assert second.model == first.model
    assert old.stopped


def test_get_runtime_rebuilds_a_dead_session(clients):
    import asyncio

    old, new = FakeClient(), FakeClient()
    clients.extend([old, new])
    asyncio.run(runtime_app.get_runtime())
    old.active = False
    assert asyncio.run(runtime_app.get_runtime()).mcp_client is new


def test_startup_failure_stops_client_and_retries(clients):
    bad, good = FakeClient(list_error=ConnectionError("gateway down")), FakeClient()
    clients.extend([bad, good])
    with pytest.raises(ConnectionError):
        runtime_app._start_runtime()
    assert bad.stopped
    assert runtime_app._runtime is None
    assert runtime_app._start_runtime().mcp_client is good


def test_empty_tool_list_is_an_error(clients):
    client = FakeClient(tools=())
    clients.append(client)
    with pytest.raises(RuntimeError, match="none of the specialist tools"):
        runtime_app._start_runtime()
    assert client.stopped
    assert runtime_app._runtime is None


def test_stop_error_does_not_mask_the_startup_error(clients, caplog):
    clients.append(FakeClient(list_error=ConnectionError("gateway down"), stop_error=OSError("x")))
    with pytest.raises(ConnectionError, match="gateway down"):
        runtime_app._start_runtime()
    assert "Error while stopping the MCP client" in caplog.text


def test_model_error_starts_no_client(monkeypatch, clients):
    def broken_model():
        raise ValueError("bad model id")

    monkeypatch.setattr(runtime_app, "build_model", broken_model)
    with pytest.raises(ValueError):
        runtime_app._start_runtime()
    assert clients == []  # build_mcp_client was never called


def test_session_check_uses_the_strands_private_method():
    # _session_is_running relies on MCPClient._is_session_active. If Strands
    # renames it, this test fails before the runtime does.
    from strands.tools.mcp import MCPClient

    assert callable(getattr(MCPClient, "_is_session_active", None))
