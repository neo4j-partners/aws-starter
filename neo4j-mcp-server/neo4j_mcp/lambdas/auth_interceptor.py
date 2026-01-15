"""
Authorization Header Interceptor for Neo4j MCP Server

This REQUEST interceptor passes the X-Neo4j-Authorization header through to
the Runtime, enabling per-request Neo4j credentials for the MCP server.

Flow:
1. Client sends: Authorization: Bearer <jwt>, X-Neo4j-Authorization: Basic <creds>
2. Gateway validates JWT
3. This Lambda passes X-Neo4j-Authorization through (unchanged)
4. Gateway adds OAuth token as Authorization header for Runtime auth
5. Runtime receives both headers; MCP server reads X-Neo4j-Authorization for Neo4j

Note: We cannot transform X-Neo4j-Authorization to Authorization because the
Gateway's OAuth credential provider will overwrite Authorization when calling
the Runtime. Instead, the Neo4j MCP server has been updated to check for
X-Neo4j-Authorization header directly.

References:
- AWS Samples: site-reliability-agent-workshop/lab_helpers/lab_03/interceptor-request.py
- Docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors.html
"""

import json
import logging
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Header name for Neo4j credentials (case-insensitive matching)
NEO4J_AUTH_HEADER = "x-neo4j-authorization"

# Interceptor output version (required by AgentCore)
INTERCEPTOR_OUTPUT_VERSION = "1.0"


def handler(event: dict, context: Any) -> dict:
    """
    REQUEST interceptor that passes X-Neo4j-Authorization through to the Runtime.

    This enables the Neo4j MCP server to receive per-request Neo4j credentials
    while AgentCore Gateway uses OAuth for Gateway→Runtime authentication.

    Note: We pass X-Neo4j-Authorization through unchanged (not transforming to
    Authorization) because the Gateway's OAuth credential provider adds its own
    Authorization header for Runtime authentication, which would overwrite ours.
    The Neo4j MCP server has been updated to read from X-Neo4j-Authorization directly.

    Expected input format (from Gateway with passRequestHeaders=true):
    {
        "interceptorInputVersion": "1.0",
        "requestContext": {
            "identity": {...},
            "requestId": "..."
        },
        "mcp": {
            "gatewayRequest": {
                "headers": {
                    "authorization": "Bearer <jwt>",
                    "x-neo4j-authorization": "Basic <creds>",
                    ...
                },
                "body": {...}
            }
        }
    }

    Output format:
    {
        "interceptorOutputVersion": "1.0",
        "mcp": {
            "transformedGatewayRequest": {
                "headers": {
                    "X-Neo4j-Authorization": "Basic <creds>"
                },
                "body": {...}
            }
        }
    }
    """
    # Log full event for debugging
    logger.info(f"FULL EVENT: {json.dumps(event, default=str)}")

    request_id = event.get("requestContext", {}).get("requestId", "unknown")
    logger.info(f"Auth interceptor invoked for request: {request_id}")

    try:
        # Extract request components
        mcp_request = event.get("mcp", {}).get("gatewayRequest", {})
        headers = mcp_request.get("headers", {})
        body = mcp_request.get("body", {})

        # Parse body if it's a string
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse body JSON: {e}")
                return _error_response(
                    body.get("id") if isinstance(body, dict) else None,
                    "Invalid JSON in request body"
                )

        # Find X-Neo4j-Authorization header (case-insensitive)
        neo4j_auth = _get_header_case_insensitive(headers, NEO4J_AUTH_HEADER)

        if not neo4j_auth:
            logger.warning("No X-Neo4j-Authorization header found")
            return _error_response(
                body.get("id"),
                "Missing X-Neo4j-Authorization header. Include Neo4j credentials "
                "as 'X-Neo4j-Authorization: Basic <base64(username:password)>'"
            )

        # Validate Basic auth format
        if not neo4j_auth.lower().startswith("basic "):
            logger.warning(f"Invalid auth format: expected 'Basic ...', got '{neo4j_auth[:20]}...'")
            return _error_response(
                body.get("id"),
                "X-Neo4j-Authorization must use Basic authentication format: "
                "'Basic <base64(username:password)>'"
            )

        # Pass X-Neo4j-Authorization through to the Runtime
        # The Neo4j MCP server reads this header directly for per-request credentials
        # (We cannot use Authorization because the Gateway's OAuth provider overwrites it)
        transformed_headers = {
            "X-Neo4j-Authorization": neo4j_auth,
            "Content-Type": "application/json",
        }

        logger.info(f"Passing X-Neo4j-Authorization through for request {request_id}")

        return {
            "interceptorOutputVersion": INTERCEPTOR_OUTPUT_VERSION,
            "mcp": {
                "transformedGatewayRequest": {
                    "headers": transformed_headers,
                    "body": body,
                }
            }
        }

    except Exception as e:
        logger.error(f"Unexpected error in auth interceptor: {e}", exc_info=True)
        return _error_response(
            None,
            f"Authorization passthrough failed: {str(e)}"
        )


def _get_header_case_insensitive(headers: dict, header_name: str) -> str | None:
    """
    Get header value with case-insensitive matching.

    HTTP header names are case-insensitive per RFC 7230.

    Args:
        headers: Dictionary of headers
        header_name: Header name to find (lowercase)

    Returns:
        Header value if found, None otherwise
    """
    header_name_lower = header_name.lower()
    for key, value in headers.items():
        if key.lower() == header_name_lower:
            return value
    return None


def _error_response(rpc_id: Any, message: str) -> dict:
    """
    Build a valid MCP/JSON-RPC error response for denied requests.

    This returns a transformedGatewayResponse which short-circuits the request
    and returns directly to the client without hitting the target.

    Args:
        rpc_id: JSON-RPC request ID (can be None)
        message: Error message to return

    Returns:
        Interceptor response with error body
    """
    logger.info(f"Returning error response: {message}")

    error_body = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {
            "code": -32600,  # Invalid Request
            "message": message,
        }
    }

    return {
        "interceptorOutputVersion": INTERCEPTOR_OUTPUT_VERSION,
        "mcp": {
            "transformedGatewayResponse": {
                "statusCode": 401,
                "headers": {
                    "Content-Type": "application/json",
                    "WWW-Authenticate": 'Basic realm="Neo4j MCP Server"',
                },
                "body": error_body,
            }
        }
    }
