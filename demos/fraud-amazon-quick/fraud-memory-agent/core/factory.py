"""Strands-specific factories shared by the runtime and the local clients.

The Bedrock model and the MCP client are constructed identically wherever the
agent runs (deployed runtime, local CLI, demo). Centralizing them here keeps
the hyperparameters and the Gateway wiring in one place; importing this
module is what pulls the Strands dependency, so the rest of ``core`` stays
framework-agnostic.
"""

import asyncio
from collections.abc import AsyncGenerator

import httpx
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient

from core.config import AWS_REGION, MODEL_ID
from core.credentials import get_active_credentials, load_credentials


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


def build_model() -> BedrockModel:
    """The shared Bedrock model — same hyperparameters everywhere."""
    return BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.0,
        max_tokens=4096,
        streaming=True,
    )


def build_mcp_client() -> MCPClient:
    """Gateway MCP client. Strands builds the streamable HTTP transport.

    Strands creates the HTTP client with the MCP SDK's default timeouts:
    30 seconds, and 300 seconds to read a response stream.
    """
    return MCPClient(url=load_credentials()["gateway_url"], auth_provider=GatewayTokenAuth())
