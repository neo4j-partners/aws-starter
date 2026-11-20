"""Gateway client setup, bearer-token auth, and tool listing. No network."""

import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest
from strands.tools.mcp import MCPClient

import fleet_supervisor.core.mcp as mcp_module
from fleet_supervisor.core.credentials import ClientCredentials, IdentityCredentials
from fleet_supervisor.core.mcp import (
    SPECIALIST_TOOL_FILTERS,
    AccessToken,
    BearerTokenAuth,
    build_mcp_client,
    client_credentials_fetcher,
    identity_fetcher,
    list_all_tools,
)

LOCAL = ClientCredentials(
    gateway_url="https://gateway.example/mcp",
    token_url="https://auth.example/oauth2/token",
    client_id="abc",
    client_secret="s3cret",
    scope="fleet/read",
)
CLOUD = IdentityCredentials(
    gateway_url="https://gateway.example/mcp", provider_name="fleet-gateway", scopes=("fleet/read",)
)


@pytest.fixture
def captured(monkeypatch):
    """Replace MCPClient with a recorder so no connection is made."""
    calls: list[dict] = []
    monkeypatch.setattr(mcp_module, "MCPClient", lambda **kwargs: calls.append(kwargs) or kwargs)
    return calls


def test_local_client_uses_bearer_auth(captured):
    build_mcp_client(LOCAL)
    (kwargs,) = captured
    assert kwargs["url"] == LOCAL.gateway_url
    assert isinstance(kwargs["auth_provider"], BearerTokenAuth)
    assert "auth" not in kwargs
    assert kwargs["tool_filters"] is SPECIALIST_TOOL_FILTERS


def test_cloud_client_uses_bearer_auth(captured, monkeypatch):
    monkeypatch.setattr(mcp_module, "identity_fetcher", lambda credentials: None)
    build_mcp_client(CLOUD)
    assert isinstance(captured[0]["auth_provider"], BearerTokenAuth)


def test_custom_filters_override_default(captured):
    custom = {"allowed": ["only_this"]}
    build_mcp_client(LOCAL, tool_filters=custom)
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


class TokenSource:
    """Hands out token-1, token-2, ... and counts fetches."""

    def __init__(self, lifetime: float = 3600):
        self.count = 0
        self.lifetime = lifetime

    async def __call__(self) -> AccessToken:
        self.count += 1
        return AccessToken(f"token-{self.count}", time.monotonic() + self.lifetime)


def gateway(valid: set[str], seen: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        seen.append(auth)
        return httpx.Response(200 if auth.removeprefix("Bearer ") in valid else 401)

    return httpx.MockTransport(handler)


def get_statuses(auth: httpx.Auth, transport: httpx.MockTransport, n: int) -> list[int]:
    async def run():
        async with httpx.AsyncClient(transport=transport, auth=auth) as client:
            return [(await client.get("https://gateway.example/mcp")).status_code for _ in range(n)]

    return asyncio.run(run())


def test_token_is_reused_until_it_expires():
    source, seen = TokenSource(), []
    statuses = get_statuses(BearerTokenAuth(source), gateway({"token-1"}, seen), 3)
    assert statuses == [200, 200, 200]
    assert source.count == 1
    assert seen == ["Bearer token-1"] * 3


def test_expired_token_is_refreshed():
    source, seen = TokenSource(lifetime=-1), []
    get_statuses(BearerTokenAuth(source), gateway({"token-1", "token-2"}, seen), 2)
    assert seen == ["Bearer token-1", "Bearer token-2"]


def test_401_refreshes_once_and_retries():
    source, seen = TokenSource(), []
    statuses = get_statuses(BearerTokenAuth(source), gateway({"token-2"}, seen), 1)
    assert statuses == [200]
    assert seen == ["Bearer token-1", "Bearer token-2"]


def test_repeated_401_is_returned_not_looped():
    source, seen = TokenSource(), []
    assert get_statuses(BearerTokenAuth(source), gateway(set(), seen), 1) == [401]
    assert len(seen) == 2


def test_client_credentials_posts_to_token_url_only(monkeypatch):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"access_token": "jwt", "expires_in": 3600})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        mcp_module.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    token = asyncio.run(client_credentials_fetcher(LOCAL)())
    assert token.value == "jwt"
    (request,) = requests
    assert str(request.url) == LOCAL.token_url
    assert request.headers["Authorization"].startswith("Basic ")
    body = request.content.decode()
    assert "grant_type=client_credentials" in body
    assert "scope=fleet%2Fread" in body
    assert "s3cret" not in body


class FakeIdentityClient:
    calls: list[dict] = []

    def __init__(self, region: str):
        pass

    async def get_token(self, **kwargs):
        FakeIdentityClient.calls.append(kwargs)
        return "m2m-token"


def test_identity_fetcher_uses_latest_workload_token(monkeypatch):
    import bedrock_agentcore.services.identity as identity

    monkeypatch.setattr(identity, "IdentityClient", FakeIdentityClient)
    FakeIdentityClient.calls = []
    fetch = identity_fetcher(CLOUD)

    monkeypatch.setattr(mcp_module, "_workload_token", None)
    with pytest.raises(RuntimeError, match="workload access token"):
        asyncio.run(fetch())

    monkeypatch.setattr(mcp_module, "_workload_token", "wat-1")
    assert asyncio.run(fetch()).value == "m2m-token"
    (call,) = FakeIdentityClient.calls
    assert call["provider_name"] == "fleet-gateway"
    assert call["agent_identity_token"] == "wat-1"
    assert call["auth_flow"] == "M2M"
    assert call["scopes"] == ["fleet/read"]


def test_remember_workload_token_copies_context(monkeypatch):
    from bedrock_agentcore.runtime import BedrockAgentCoreContext

    monkeypatch.setattr(mcp_module, "_workload_token", None)
    monkeypatch.setattr(BedrockAgentCoreContext, "get_workload_access_token", lambda: None)
    mcp_module.remember_workload_token()
    assert mcp_module._workload_token is None
    monkeypatch.setattr(BedrockAgentCoreContext, "get_workload_access_token", lambda: "wat-9")
    mcp_module.remember_workload_token()
    assert mcp_module._workload_token == "wat-9"


class Page(list):
    def __init__(self, items, token):
        super().__init__(items)
        self.pagination_token = token


def test_list_all_tools_follows_pagination():
    pages = {None: Page(["a"], "p2"), "p2": Page(["b"], "p3"), "p3": Page(["c"], None)}
    client = SimpleNamespace(list_tools_sync=lambda pagination_token=None: pages[pagination_token])
    assert list_all_tools(client) == ["a", "b", "c"]
