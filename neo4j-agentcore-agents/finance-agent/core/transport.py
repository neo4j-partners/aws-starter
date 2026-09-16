"""MCP transport factory for the Neo4j MCP server via AgentCore Gateway.

``create_transport`` is passed to ``MCPClient`` and invoked on every
``with mcp_client:`` entry. Resolving credentials here (not at module load)
is what keeps the Bearer token fresh: ``get_active_credentials`` refreshes
the OAuth2 token in memory whenever it is missing or close to expiring, so a
long-running runtime never serves requests with an expired token.
"""

from contextlib import asynccontextmanager

try:
    # MCP 2.x uses its bundled HTTP client, which supports the SSE methods the
    # transport requires. MCP 1.x uses the public httpx package instead.
    import httpx2 as httpx
except ImportError:  # pragma: no cover - exercised in the MCP 1.x local environment
    import httpx

from mcp.client.streamable_http import streamable_http_client

from core.credentials import get_active_credentials


@asynccontextmanager
async def _authenticated_transport(url: str, access_token: str):
    """Yield an MCP transport with an HTTP client that is closed on exit."""
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {access_token}"}) as http_client:
        async with streamable_http_client(url, http_client=http_client) as transport:
            yield transport


def create_transport():
    """Build a streamable-HTTP transport with a freshly resolved Bearer token."""
    credentials = get_active_credentials()
    return _authenticated_transport(credentials["gateway_url"], credentials["access_token"])
