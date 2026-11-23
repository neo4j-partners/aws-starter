"""Tests for the FastMCP client operations in client/mcp_operations.py.

Each test runs the operations against a small local MCP server whose tools
carry a Gateway-style ``target___`` prefix, so the name mapping is exercised
without AWS.
"""

import asyncio
import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from mcp.server.mcpserver import MCPServer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "client"))

import mcp_operations  # noqa: E402

PREFIX = "target___"


def build_server() -> MCPServer:
    server = MCPServer("fake-neo4j")

    @server.tool(name=f"{PREFIX}get_neo4j_schema", description="Get the schema.\nMore text.")
    def get_neo4j_schema() -> str:
        return "schema: (:Account)-[:TRANSFER]->(:Account)"

    @server.tool(name=f"{PREFIX}read_neo4j_cypher", description="Run a read query.")
    def read_neo4j_cypher(query: str) -> str:
        if query == "FAIL":
            raise ValueError("query failed on purpose")
        return f"ran: {query}"

    return server


class RequestLog:
    """ASGI wrapper that records each HTTP request's method and auth header."""

    def __init__(self, app) -> None:
        self.app = app
        self.requests: list[tuple[str, str | None]] = []

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            auth = headers.get(b"authorization")
            self.requests.append((scope["method"], auth.decode() if auth else None))
        await self.app(scope, receive, send)


@pytest.fixture(scope="module")
def mcp_server() -> Iterator[tuple[str, RequestLog]]:
    # This server speaks MCP 2026-07-28, which has no session ID, so the client
    # sends no DELETE on close. Only a Gateway session exercises the DELETE.
    log = RequestLog(build_server().streamable_http_app())
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(log, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("local MCP server did not start")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/mcp", log
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


def run(url: str, operation, *args, headers: dict | None = None) -> None:
    asyncio.run(mcp_operations.connect_and_run(url, operation, *args, headers=headers))


def test_get_tool_map_strips_the_gateway_prefix(mcp_server) -> None:
    url, _ = mcp_server
    found: dict[str, str] = {}

    async def capture(session) -> None:
        found.update(await mcp_operations.get_tool_map(session))

    run(url, capture)
    assert found == {
        "get_neo4j_schema": f"{PREFIX}get_neo4j_schema",
        "read_neo4j_cypher": f"{PREFIX}read_neo4j_cypher",
    }


def test_resolve_tool_name_rejects_unknown_names() -> None:
    with pytest.raises(KeyError, match="Unknown tool: missing"):
        mcp_operations.resolve_tool_name({}, "missing")


def test_list_tools_prints_full_names(mcp_server, capsys) -> None:
    url, _ = mcp_server
    run(url, mcp_operations.list_tools)
    out = capsys.readouterr().out
    assert f"{PREFIX}get_neo4j_schema\n  Get the schema." in out
    assert f"{PREFIX}read_neo4j_cypher\n  Run a read query." in out


def test_get_schema_calls_the_prefixed_tool(mcp_server, capsys) -> None:
    url, _ = mcp_server
    run(url, mcp_operations.get_schema)
    assert "schema: (:Account)-[:TRANSFER]->(:Account)" in capsys.readouterr().out


def test_run_query_calls_the_prefixed_tool(mcp_server, capsys) -> None:
    url, _ = mcp_server
    run(url, mcp_operations.run_query)
    assert "ran: MATCH (n) RETURN labels(n)[0] as label" in capsys.readouterr().out


def test_run_full_tests_passes_each_tool(mcp_server, capsys) -> None:
    url, _ = mcp_server
    run(url, mcp_operations.run_full_tests)
    out = capsys.readouterr().out
    assert out.count("   PASSED") == 4
    assert "FAILED" not in out


def test_call_tool_prints_a_tool_error_as_a_result(mcp_server, capsys) -> None:
    url, _ = mcp_server
    run(url, mcp_operations.call_tool, f"{PREFIX}read_neo4j_cypher", '{"query": "FAIL"}')
    out = capsys.readouterr().out
    # The server hides the exception text and reports the tool that failed.
    assert out == f"Result: Error executing tool {PREFIX}read_neo4j_cypher\n"


def test_headers_reach_the_server(mcp_server) -> None:
    url, log = mcp_server
    log.requests.clear()
    run(url, mcp_operations.list_tools, headers={"Authorization": "Bearer test-token"})
    assert log.requests
    assert all(auth == "Bearer test-token" for _, auth in log.requests)


def test_client_uses_the_request_timeout(mcp_server, monkeypatch) -> None:
    url, _ = mcp_server
    seen: list[object] = []

    class RecordingClient(mcp_operations.Client):
        def __init__(self, *args, **kwargs) -> None:
            seen.append(kwargs.get("timeout"))
            super().__init__(*args, **kwargs)

    async def noop(session) -> None:
        return None

    monkeypatch.setattr(mcp_operations, "Client", RecordingClient)
    run(url, noop)
    assert seen == [mcp_operations.REQUEST_TIMEOUT]
