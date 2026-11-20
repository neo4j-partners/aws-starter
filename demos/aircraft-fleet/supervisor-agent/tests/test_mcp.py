"""Gateway client setup and the specialist tool filter, with MCPClient stubbed."""

from types import SimpleNamespace

import pytest
from strands.tools.mcp import MCPClient

import core.mcp as mcp_module
from core.mcp import SPECIALIST_TOOL_FILTERS, build_mcp_client

CREDENTIALS = {
    "gateway_url": "https://gateway.example/mcp",
    "client_id": "abc",
    "client_secret": "s3cret",
}


@pytest.fixture
def captured(monkeypatch):
    """Replace MCPClient with a recorder so no connection is made."""
    calls: list[dict] = []
    monkeypatch.setattr(mcp_module, "MCPClient", lambda **kwargs: calls.append(kwargs) or kwargs)
    return calls


def test_client_uses_client_credentials_auth(captured):
    build_mcp_client(CREDENTIALS)
    (kwargs,) = captured
    assert kwargs["url"] == CREDENTIALS["gateway_url"]
    assert kwargs["auth"] == {"client_id": "abc", "client_secret": "s3cret"}
    assert kwargs["tool_filters"] is SPECIALIST_TOOL_FILTERS


def test_scope_is_split_into_scopes(captured):
    build_mcp_client({**CREDENTIALS, "scope": "fleet/read fleet/schema"})
    assert captured[0]["auth"]["scopes"] == ["fleet/read", "fleet/schema"]


def test_custom_filters_override_default(captured):
    custom = {"allowed": ["only_this"]}
    build_mcp_client(CREDENTIALS, tool_filters=custom)
    assert captured[0]["tool_filters"] is custom


@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        ("neo4j-mcp-server-target___get_neo4j_schema", True),
        ("neo4j-mcp-server-target___read_neo4j_cypher", True),
        ("neo4j-mcp-server-target___write_neo4j_cypher", False),
        ("x_amz_bedrock_agentcore_search", False),
        ("neo4j-mcp-server-target___read_neo4j_cypher_v2", False),
    ],
)
def test_filter_allows_only_read_and_schema_tools(name, allowed):
    # Use the MCPClient's own filter check so the test follows Strands' matching rules.
    client = MCPClient.__new__(MCPClient)
    tool = SimpleNamespace(mcp_tool=SimpleNamespace(name=name))
    assert client._should_include_tool_with_filters(tool, SPECIALIST_TOOL_FILTERS) is allowed
