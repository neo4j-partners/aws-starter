#!/bin/bash
# ==============================================================================
# LOCAL.SH - Neo4j MCP Server Local Development Script
# ==============================================================================
#
# PURPOSE:
#   Manages a local Neo4j MCP server running in Docker for development and
#   testing. This is a thin wrapper that sets up the Python environment and
#   delegates to client/mcp_local_client.py for all functionality.
#
# TARGET:
#   Local Docker container at http://localhost:8000/mcp
#
# AUTHENTICATION:
#   None required - server uses NEO4J_* credentials from environment variables
#
# COMMANDS:
#   start              Start the local MCP server (Docker container)
#   stop               Stop the local MCP server
#   test               Run the full MCP client test suite
#   tools              List available MCP tools
#   call <tool> <json> Call a specific tool with JSON arguments
#
# EXAMPLES:
#   ./local.sh start
#   ./local.sh test
#   ./local.sh tools
#   ./local.sh call get-schema '{}'
#   ./local.sh call read-cypher '{"query": "MATCH (n) RETURN count(n)"}'
#
# ENVIRONMENT:
#   MCP_SERVER_URL - Override server URL (default: http://localhost:8000/mcp)
#   NEO4J_URI      - Neo4j connection URI (from .env)
#   NEO4J_USERNAME - Neo4j username (from .env)
#   NEO4J_PASSWORD - Neo4j password (from .env)
#
# SEE ALSO:
#   ./cloud.sh      - Cloud AgentCore testing (Cognito auth)
#   ./cloud-http.sh - Raw HTTP debugging for cloud server
#
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Install Python dependencies via uv
setup_deps() {
    uv sync --quiet --directory "$SCRIPT_DIR"
}

# Map empty command to 'help'
command="${1:-help}"
shift 2>/dev/null || true

# Help still needs deps for imports
if [[ "$command" == "help" || "$command" == "--help" || "$command" == "-h" ]]; then
    setup_deps
    uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/client/mcp_local_client.py" help
    exit 0
fi

# Install deps and run
setup_deps
uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/client/mcp_local_client.py" "$command" "$@"
