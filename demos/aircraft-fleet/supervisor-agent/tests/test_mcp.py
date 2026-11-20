"""Gateway client setup, bearer-token auth, and tool listing. No network."""

import asyncio
import base64
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from strands.tools.mcp import MCPClient

import fleet_supervisor.core.mcp as mcp_module
from fleet_supervisor.core.credentials import ClientCredentials, IdentityCredentials
from fleet_supervisor.core.mcp import (
    M2M_AUTH_FLOW,
    SPECIALIST_TOOL_FILTERS,
    TOKEN_EXPIRY_MARGIN_S,
    UNREADABLE_EXPIRY_MAX_AGE_S,
    AccessToken,
    BearerTokenAuth,
    GatewayAuth,
    IdentityTokens,
    build_gateway_auth,
    build_mcp_client,
    client_credentials_fetcher,
    jwt_deadline,
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
    gateway = build_gateway_auth(LOCAL)
    build_mcp_client(gateway)
    (kwargs,) = captured
    assert kwargs["url"] == LOCAL.gateway_url
    assert kwargs["auth_provider"] is gateway.auth
    assert "auth" not in kwargs
    assert kwargs["tool_filters"] is SPECIALIST_TOOL_FILTERS
    assert gateway.identity is None


def test_cloud_gateway_auth_uses_identity(monkeypatch):
    import bedrock_agentcore.services.identity as identity

    monkeypatch.setattr(identity, "IdentityClient", FakeIdentityClient)
    gateway = build_gateway_auth(CLOUD)
    assert isinstance(gateway.auth, BearerTokenAuth)
    assert isinstance(gateway.identity, IdentityTokens)
    assert gateway.gateway_url == CLOUD.gateway_url


def test_custom_filters_override_default(captured):
    custom = {"allowed": ["only_this"]}
    build_mcp_client(build_gateway_auth(LOCAL), tool_filters=custom)
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
    """Hands out token-1, token-2, ... and records each fetch's force flag."""

    def __init__(self, lifetime: float = 3600):
        self.count = 0
        self.lifetime = lifetime
        self.forced: list[bool] = []

    async def __call__(self, force: bool) -> AccessToken:
        self.count += 1
        self.forced.append(force)
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


def test_401_forces_one_refresh_and_retries():
    source, seen = TokenSource(), []
    statuses = get_statuses(BearerTokenAuth(source), gateway({"token-2"}, seen), 1)
    assert statuses == [200]
    assert seen == ["Bearer token-1", "Bearer token-2"]
    assert source.forced == [False, True]


def test_auth_works_across_event_loops():
    # A rebuilt MCP client runs a new loop; the shared auth must keep working.
    source, seen = TokenSource(lifetime=-1), []
    auth = BearerTokenAuth(source)
    transport = gateway({"token-1", "token-2", "token-3"}, seen)
    assert get_statuses(auth, transport, 1) == [200]
    assert get_statuses(auth, transport, 1) == [200]
    assert source.count == 2


def test_token_set_on_the_request_path_is_used_without_a_fetch():
    source, seen = TokenSource(), []
    auth = BearerTokenAuth(source)
    assert auth.needs_token()
    auth.set_token(AccessToken("pushed", time.monotonic() + 600))
    assert not auth.needs_token()
    assert get_statuses(auth, gateway({"pushed"}, seen), 2) == [200, 200]
    assert source.count == 0


def test_rejected_pushed_token_is_replaced_by_a_forced_fetch():
    source, seen = TokenSource(), []
    auth = BearerTokenAuth(source)
    auth.set_token(AccessToken("stale", time.monotonic() + 600))
    assert get_statuses(auth, gateway({"token-1"}, seen), 1) == [200]
    assert seen == ["Bearer stale", "Bearer token-1"]
    assert source.forced == [True]


def test_expired_pushed_token_needs_a_new_one():
    auth = BearerTokenAuth(TokenSource())
    auth.set_token(AccessToken("old", time.monotonic() - 1))
    assert auth.needs_token()


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
    token = asyncio.run(client_credentials_fetcher(LOCAL)(False))
    assert token.value == "jwt"
    (request,) = requests
    assert str(request.url) == LOCAL.token_url
    assert request.headers["Authorization"].startswith("Basic ")
    body = request.content.decode()
    assert "grant_type=client_credentials" in body
    assert "scope=fleet%2Fread" in body
    assert "s3cret" not in body


def make_jwt(claims: dict) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256'})}.{part(claims)}.signature"


def test_jwt_deadline_uses_the_exp_claim_minus_the_margin():
    token = make_jwt({"exp": time.time() + 3600})
    expected = time.monotonic() + 3600 - TOKEN_EXPIRY_MARGIN_S
    assert jwt_deadline(token) == pytest.approx(expected, abs=2)


@pytest.mark.parametrize("token", ["not-a-jwt", make_jwt({"sub": "x"}), "a.!!!.c"])
def test_jwt_deadline_without_a_readable_exp_is_short(token):
    expected = time.monotonic() + UNREADABLE_EXPIRY_MAX_AGE_S
    assert jwt_deadline(token) == pytest.approx(expected, abs=2)


class FakeIdentityClient:
    calls: list[dict] = []
    threads: list[str] = []

    def __init__(self, region: str):
        pass

    async def get_token(self, **kwargs):
        FakeIdentityClient.calls.append(kwargs)
        FakeIdentityClient.threads.append(threading.current_thread().name)
        return make_jwt({"exp": time.time() + 3600})


@pytest.fixture
def identity(monkeypatch):
    import bedrock_agentcore.services.identity as identity_module

    monkeypatch.setattr(identity_module, "IdentityClient", FakeIdentityClient)
    FakeIdentityClient.calls, FakeIdentityClient.threads = [], []
    return IdentityTokens(CLOUD)


@pytest.fixture
def workload_token(monkeypatch):
    """Set what the runtime context reports as the request's workload token."""
    from bedrock_agentcore.runtime import BedrockAgentCoreContext

    current = {"token": None}
    monkeypatch.setattr(
        BedrockAgentCoreContext, "get_workload_access_token", lambda: current["token"]
    )
    return current


def test_identity_fetch_needs_a_workload_token(identity, workload_token):
    identity.remember_workload_token()
    with pytest.raises(RuntimeError, match="workload access token"):
        asyncio.run(identity.fetch(False))
    assert FakeIdentityClient.calls == []


def test_identity_fetch_passes_m2m_scopes_and_force(identity, workload_token):
    workload_token["token"] = "wat-1"
    identity.remember_workload_token()
    token = asyncio.run(identity.fetch(True))
    (call,) = FakeIdentityClient.calls
    assert call["provider_name"] == "fleet-gateway"
    assert call["agent_identity_token"] == "wat-1"
    assert call["auth_flow"] == M2M_AUTH_FLOW == "M2M"
    assert call["scopes"] == ["fleet/read"]
    assert call["force_authentication"] is True
    assert token.expires_at > time.monotonic() + 3000
    # The blocking boto3 call runs in a worker thread, not on the caller's loop.
    assert FakeIdentityClient.threads != [threading.current_thread().name]


def test_missing_workload_token_clears_the_previous_one(identity, workload_token, caplog):
    workload_token["token"] = "wat-1"
    assert identity.remember_workload_token() == "wat-1"
    workload_token["token"] = None
    assert identity.remember_workload_token() is None
    assert "no workload access token" in caplog.text
    with pytest.raises(RuntimeError, match="workload access token"):
        asyncio.run(identity.fetch(False))


def test_prepare_request_fetches_only_when_needed(identity, workload_token):
    gateway = GatewayAuth(CLOUD.gateway_url, BearerTokenAuth(identity.fetch), identity)
    workload_token["token"] = "wat-1"
    asyncio.run(gateway.prepare_request())
    asyncio.run(gateway.prepare_request())
    assert len(FakeIdentityClient.calls) == 1
    assert FakeIdentityClient.calls[0]["force_authentication"] is False
    assert not gateway.auth.needs_token()


def test_prepare_request_without_a_workload_token_skips_the_fetch(identity, workload_token):
    gateway = GatewayAuth(CLOUD.gateway_url, BearerTokenAuth(identity.fetch), identity)
    asyncio.run(gateway.prepare_request())
    assert FakeIdentityClient.calls == []
    assert gateway.auth.needs_token()


def test_prepare_request_does_nothing_on_the_local_path():
    gateway = build_gateway_auth(LOCAL)
    asyncio.run(gateway.prepare_request())
    assert gateway.auth.needs_token()


class Page(list):
    def __init__(self, items, token):
        super().__init__(items)
        self.pagination_token = token


def test_list_all_tools_follows_pagination():
    pages = {None: Page(["a"], "p2"), "p2": Page(["b"], "p3"), "p3": Page(["c"], None)}
    client = SimpleNamespace(list_tools_sync=lambda pagination_token=None: pages[pagination_token])
    assert list_all_tools(client) == ["a", "b", "c"]
