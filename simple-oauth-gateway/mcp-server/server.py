"""
Auth-Aware MCP Server for OAuth2 Demo with RBAC

This MCP server demonstrates role-based access control (RBAC) using
headers injected by the Gateway interceptor:

- X-User-Id: The user's Cognito sub claim (or m2m:client_id for M2M tokens)
- X-User-Groups: Comma-separated list of user's Cognito groups
- X-Client-Id: The OAuth client ID

Tools:
- echo: Public tool, available to all authenticated users
- get_user_info: Returns caller identity from injected headers
- admin_action: Admin-only tool (enforced by Gateway interceptor)
- server_info: Server information and available tools

Note: The Gateway interceptor enforces RBAC by blocking unauthorized
tool calls before they reach this server. The admin_action tool includes
a secondary check as defense-in-depth.
"""

import logging
from contextvars import ContextVar

from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastMCP server for AgentCore Runtime
# host="0.0.0.0" - Listen on all interfaces (required by AgentCore)
# stateless_http=True - Enable stateless mode for enterprise security
mcp = FastMCP(
    "Simple OAuth Demo Server",
    host="0.0.0.0",
    stateless_http=True
)

# Context variable for storing request headers (set by middleware if available)
_request_headers: ContextVar[dict] = ContextVar("request_headers", default={})


def _get_user_context() -> dict:
    """
    Extract user context from injected headers.

    The Gateway interceptor injects these headers after extracting
    claims from the JWT:
    - X-User-Id: User identifier (sub claim or m2m:client_id)
    - X-User-Groups: Comma-separated group list
    - X-Client-Id: OAuth client ID

    Returns default values if headers are not available (e.g., direct
    access without going through Gateway).
    """
    headers = _request_headers.get()

    user_id = headers.get("x-user-id", "unknown")
    groups_str = headers.get("x-user-groups", "")
    client_id = headers.get("x-client-id", "unknown")

    # Parse groups from comma-separated string
    groups = [g.strip() for g in groups_str.split(",") if g.strip()]

    return {
        "user_id": user_id,
        "groups": groups,
        "client_id": client_id,
        "authenticated": user_id != "unknown"
    }


@mcp.tool()
def echo(message: str) -> str:
    """
    Echo back the provided message.

    This is a public tool available to any authenticated user,
    regardless of group membership. It demonstrates basic MCP
    tool functionality.

    Args:
        message: The message to echo back

    Returns:
        The echoed message with prefix
    """
    ctx = _get_user_context()
    logger.info(f"echo called by user={ctx['user_id']}, groups={ctx['groups']}")
    return f"Echo: {message}"


@mcp.tool()
def get_user_info() -> dict:
    """
    Get information about the current user from injected headers.

    The Gateway interceptor extracts identity claims from the JWT
    and injects them as HTTP headers. This tool reads those headers
    to show the caller their own identity.

    Returns:
        dict containing:
        - user_id: Cognito sub claim or m2m:client_id
        - groups: List of Cognito group memberships
        - client_id: OAuth client ID used for authentication
        - authenticated: Whether identity was successfully extracted
        - auth_type: "user" (with groups) or "m2m" (machine-to-machine)
    """
    ctx = _get_user_context()

    # Determine authentication type
    if ctx["user_id"].startswith("m2m:"):
        auth_type = "m2m"
    elif ctx["groups"]:
        auth_type = "user"
    else:
        auth_type = "unknown"

    logger.info(f"get_user_info called: {ctx}")

    return {
        "user_id": ctx["user_id"],
        "groups": ctx["groups"],
        "client_id": ctx["client_id"],
        "authenticated": ctx["authenticated"],
        "auth_type": auth_type,
        "message": "Identity extracted from Gateway interceptor headers"
    }


@mcp.tool()
def admin_action(action: str) -> dict:
    """
    Perform an administrative action.

    This tool requires the caller to be a member of the "admin" group.
    Access control is enforced at two levels:

    1. Gateway Interceptor (primary): Blocks non-admin users before
       the request reaches this server
    2. This tool (defense-in-depth): Secondary check in case headers
       are available

    Args:
        action: Description of the admin action to perform

    Returns:
        dict with action result or error if unauthorized
    """
    ctx = _get_user_context()
    logger.info(f"admin_action called by user={ctx['user_id']}, groups={ctx['groups']}, action={action}")

    # Defense-in-depth: verify admin group membership
    # The Gateway interceptor should have already blocked non-admins
    if ctx["authenticated"] and "admin" not in ctx["groups"]:
        logger.warning(f"admin_action: user {ctx['user_id']} not in admin group (should have been blocked by interceptor)")
        return {
            "success": False,
            "error": "Unauthorized: admin group membership required",
            "user": ctx["user_id"],
            "groups": ctx["groups"]
        }

    return {
        "success": True,
        "action": action,
        "performed_by": ctx["user_id"],
        "user_groups": ctx["groups"],
        "message": f"Admin action '{action}' completed successfully"
    }


@mcp.tool()
def server_info() -> dict:
    """
    Get information about this MCP server and its capabilities.

    Returns server metadata including available tools and
    RBAC configuration.

    Returns:
        dict with server information
    """
    return {
        "name": "Simple OAuth Demo MCP Server",
        "version": "2.0.0",
        "purpose": "Demonstrate OAuth2 authentication with RBAC",
        "tools": {
            "echo": "Public - available to all authenticated users",
            "get_user_info": "Public - returns caller identity",
            "admin_action": "Protected - requires 'admin' group",
            "server_info": "Public - this information"
        },
        "features": [
            "OAuth2 M2M (client_credentials) authentication",
            "OAuth2 User (password) authentication with groups",
            "Group-based access control (RBAC)",
            "Gateway interceptor for JWT claim extraction",
            "Header-based identity propagation"
        ],
        "groups": {
            "users": "Basic access to public tools",
            "admin": "Full access including admin_action tool"
        }
    }


if __name__ == "__main__":
    logger.info("Starting Simple OAuth Demo MCP Server with RBAC")
    mcp.run(transport="streamable-http")
