#!/bin/bash
# Neo4j MCP Agent
#
# A ReAct agent that connects to the Neo4j MCP server via AgentCore Gateway
# and answers natural language questions using AWS Bedrock Claude.
#
# Usage:
#   ./agent.sh "What is the database schema?"
#   ./agent.sh "How many Aircraft are in the database?"
#
# Prerequisites:
#   - .mcp-credentials.json (copy from simple-neo4j-mcp-server deployment)
#   - AWS credentials configured (for Bedrock access)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check for credentials file
if [ ! -f "$SCRIPT_DIR/.mcp-credentials.json" ]; then
    echo "ERROR: Credentials file not found: .mcp-credentials.json"
    echo ""
    echo "Copy credentials from your simple-neo4j-mcp-server deployment:"
    echo "  cp ../simple-neo4j-mcp-server/.mcp-credentials.json ."
    echo ""
    echo "Required fields: gateway_url, token_url, client_id, client_secret, scope"
    exit 1
fi

# Show help
if [ "$1" = "help" ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Neo4j MCP Agent"
    echo ""
    echo "A ReAct agent that queries Neo4j via AgentCore Gateway."
    echo "Tokens are automatically refreshed when expired."
    echo ""
    echo "Usage:"
    echo "  ./agent.sh                  Run demo queries"
    echo "  ./agent.sh \"<question>\"     Ask a specific question"
    echo ""
    echo "Examples:"
    echo "  ./agent.sh \"What is the database schema?\""
    echo "  ./agent.sh \"How many Aircraft are in the database?\""
    echo "  ./agent.sh \"What types of relationships exist?\""
    echo "  ./agent.sh \"Find all airports in California\""
    echo ""
    echo "Prerequisites:"
    echo "  1. Deploy simple-neo4j-mcp-server with AgentCore Gateway"
    echo "  2. Copy .mcp-credentials.json from that deployment"
    echo "  3. AWS credentials configured (for Bedrock access)"
    echo ""
    echo "Commands:"
    echo "  ./agent.sh setup    Install dependencies"
    echo "  ./agent.sh help     Show this help message"
    exit 0
fi

# Setup command - install dependencies
if [ "$1" = "setup" ]; then
    echo "Installing dependencies..."
    cd "$SCRIPT_DIR"
    uv sync
    echo ""
    echo "Setup complete!"
    exit 0
fi

# Ensure dependencies are installed
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "Installing dependencies (first run)..."
    cd "$SCRIPT_DIR"
    uv sync
    echo ""
fi

# Run the agent
cd "$SCRIPT_DIR"
uv run python agent.py "$@"
