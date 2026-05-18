#!/bin/bash
# Finance Agent - AgentCore deployment helper
#
# This script does ONE thing: deploy/manage the agent on AgentCore Runtime.
# It is a thin wrapper over the `agentcore` CLI; the only reason it exists
# (rather than documenting raw `agentcore` commands) is that `deploy` sources
# NEO4J_URI/NEO4J_PASSWORD from .env and injects them into the runtime env
# for Context Graph memory.
#
# It does NOT run the agent locally and it does NOT run the clients. The
# server runs in the foreground of its own terminal; the clients are uv
# console scripts. See the README "Quick Start: Local". In short:
#
#   Terminal 1:  uv run finance-server          # Ctrl+C to stop
#   Terminal 2:  uv run finance-cli "question"
#                uv run finance-demo
#                uv run finance-invoke memory-demo
#
# Usage:
#   ./agent.sh configure          Configure for AWS deployment
#   ./agent.sh deploy             Deploy to AgentCore Runtime
#   ./agent.sh status             Check deployment status
#   ./agent.sh invoke-cloud "prompt"  Invoke deployed agent
#   ./agent.sh destroy            Remove from AgentCore
#
# Prerequisites:
#   - .mcp-credentials.json at the agent root (from Neo4j MCP deployment)
#   - AWS credentials configured (for Bedrock access)

set -e

# This script and the uv project (pyproject.toml, uv.lock, .venv,
# .mcp-credentials.json) live at the agent root; the runtime entrypoint
# lives in server/ and the client tooling in client/.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRYPOINT="server/runtime_app.py"
AGENT_NAME="finance_agent"
cd "$ROOT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Neo4j credentials for Context Graph memory. The memory tools open a direct
# Neo4j connection (not via the MCP Gateway), so the runtime needs NEO4J_URI
# and NEO4J_PASSWORD. Source them from finance-agent/.env if present, else
# fall back to the Neo4j MCP server's .env (same database as the finance
# graph). Read the first matching value only; split on the first '=' so
# passwords containing '=' survive.
read_env_var() {
    # $1=file  $2=key. Takes the first match, strips CR and one layer of
    # surrounding single/double quotes (common .env style).
    [ -f "$1" ] || return 1
    sed -n "s/^[[:space:]]*$2=//p" "$1" | head -n1 | tr -d '\r' \
        | sed -E 's/^"(.*)"$/\1/; s/^'\''(.*)'\''$/\1/'
}

load_neo4j_env() {
    local src
    for src in "$ROOT_DIR/.env" "$ROOT_DIR/../../neo4j-agentcore-mcp-server/.env"; do
        if [ -f "$src" ]; then
            : "${NEO4J_URI:=$(read_env_var "$src" NEO4J_URI)}"
            : "${NEO4J_PASSWORD:=$(read_env_var "$src" NEO4J_PASSWORD)}"
        fi
    done
}

print_usage() {
    echo "Finance Agent - AgentCore deployment helper"
    echo ""
    echo "Run the agent locally without this script:"
    echo "  Terminal 1:  uv run finance-server          # Ctrl+C to stop"
    echo "  Terminal 2:  uv run finance-cli \"question\""
    echo "               uv run finance-demo"
    echo "               uv run finance-invoke memory-demo"
    echo ""
    echo "Deployment (this script):"
    echo "  ./agent.sh configure          Configure for AWS deployment"
    echo "  ./agent.sh deploy             Deploy to AgentCore Runtime"
    echo "  ./agent.sh status             Check deployment status"
    echo "  ./agent.sh invoke-cloud \"prompt\"  Invoke deployed agent"
    echo "  ./agent.sh destroy            Remove from AgentCore"
    echo "  ./agent.sh help               Show this help message"
}

ensure_deps() {
    if [ ! -d ".venv" ]; then
        echo -e "${YELLOW}Installing dependencies (first run)...${NC}"
        uv sync
        echo ""
    fi
}

case "${1:-help}" in
    configure)
        ensure_deps
        echo -e "${GREEN}Configuring agent for AWS deployment...${NC}"
        echo ""
        uv run agentcore configure -e "$ENTRYPOINT" -n "$AGENT_NAME"
        echo ""
        echo -e "${GREEN}Configuration complete!${NC}"
        echo "Run './agent.sh deploy' to deploy to AgentCore Runtime"
        ;;

    deploy)
        ensure_deps
        echo -e "${GREEN}Deploying to AgentCore Runtime...${NC}"
        echo "This may take several minutes..."
        echo ""
        load_neo4j_env
        DEPLOY_ARGS=()
        if [ -n "$NEO4J_URI" ] && [ -n "$NEO4J_PASSWORD" ]; then
            DEPLOY_ARGS+=(--env "NEO4J_URI=$NEO4J_URI")
            DEPLOY_ARGS+=(--env "NEO4J_PASSWORD=$NEO4J_PASSWORD")
            echo -e "${GREEN}Context Graph memory: injecting NEO4J_URI/NEO4J_PASSWORD into runtime env${NC}"
        else
            echo -e "${YELLOW}NEO4J_URI/NEO4J_PASSWORD not found — Context Graph memory will be disabled in the cloud (agent still runs MCP-only)${NC}"
        fi
        echo ""
        uv run agentcore deploy "${DEPLOY_ARGS[@]}"
        echo ""
        echo -e "${GREEN}Deployment complete!${NC}"
        ;;

    status)
        ensure_deps
        echo -e "${GREEN}Checking deployment status...${NC}"
        echo ""
        uv run agentcore status
        ;;

    invoke|invoke-cloud)
        ensure_deps
        if [ -z "$2" ]; then
            PROMPT="Which accounts have the highest risk scores, and who do they transfer money to?"
            echo -e "${GREEN}Invoking deployed agent with default question...${NC}"
        else
            PROMPT="$2"
            echo -e "${GREEN}Invoking deployed agent...${NC}"
        fi
        echo "Prompt: $PROMPT"
        echo ""
        uv run agentcore invoke "{\"prompt\": \"$PROMPT\"}"
        ;;

    destroy)
        ensure_deps
        echo -e "${YELLOW}Removing agent from AgentCore Runtime...${NC}"
        echo ""
        uv run agentcore destroy
        echo ""
        echo -e "${GREEN}Cleanup complete!${NC}"
        ;;

    help|--help|-h)
        print_usage
        ;;

    *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo ""
        print_usage
        exit 1
        ;;
esac
