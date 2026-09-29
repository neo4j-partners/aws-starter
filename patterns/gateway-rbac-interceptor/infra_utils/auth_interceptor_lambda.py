"""
Auth Interceptor Lambda for AgentCore Gateway.

This REQUEST interceptor:
1. Extracts cognito:groups and sub claims from JWT
2. Injects X-User-Id, X-User-Groups, X-Client-Id headers
3. Enforces group-based access control for admin tools

Based on: amazon-bedrock-agentcore-samples site-reliability-agent-workshop
"""

from __future__ import annotations

import base64
import json
from typing import Any

# Tools that require 'admin' group membership
ADMIN_TOOLS = frozenset({"admin_action"})

# Interceptor protocol version
INTERCEPTOR_VERSION = "1.0"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    REQUEST interceptor that extracts JWT claims and enforces RBAC.

    The Gateway validates JWT signature via OIDC discovery before invoking
    this Lambda. We only decode the payload to extract claims.
    """
    try:
        # Log the incoming event for debugging
        print(f"[Interceptor] Event: {json.dumps(event, default=str)}")

        # Extract request from Gateway event structure
        mcp_data = event.get("mcp", {})
        gateway_request = mcp_data.get("gatewayRequest", {})
        headers = gateway_request.get("headers", {})
        body = gateway_request.get("body", {})

        # Parse body if string
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError as e:
                print(f"[Interceptor] Invalid JSON body: {e}")
                return _deny_request(None, "Invalid JSON in request body")

        # Get MCP method and request ID
        method = body.get("method", "")
        rpc_id = body.get("id")

        # Extract identity from JWT
        auth_header = headers.get("authorization") or headers.get("Authorization") or ""
        user_id, groups, client_id = _extract_identity(auth_header)

        print(f"[Interceptor] Method: {method}, User: {user_id}, Groups: {groups}")

        # Check RBAC for tools/call
        if method == "tools/call":
            tool_name = body.get("params", {}).get("name", "")
            # Remove target prefix (e.g., "mcp-server-target___admin_action")
            base_tool_name = tool_name.split("___")[-1]

            if base_tool_name in ADMIN_TOOLS and "admin" not in groups:
                print(f"[Interceptor] DENIED: {user_id} -> {base_tool_name}")
                return _deny_request(
                    rpc_id,
                    f"Access denied: Tool '{base_tool_name}' requires 'admin' group. "
                    f"Your groups: {groups or 'none'}"
                )

        # Allow request with identity headers
        return _allow_request(auth_header, body, user_id, groups, client_id)

    except Exception as e:
        print(f"[Interceptor] Error: {e}")
        return _deny_request(None, f"Authorization error: {e}")


def _extract_identity(auth_header: str) -> tuple[str, list[str], str]:
    """Extract user identity from JWT Authorization header."""
    if not auth_header:
        return "anonymous", [], "unknown"

    claims = _decode_jwt(auth_header)
    if not claims:
        return "anonymous", [], "unknown"

    groups = claims.get("cognito:groups", [])
    client_id = claims.get("client_id", "unknown")
    user_id = claims.get("sub", client_id)

    # M2M tokens have no groups - mark as machine identity
    if not groups and client_id != "unknown":
        user_id = f"m2m:{client_id}"

    return user_id, groups, client_id


def _decode_jwt(auth_header: str) -> dict[str, Any] | None:
    """Decode JWT payload without verification (Gateway already validated)."""
    try:
        # Remove 'Bearer ' prefix
        token = auth_header.replace("Bearer ", "").strip()

        # JWT: header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return None

        # Decode payload with padding
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception as e:
        print(f"[Interceptor] JWT decode error: {e}")
        return None


def _allow_request(
    auth_header: str,
    body: dict[str, Any],
    user_id: str,
    groups: list[str],
    client_id: str,
) -> dict[str, Any]:
    """Build response that allows the request with identity headers."""
    return {
        "interceptorOutputVersion": INTERCEPTOR_VERSION,
        "mcp": {
            "transformedGatewayRequest": {
                "headers": {
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                    "X-User-Id": user_id,
                    "X-User-Groups": ",".join(groups),
                    "X-Client-Id": client_id,
                },
                "body": body,
            }
        },
    }


def _deny_request(rpc_id: Any, message: str) -> dict[str, Any]:
    """Build response that denies the request with an error."""
    print(f"[Interceptor] Denying: {message}")
    return {
        "interceptorOutputVersion": INTERCEPTOR_VERSION,
        "mcp": {
            "transformedGatewayResponse": {
                "statusCode": 200,  # MCP errors use 200 with error in body
                "headers": {"Content-Type": "application/json"},
                "body": {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": message}],
                    },
                },
            }
        },
    }
