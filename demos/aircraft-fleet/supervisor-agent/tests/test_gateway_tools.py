"""GatewayTool's reconnect-and-retry, driven through the real runtime rebuild."""

import asyncio
import logging

import pytest
from strands.types.events import ToolResultEvent
from strands.types.exceptions import MCPClientInitializationError, ToolProviderException

from fleet_supervisor import server
from fleet_supervisor.core.gateway_tools import (
    REQUEST_SESSION_ID,
    SESSION_TERMINATED_TEXT,
    GatewayTool,
    stop_quietly,
)
from fleet_supervisor.core.tool_errors import UNAVAILABLE_RESULT

TOOL = "fleet___read_neo4j_cypher"


class FakeTool:
    """Stands in for MCPAgentTool. It calls its own client, like the real one."""

    def __init__(self, client, name, spec):
        self.client = client
        self.tool_name = name
        self._spec = spec
        self.spec_reads = 0

    @property
    def tool_spec(self):
        self.spec_reads += 1
        return self._spec

    async def stream(self, tool_use, invocation_state, **kwargs):
        yield ToolResultEvent(await self.client.call(tool_use))


class FakeClient:
    """Stands in for MCPClient.

    ``reply`` and ``status`` are the tool result while the session is up. ``gate``, when set,
    holds a call in flight until the test releases it. A call that started
    while the session was up but ends after it went down returns an error
    result, as Strands does. A call made while it is down raises.
    """

    def __init__(
        self,
        tools=(TOOL,),
        spec=None,
        reply="ok",
        status="success",
        fail_start=None,
        terminated=False,
    ):
        self.tool_names = list(tools)
        self.spec = spec or {"name": TOOL, "description": "first"}
        self.reply = reply
        self.status = status
        self.fail_start = fail_start
        # Every call gets the SDK's 404 result while the session looks active.
        self.terminated = terminated
        self.gate: asyncio.Event | None = None
        self.active = False
        self.stopped = False
        self.calls = 0
        self.tools: list[FakeTool] = []

    def start(self):
        if self.fail_start:
            raise self.fail_start
        self.active = True
        return self

    def list_tools_sync(self, pagination_token=None):
        self.tools = [FakeTool(self, name, self.spec) for name in self.tool_names]
        return Page(self.tools)

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

    async def call(self, tool_use):
        if not self.active:
            raise MCPClientInitializationError("the client session is not running")
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.terminated:
            return {
                "toolUseId": tool_use["toolUseId"],
                "status": "error",
                "content": [{"text": SESSION_TERMINATED_TEXT}],
            }
        if not self.active:
            return {
                "toolUseId": tool_use["toolUseId"],
                "status": "error",
                "content": [{"text": "Tool execution failed: connection closed"}],
            }
        return {
            "toolUseId": tool_use["toolUseId"],
            "status": self.status,
            "content": [{"text": self.reply}],
        }


class Page(list):
    pagination_token = None


class Queue(list):
    """The clients still to hand out. ``built`` records the ones handed out."""

    built: list[FakeClient]


@pytest.fixture
def clients(monkeypatch):
    """Hand out the queued FakeClients in order. Record each build."""
    queue = Queue()
    built: list[FakeClient] = []

    def next_client(gateway):
        client = queue.pop(0)
        built.append(client)
        return client

    monkeypatch.setattr(server, "_runtime", None)
    monkeypatch.setattr(server, "build_model", lambda: "model")
    monkeypatch.setattr(server, "gateway_auth", lambda: "gateway")
    monkeypatch.setattr(server, "build_mcp_client", next_client)
    queue.built = built
    return queue


def use(tool_use_id="u1"):
    return {"toolUseId": tool_use_id, "name": TOOL, "input": {"query": "MATCH (n) RETURN n"}}


async def run_tool(tool: GatewayTool, tool_use_id="u1"):
    events = [event async for event in tool.stream(use(tool_use_id), {})]
    assert len(events) == 1
    return events[0].tool_result


def text(result):
    return result["content"][0]["text"]


async def start(clients):
    runtime = await server.get_runtime()
    (tool,) = runtime.tools
    return runtime, tool


def rebuild_logs(caplog):
    return [
        r for r in caplog.records if r.getMessage().startswith("Rebuilding the Gateway MCP client")
    ]


def test_call_after_the_session_ended_rebuilds_and_retries(clients, caplog):
    old, new = FakeClient(), FakeClient(reply="rows")
    clients.extend([old, new])

    async def scenario():
        REQUEST_SESSION_ID.set("sess-1")
        runtime, tool = await start(clients)
        old.active = False  # the Gateway dropped the session
        return runtime, await run_tool(tool)

    runtime, result = asyncio.run(scenario())
    assert (result["status"], text(result)) == ("success", "rows")
    assert runtime.connection.client is new
    assert old.stopped
    (record,) = rebuild_logs(caplog)
    assert record.levelno == logging.WARNING
    assert "session=sess-1" in record.getMessage()
    assert "cause=MCPClientInitializationError" in caplog.text


def test_in_flight_error_result_rebuilds_and_retries(clients, caplog):
    old, new = FakeClient(), FakeClient(reply="rows")
    clients.extend([old, new])

    async def scenario():
        _, tool = await start(clients)
        old.gate = asyncio.Event()
        call = asyncio.create_task(run_tool(tool))
        await asyncio.sleep(0)
        old.active = False  # the session ends while the call is in flight
        old.gate.set()
        return await call

    result = asyncio.run(scenario())
    assert (result["status"], text(result)) == ("success", "rows")
    assert "connection closed" not in str(result)
    assert "cause=ErrorResultWhileSessionDown" in caplog.text
    assert len(rebuild_logs(caplog)) == 1


def test_one_rebuild_for_callers_that_find_the_session_dead_at_different_times(clients, caplog):
    caplog.set_level(logging.INFO)
    old, new = FakeClient(), FakeClient(reply="rows")
    clients.extend([old, new])

    async def scenario():
        _, tool = await start(clients)
        # B is in flight on the old client when the session ends.
        old.gate = asyncio.Event()
        late = asyncio.create_task(run_tool(tool, "b"))
        await asyncio.sleep(0)
        old.active = False
        # A arrives next, finds the session dead, and rebuilds.
        early = await run_tool(tool, "a")
        # B still holds the old client, so the rebuild has not stopped it yet.
        stopped_while_held = old.stopped
        # B's call now fails. It passes the old connection, sees the new one,
        # and reuses it instead of rebuilding again.
        old.gate.set()
        return early, await late, stopped_while_held

    early, late, stopped_while_held = asyncio.run(scenario())
    assert [text(early), text(late)] == ["rows", "rows"]
    assert clients.built == [old, new]  # the first build and one rebuild
    assert len(rebuild_logs(caplog)) == 1
    assert new.calls == 2
    assert not stopped_while_held
    assert old.stopped  # stopped once B let go
    assert "Stopped the replaced MCP client after its last call" in caplog.text


def test_a_request_after_the_rebuild_uses_the_new_client(clients):
    old, new = FakeClient(), FakeClient(reply="rows")
    clients.extend([old, new])

    async def scenario():
        _, tool = await start(clients)
        old.active = False
        await run_tool(tool, "a")
        return await run_tool(tool, "b")

    assert text(asyncio.run(scenario())) == "rows"
    assert clients.built == [old, new]
    assert new.calls == 2


def test_only_one_retry_then_the_fixed_unavailable_result(clients, caplog):
    old, new = FakeClient(), FakeClient()
    clients.extend([old, new])

    async def scenario():
        _, tool = await start(clients)
        old.active = False
        # The rebuilt session is down too by the time the retry runs.
        new.start = lambda: setattr(new, "active", False) or new
        return await run_tool(tool)

    result = asyncio.run(scenario())
    assert result["status"] == "error"
    assert text(result) == UNAVAILABLE_RESULT
    assert clients.built == [old, new]
    assert "the retry failed too" in caplog.text


def test_failed_rebuild_returns_unavailable_and_the_next_request_rebuilds(clients, caplog):
    old = FakeClient()
    broken = FakeClient(fail_start=PermissionError("401 from https://gw.example/mcp"))
    good = FakeClient(reply="rows")
    clients.extend([old, broken, good])

    async def scenario():
        runtime, tool = await start(clients)
        old.active = False
        first = await run_tool(tool)
        assert runtime.connection is None
        await server.get_runtime()  # the next request
        return first, await run_tool(tool)

    first, second = asyncio.run(scenario())
    assert text(first) == UNAVAILABLE_RESULT
    assert "cause=PermissionError" in caplog.text
    assert "gw.example" not in "".join(
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    )
    assert text(second) == "rows"
    assert broken.stopped


def test_session_terminated_result_rebuilds_and_retries(clients, caplog):
    caplog.set_level(logging.INFO)
    old, new = FakeClient(terminated=True), FakeClient(reply="rows")
    clients.extend([old, new])

    async def scenario():
        _, tool = await start(clients)
        return await run_tool(tool)

    result = asyncio.run(scenario())
    assert (result["status"], text(result)) == ("success", "rows")
    assert "cause=SessionTerminated" in caplog.text
    assert clients.built == [old, new]
    assert len(rebuild_logs(caplog)) == 1
    assert old.stopped


def test_session_terminated_on_the_retry_marks_the_new_client_stale(clients, caplog):
    old, new = FakeClient(terminated=True), FakeClient(terminated=True)
    good = FakeClient(reply="rows")
    clients.extend([old, new, good])

    async def scenario():
        runtime, tool = await start(clients)
        first = await run_tool(tool)
        # The client thread is still up, but the next request must rebuild.
        assert new.active
        assert not runtime.connection.is_running()
        await server.get_runtime()  # the next request
        return first, await run_tool(tool)

    first, second = asyncio.run(scenario())
    assert text(first) == UNAVAILABLE_RESULT
    assert "the retry failed too" in caplog.text
    assert text(second) == "rows"
    assert clients.built == [old, new, good]


def test_session_terminated_text_matches_the_sdk_and_strands():
    """Pin the text: the MCP SDK's 404 error as Strands turns it into a result."""
    import anyio
    from mcp.client.streamable_http import StreamableHTTPTransport
    from mcp.shared.exceptions import McpError
    from strands.tools.mcp import MCPClient

    async def sdk_error():
        writer, reader = anyio.create_memory_object_stream(1)
        transport = StreamableHTTPTransport("http://127.0.0.1:9/mcp")
        await transport._send_session_terminated_error(writer, 1)
        return (await reader.receive()).message.root.error

    error = anyio.run(sdk_error)
    client = MCPClient(lambda: None)
    result = client._handle_tool_execution_error("u1", McpError(error))
    assert text(result) == SESSION_TERMINATED_TEXT


def test_stop_failure_logs_the_class_at_warning_and_details_at_debug(caplog):
    caplog.set_level(logging.DEBUG)

    class Failing:
        def stop(self, *exc_info):
            raise RuntimeError("session ended: 404 from https://gw.example/mcp")

    stop_quietly(Failing())
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [r.getMessage() for r in warnings] == [
        "Error while stopping the MCP client (cause=RuntimeError)"
    ]
    assert any(r.levelno == logging.DEBUG and r.exc_info for r in caplog.records)


def test_tool_missing_after_rebuild_returns_unavailable(clients):
    old, new = FakeClient(), FakeClient(tools=("fleet___get_neo4j_schema",))
    clients.extend([old, new])

    async def scenario():
        _, tool = await start(clients)
        old.active = False
        return await run_tool(tool)

    assert text(asyncio.run(scenario())) == UNAVAILABLE_RESULT


def test_query_error_from_a_live_session_is_scrubbed_not_retried(clients, caplog):
    raw = (
        "Error calling tool 'read_neo4j_cypher': {neo4j_code: Neo.ClientError.Statement."
        "SyntaxError} {message: Invalid input 'MATC'} {gql_status: 42001}"
    )
    client = FakeClient(reply=raw, status="error")
    clients.append(client)

    async def scenario():
        REQUEST_SESSION_ID.set("sess-q")
        _, tool = await start(clients)
        return await run_tool(tool)

    result = asyncio.run(scenario())
    assert result["status"] == "error"
    assert result["toolUseId"] == "u1"
    assert text(result) == (
        "The generated Cypher query failed: Neo.ClientError.Statement.SyntaxError:"
        " Invalid input 'MATC'\nRephrase the question to fit the schema and try again."
    )
    assert client.calls == 1
    assert clients.built == [client]
    (record,) = [r for r in caplog.records if "tool error" in r.getMessage()]
    assert record.levelno == logging.WARNING
    assert "session=sess-q, kind=query, code=Neo.ClientError.Statement.SyntaxError" in (
        record.getMessage()
    )
    assert raw in record.getMessage()


def test_unreachable_database_from_a_live_session_is_unavailable(clients, caplog):
    raw = "Error calling tool 'read_neo4j_cypher': Couldn't connect to db.internal:7687"
    client = FakeClient(reply=raw, status="error")
    clients.append(client)

    async def scenario():
        _, tool = await start(clients)
        return await run_tool(tool)

    result = asyncio.run(scenario())
    assert text(result) == UNAVAILABLE_RESULT
    assert "db.internal" not in str(result)
    assert client.calls == 1  # the session is up, so this is not a session retry
    (record,) = [r for r in caplog.records if "tool error" in r.getMessage()]
    assert record.levelno == logging.ERROR
    assert "kind=unavailable" in record.getMessage()
    assert raw in record.getMessage()


def test_in_flight_error_text_never_reaches_the_model_after_a_failed_retry(clients):
    old, new = FakeClient(), FakeClient()
    clients.extend([old, new])

    async def scenario():
        _, tool = await start(clients)
        old.gate = asyncio.Event()
        call = asyncio.create_task(run_tool(tool))
        await asyncio.sleep(0)
        old.active = False
        new.start = lambda: setattr(new, "active", False) or new
        old.gate.set()
        return await call

    result = asyncio.run(scenario())
    assert text(result) == UNAVAILABLE_RESULT
    assert "connection closed" not in str(result)


def test_success_results_pass_through_unchanged(clients):
    client = FakeClient(reply='[{"n": 1}]')
    clients.append(client)

    async def scenario():
        _, tool = await start(clients)
        return await run_tool(tool)

    assert asyncio.run(scenario()) == {
        "toolUseId": "u1",
        "status": "success",
        "content": [{"text": '[{"n": 1}]'}],
    }


def test_spec_is_read_once_and_kept_across_rebuilds(clients):
    old = FakeClient(spec={"name": TOOL, "description": "first"})
    new = FakeClient(spec={"name": TOOL, "description": "second"})
    clients.extend([old, new])

    async def scenario():
        _, tool = await start(clients)
        old.active = False
        await run_tool(tool)
        return tool

    tool = asyncio.run(scenario())
    assert tool.tool_spec == {"name": TOOL, "description": "first"}
    assert tool.tool_spec is tool.tool_spec
    assert old.tools[0].spec_reads == 1
    assert new.tools[0].spec_reads == 0
