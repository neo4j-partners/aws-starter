"""Gateway MCP client and its auth.

All Gateway auth lives in this module. :func:`build_gateway_auth` picks one
of two token sources and hands it to :class:`BearerTokenAuth`:

- Local (:class:`ClientCredentials`): the OAuth client_credentials grant,
  posted straight to the ``token_url`` from the credentials file. There is no
  OAuth discovery, so the client secret only ever goes to that URL. The MCP
  server cannot redirect it to another authorization server.
- Cloud (:class:`IdentityCredentials`): an M2M token from AgentCore Identity.
  The runtime holds no secret. Each request fetches the token on the request
  path, where the workload access token is valid. See :class:`GatewayAuth`.
"""

import asyncio
import base64
import json
import logging
import re
import threading
import time
import weakref
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from dataclasses import dataclass
from typing import NamedTuple

import httpx
from strands.tools.mcp import MCPClient, ToolFilters

from fleet_supervisor.core.config import AWS_REGION
from fleet_supervisor.core.credentials import (
    ClientCredentials,
    GatewayCredentials,
    IdentityCredentials,
)

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
# A Gateway token whose ``exp`` claim cannot be read is reused for at most
# this long. A 401 also triggers a refresh.
UNREADABLE_EXPIRY_MAX_AGE_S = 5 * 60

# The Identity flow for the Gateway token. The token belongs to the agent's
# OAuth client, not to a user, so every request can share it. The process-wide
# token cache in this module is valid only for M2M. A user-federated flow
# would need one token per user.
M2M_AUTH_FLOW = "M2M"


class AccessToken(NamedTuple):
    value: str
    expires_at: float  # time.monotonic() deadline


# Called with force=True after the Gateway rejects a token, so the source
# must not hand back the same cached token.
TokenFetcher = Callable[[bool], Awaitable[AccessToken]]


def jwt_deadline(token: str) -> float:
    """Return when to refresh a JWT, as a ``time.monotonic()`` deadline.

    Reads the ``exp`` claim without checking the signature. The Gateway checks
    the signature. This only decides when to fetch a new token.
    """
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        expires_in = float(claims["exp"]) - time.time()
    except (IndexError, KeyError, TypeError, ValueError):
        logger.warning(
            "The Gateway token has no readable exp claim; refreshing it within %ss",
            UNREADABLE_EXPIRY_MAX_AGE_S,
        )
        return time.monotonic() + UNREADABLE_EXPIRY_MAX_AGE_S
    return time.monotonic() + expires_in - TOKEN_EXPIRY_MARGIN_S


class BearerTokenAuth(httpx.Auth):
    """Send a bearer token on every request and refresh it when it expires.

    A 401 response forces one refresh and one retry. The MCP client runs on
    its own event loop thread, so only the async flow is supported.
    :meth:`set_token` lets the request path supply a token from another thread.
    """

    def __init__(self, fetch_token: TokenFetcher) -> None:
        self._fetch_token = fetch_token
        self._token: AccessToken | None = None
        # Guards _token: set_token runs on a request thread, the auth flow on
        # the MCP client's thread.
        self._token_lock = threading.Lock()
        # Serializes fetches on each MCP client's event loop. The auth outlives
        # client rebuilds, and each client runs its own loop, so there is one
        # lock per loop. During a rebuild the old and new loops both run, and
        # each keeps its own lock. A loop's entry goes away with the loop.
        self._fetch_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
            weakref.WeakKeyDictionary()
        )
        # Guards _fetch_locks, which the client loops' threads share.
        self._fetch_locks_guard = threading.Lock()

    def set_token(self, token: AccessToken) -> None:
        """Use ``token`` from now on."""
        with self._token_lock:
            self._token = token

    def needs_token(self) -> bool:
        """Report whether there is no token or the current one has expired."""
        with self._token_lock:
            token = self._token
        return token is None or time.monotonic() >= token.expires_at

    def _lock_for_this_loop(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        with self._fetch_locks_guard:
            lock = self._fetch_locks.get(loop)
            if lock is None:
                lock = self._fetch_locks[loop] = asyncio.Lock()
            return lock

    async def _get_token(self, rejected: str | None = None) -> str:
        async with self._lock_for_this_loop():
            with self._token_lock:
                token = self._token
            if token is not None and token.value == rejected:
                token = await self._fetch_token(True)
            elif token is None or time.monotonic() >= token.expires_at:
                token = await self._fetch_token(False)
            else:
                return token.value
            self.set_token(token)
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
    """Fetch a token with the client_credentials grant from ``token_url``.

    Every call is a new grant, so ``force`` needs no special handling.
    """

    async def fetch(force: bool) -> AccessToken:
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


class IdentityTokens:
    """M2M Gateway tokens from an AgentCore Identity credential provider.

    Identity needs the request's workload access token, which the runtime sets
    in a context variable for each request. The MCP client cannot read it
    reliably: ``MCPClient.start()`` copies the context into its background
    thread, so that thread sees the first request's token, frozen. Each
    request therefore records its own workload token here with
    :meth:`remember_workload_token`.
    """

    def __init__(self, credentials: IdentityCredentials) -> None:
        from bedrock_agentcore.services.identity import IdentityClient

        self._credentials = credentials
        self._client = IdentityClient(AWS_REGION)
        self._workload_token: str | None = None
        self._lock = threading.Lock()

    def remember_workload_token(self) -> str | None:
        """Record the current request's workload access token and return it.

        Call this on the request path. With no token, None is stored, so a
        later fetch never reuses an earlier request's token.
        """
        from bedrock_agentcore.runtime import BedrockAgentCoreContext

        token = BedrockAgentCoreContext.get_workload_access_token()
        if token is None:
            logger.warning("The request has no workload access token")
        with self._lock:
            self._workload_token = token
        return token

    def _get_token_blocking(self, workload_token: str, force: bool) -> AccessToken:
        # get_token is async but calls blocking boto3 inside, so it runs on
        # its own loop in a worker thread. The M2M path awaits nothing else.
        value = asyncio.run(
            self._client.get_token(
                provider_name=self._credentials.provider_name,
                agent_identity_token=workload_token,
                scopes=list(self._credentials.scopes),
                auth_flow=M2M_AUTH_FLOW,
                force_authentication=force,
            )
        )
        logger.info(
            "Fetched a Gateway token from provider %s (forced=%s)",
            self._credentials.provider_name,
            force,
        )
        return AccessToken(value, jwt_deadline(value))

    async def fetch(self, force: bool) -> AccessToken:
        """Fetch a token with the latest recorded workload token.

        ``force`` asks the token vault for a new token instead of its cached one.
        """
        with self._lock:
            workload_token = self._workload_token
        if workload_token is None:
            raise RuntimeError("No workload access token for the Gateway token request")
        return await asyncio.to_thread(self._get_token_blocking, workload_token, force)


@dataclass(frozen=True)
class GatewayAuth:
    """The Gateway endpoint and its token source, built once per process."""

    gateway_url: str
    auth: BearerTokenAuth
    identity: IdentityTokens | None = None

    async def prepare_request(self) -> None:
        """Get the Gateway token ready for one request. Call on the request path.

        On the cloud path this records the request's workload token and, when
        the current Gateway token is missing or expired, fetches one and hands
        it to the auth. The MCP client then fetches only after a 401, or when
        a token expires during a long request. The local path does nothing:
        its fetch needs no per-request input.
        """
        if self.identity is None:
            return
        if self.identity.remember_workload_token() is None:
            return
        if self.auth.needs_token():
            self.auth.set_token(await self.identity.fetch(False))


def build_gateway_auth(credentials: GatewayCredentials) -> GatewayAuth:
    """Pick the token source that fits the credentials."""
    match credentials:
        case IdentityCredentials():
            identity = IdentityTokens(credentials)
            return GatewayAuth(credentials.gateway_url, BearerTokenAuth(identity.fetch), identity)
        case ClientCredentials():
            fetch = client_credentials_fetcher(credentials)
            return GatewayAuth(credentials.gateway_url, BearerTokenAuth(fetch))


def build_mcp_client(gateway: GatewayAuth, tool_filters: ToolFilters | None = None) -> MCPClient:
    """Create the Gateway MCP client. It shares the process-wide auth."""
    return MCPClient(
        url=gateway.gateway_url,
        auth_provider=gateway.auth,
        tool_filters=tool_filters if tool_filters is not None else SPECIALIST_TOOL_FILTERS,
    )
