"""Strands-specific factories shared by the runtime and the local clients.

The Bedrock model and the MCP client are constructed identically wherever the
agent runs (deployed runtime, local CLI, demo). Centralizing them here keeps
the hyperparameters and the Gateway wiring in one place; importing this
module is what pulls the Strands dependency, so the rest of ``core`` stays
framework-agnostic.
"""

import asyncio
import base64
import functools
import json
import logging
import threading
import time
from collections.abc import AsyncGenerator
from typing import NamedTuple

import httpx
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient

from core.config import AWS_REGION, MODEL_ID
from core.credentials import (
    IdentityCredentials,
    get_active_credentials,
    identity_credentials,
    load_credentials,
)

logger = logging.getLogger(__name__)

# Refresh an Identity Gateway token this many seconds before it expires.
TOKEN_EXPIRY_MARGIN_S = 60
# A Gateway token whose ``exp`` claim cannot be read is reused for at most
# this long. A 401 also triggers a refresh.
UNREADABLE_EXPIRY_MAX_AGE_S = 5 * 60
# The Gateway token belongs to the agent's OAuth client, not to a user, so
# every request can share it. The process-wide cache below is valid only for
# M2M. A user-federated flow would need one token per user.
M2M_AUTH_FLOW = "M2M"


class GatewayTokenAuth(httpx.Auth):
    """Send the Gateway OAuth2 token on every MCP request.

    ``get_active_credentials`` refreshes the token in memory when it is
    missing or close to expiring, so a long-running runtime never sends an
    expired token. The refresh is a blocking HTTP call, so it runs in a
    worker thread.
    """

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        credentials = await asyncio.to_thread(get_active_credentials)
        request.headers["Authorization"] = f"Bearer {credentials['access_token']}"
        yield request


class AccessToken(NamedTuple):
    value: str
    expires_at: float  # time.monotonic() deadline


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


class IdentityGatewayTokens:
    """The process-wide M2M Gateway token from an AgentCore Identity provider.

    Each fetch needs a workload access token, which is valid only for the
    request that carries it. So the caller passes its own request's token.
    """

    def __init__(self, credentials: IdentityCredentials) -> None:
        from bedrock_agentcore.services.identity import IdentityClient

        self._credentials = credentials
        self._client = IdentityClient(AWS_REGION)
        self._token: AccessToken | None = None
        # Serializes fetches, so concurrent requests share one new token.
        self._lock = threading.Lock()

    def get(self, workload_token: str, rejected: str | None = None) -> str:
        """Return a current Gateway token. Blocks while it fetches one.

        ``rejected`` is a token the Gateway answered with 401. The token vault
        is then asked for a new token instead of its cached one, unless
        another request has already replaced the rejected token.
        """
        with self._lock:
            cached = self._token
            if (
                cached is not None
                and cached.value != rejected
                and time.monotonic() < cached.expires_at
            ):
                return cached.value
            # get_token is async but calls blocking boto3 inside, so it runs
            # on its own loop in this worker thread.
            value = asyncio.run(
                self._client.get_token(
                    provider_name=self._credentials.provider_name,
                    agent_identity_token=workload_token,
                    scopes=list(self._credentials.scopes),
                    auth_flow=M2M_AUTH_FLOW,
                    force_authentication=rejected is not None,
                )
            )
            self._token = AccessToken(value, jwt_deadline(value))
            logger.info(
                "Fetched a Gateway token from provider %s (forced=%s)",
                self._credentials.provider_name,
                rejected is not None,
            )
            return value


@functools.cache
def identity_gateway_tokens(credentials: IdentityCredentials) -> IdentityGatewayTokens:
    """The one token source for the process."""
    return IdentityGatewayTokens(credentials)


class IdentityGatewayAuth(httpx.Auth):
    """Send the Identity Gateway token on every MCP request of one agent request.

    A 401 response forces one refresh and one retry.
    """

    def __init__(self, tokens: IdentityGatewayTokens, workload_token: str) -> None:
        self._tokens = tokens
        self._workload_token = workload_token

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        token = await asyncio.to_thread(self._tokens.get, self._workload_token)
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            logger.info("Gateway returned 401; fetching a new token")
            token = await asyncio.to_thread(self._tokens.get, self._workload_token, token)
            request.headers["Authorization"] = f"Bearer {token}"
            yield request


def workload_access_token() -> str:
    """Return the current request's workload access token.

    The Runtime sets it in a context variable for each request. Call this on
    the request path. It never falls back to the SDK's local workload
    identity, which writes ``.agentcore.json``.
    """
    from bedrock_agentcore.runtime import BedrockAgentCoreContext

    token = BedrockAgentCoreContext.get_workload_access_token()
    if not token:
        raise RuntimeError(
            "The request has no workload access token for AgentCore Identity. "
            "Invoke with a runtime user ID (runtimeUserId, or agentcore invoke --user-id)."
        )
    return token


def build_model() -> BedrockModel:
    """The shared Bedrock model — same hyperparameters everywhere."""
    return BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        max_tokens=4096,
        streaming=True,
    )


def build_mcp_client() -> MCPClient:
    """Gateway MCP client. Strands builds the streamable HTTP transport.

    On the Runtime the token comes from AgentCore Identity, so call this on
    the request path, where the workload access token is set. Locally it
    comes from the credentials file.

    Strands creates the HTTP client with the MCP SDK's default timeouts:
    30 seconds, and 300 seconds to read a response stream.
    """
    if (identity := identity_credentials()) is not None:
        auth = IdentityGatewayAuth(identity_gateway_tokens(identity), workload_access_token())
        return MCPClient(url=identity.gateway_url, auth_provider=auth)
    return MCPClient(url=load_credentials()["gateway_url"], auth_provider=GatewayTokenAuth())
