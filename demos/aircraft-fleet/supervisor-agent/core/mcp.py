"""Gateway MCP client.

All Gateway auth lives in :func:`build_mcp_client`, so the OAuth setup can be
checked in one place.
"""

import re

from strands.tools.mcp import MCPClient, ToolFilters

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


def build_mcp_client(credentials: dict, tool_filters: ToolFilters | None = None) -> MCPClient:
    """Create the Gateway client with the OAuth client_credentials flow.

    The MCP SDK finds the Cognito token endpoint through OAuth discovery from
    the Gateway URL, then fetches and refreshes the token. ``scopes`` is
    advisory: a scope the server advertises wins over this one.
    """
    auth = {
        "client_id": credentials["client_id"],
        "client_secret": credentials["client_secret"],
    }
    if scope := credentials.get("scope"):
        auth["scopes"] = scope.split()
    return MCPClient(
        url=credentials["gateway_url"],
        auth=auth,
        tool_filters=tool_filters if tool_filters is not None else SPECIALIST_TOOL_FILTERS,
    )
