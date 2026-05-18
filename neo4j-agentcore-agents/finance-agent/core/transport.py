"""MCP transport factory for the Neo4j MCP server via AgentCore Gateway.

``create_transport`` is passed to ``MCPClient`` and invoked on every
``with mcp_client:`` entry. Resolving credentials here (not at module load)
is what keeps the Bearer token fresh: ``get_active_credentials`` refreshes
the OAuth2 token in memory whenever it is missing or close to expiring, so a
long-running runtime never serves requests with an expired token.
"""

from mcp.client.streamable_http import streamablehttp_client

from core.credentials import get_active_credentials


def create_transport():
    """Build a streamable-HTTP transport with a freshly resolved Bearer token."""
    credentials = get_active_credentials()
    return streamablehttp_client(
        credentials["gateway_url"],
        headers={"Authorization": f"Bearer {credentials['access_token']}"},
    )
