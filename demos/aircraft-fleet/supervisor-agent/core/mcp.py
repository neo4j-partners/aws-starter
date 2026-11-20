"""Gateway MCP client and its auth.

All Gateway auth lives in this module. :func:`build_mcp_client` picks one of
two token sources and hands it to :class:`BearerTokenAuth`:

- Local (:class:`ClientCredentials`): the OAuth client_credentials grant,
  posted straight to the ``token_url`` from the credentials file. There is no
  OAuth discovery, so the client secret only ever goes to that URL. The MCP
  server cannot redirect it to another authorization server.
- Cloud (:class:`IdentityCredentials`): an M2M token from AgentCore Identity.
  The runtime holds no secret.
"""

import asyncio
import logging
import re
import threading
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from typing import NamedTuple

import httpx
from strands.tools.mcp import MCPAgentTool, MCPClient, ToolFilters

from core.config import AWS_REGION
from core.credentials import ClientCredentials, GatewayCredentials, IdentityCredentials

logger = logging.getLogger(__name__)

# Gateway tool names are ``{target}___{tool}``. ``ToolFilters`` applies
# ``re.Pattern.match``, which anchors at the start, hence the leading ``.*``.
# Both specialists need both tools: the schema tool to learn the labels and
# the read tool to run Cypher.
SPECIALIST_TOOL_FILTERS: ToolFilters = {
    "allowed": [
        re.compile(r".*___get_neo4j_schema$"),
        re.compile(r".*___read_neo4j_cypher$"),
    ]
}

# Refresh a token this many seconds before it expires.
TOKEN_EXPIRY_MARGIN_S = 60
# Identity does not return the expiry, so reuse its token for at most this
# long. A 401 also triggers a refresh.
IDENTITY_TOKEN_MAX_AGE_S = 15 * 60


class AccessToken(NamedTuple):
    value: str
    expires_at: float  # time.monotonic() deadline


TokenFetcher = Callable[[], Awaitable[AccessToken]]


class BearerTokenAuth(httpx.Auth):
    """Send a bearer token on every request and refresh it when it expires.

    A 401 response forces one refresh and one retry. The MCP client runs on
    its own event loop thread, so only the async flow is supported.
    """

    def __init__(self, fetch_token: TokenFetcher) -> None:
        self._fetch_token = fetch_token
        self._token: AccessToken | None = None
        self._lock: asyncio.Lock | None = None

    async def _get_token(self, rejected: str | None = None) -> str:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            token = self._token
            if token is None or token.value == rejected or time.monotonic() >= token.expires_at:
                token = self._token = await self._fetch_token()
            return token.value

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        token = await self._get_token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            logger.info("Gateway returned 401; fetching a new token")
            request.headers["Authorization"] = f"Bearer {await self._get_token(rejected=token)}"
            yield request

    def sync_auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        raise RuntimeError("BearerTokenAuth supports async clients only")


def client_credentials_fetcher(credentials: ClientCredentials) -> TokenFetcher:
    """Fetch a token with the client_credentials grant from ``token_url``."""

    async def fetch() -> AccessToken:
        data = {"grant_type": "client_credentials"}
        if credentials.scope:
            data["scope"] = credentials.scope
        async with httpx.AsyncClient(timeout=30.0) as http:
            response = await http.post(
                credentials.token_url,
                data=data,
                auth=httpx.BasicAuth(credentials.client_id, credentials.client_secret),
            )
        response.raise_for_status()
        body = response.json()
        lifetime = int(body.get("expires_in", 3600))
        logger.info("Fetched a Gateway token (expires in %ss)", lifetime)
        return AccessToken(
            body["access_token"], time.monotonic() + lifetime - TOKEN_EXPIRY_MARGIN_S
        )

    return fetch


# The runtime sets the workload access token per request in a context
# variable. The MCP client calls the token fetcher on its own thread, where
# that variable is unset, so each request copies the latest token here.
_workload_token: str | None = None
_workload_token_lock = threading.Lock()


def remember_workload_token() -> None:
    """Copy the current request's workload access token for the token fetcher.

    Call this at the start of each request. Outside AgentCore Runtime there
    is no token, and this does nothing.
    """
    global _workload_token
    from bedrock_agentcore.runtime import BedrockAgentCoreContext

    if token := BedrockAgentCoreContext.get_workload_access_token():
        with _workload_token_lock:
            _workload_token = token


def identity_fetcher(credentials: IdentityCredentials) -> TokenFetcher:
    """Fetch an M2M token from the AgentCore Identity credential provider."""
    from bedrock_agentcore.services.identity import IdentityClient

    client = IdentityClient(AWS_REGION)

    async def fetch() -> AccessToken:
        with _workload_token_lock:
            workload_token = _workload_token
        if workload_token is None:
            raise RuntimeError("No workload access token yet; the runtime sets one per request")
        token = await client.get_token(
            provider_name=credentials.provider_name,
            agent_identity_token=workload_token,
            scopes=list(credentials.scopes),
            auth_flow="M2M",
        )
        logger.info("Fetched a Gateway token from provider %s", credentials.provider_name)
        return AccessToken(token, time.monotonic() + IDENTITY_TOKEN_MAX_AGE_S)

    return fetch


def build_mcp_client(
    credentials: GatewayCredentials, tool_filters: ToolFilters | None = None
) -> MCPClient:
    """Create the Gateway client with the token source that fits the credentials."""
    match credentials:
        case IdentityCredentials():
            fetch_token = identity_fetcher(credentials)
        case ClientCredentials():
            fetch_token = client_credentials_fetcher(credentials)
    return MCPClient(
        url=credentials.gateway_url,
        auth_provider=BearerTokenAuth(fetch_token),
        tool_filters=tool_filters if tool_filters is not None else SPECIALIST_TOOL_FILTERS,
    )


def list_all_tools(client: MCPClient) -> list[MCPAgentTool]:
    """List the filtered tools across every page the server returns."""
    tools: list[MCPAgentTool] = []
    token: str | None = None
    while True:
        page = client.list_tools_sync(pagination_token=token)
        tools.extend(page)
        token = page.pagination_token
        if token is None:
            return tools
