#!/bin/bash
# Finance Agent - AgentCore deployment helper
#
# This script does ONE thing: deploy/manage the agent on AgentCore Runtime.
# It is a thin wrapper over the `agentcore` CLI; the only reason it exists
# (rather than documenting raw `agentcore` commands) is that `deploy` sources
# MEMORY_API_KEY from .env and injects it into the runtime for NAMS memory.
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

# NAMS configuration. Source it from finance-agent/.env. Read the first
# matching value only; split on the first '=' so keys containing '=' survive.
read_env_var() {
    # $1=file  $2=key. Takes the first match, strips CR and one layer of
    # surrounding single/double quotes (common .env style).
    [ -f "$1" ] || return 1
    sed -n "s/^[[:space:]]*$2=//p" "$1" | head -n1 | tr -d '\r' \
        | sed -E 's/^"(.*)"$/\1/; s/^'\''(.*)'\''$/\1/'
}

load_nams_env() {
    local src="$ROOT_DIR/.env"
    [ -f "$src" ] || return 0
    : "${MEMORY_API_KEY:=$(read_env_var "$src" MEMORY_API_KEY)}"
    : "${MEMORY_ENDPOINT:=$(read_env_var "$src" MEMORY_ENDPOINT)}"
    : "${MEMORY_WORKSPACE_ID:=$(read_env_var "$src" MEMORY_WORKSPACE_ID)}"
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
        load_nams_env
        if [ -z "$MEMORY_API_KEY" ]; then
            echo -e "${RED}ERROR: MEMORY_API_KEY not found.${NC}"
            echo "NAMS memory is required. Provide it in finance-agent/.env"
            echo "and re-run './agent.sh deploy'."
            exit 1
        fi
        DEPLOY_ARGS=(--env "MEMORY_API_KEY=$MEMORY_API_KEY")
        [ -z "$MEMORY_ENDPOINT" ] || DEPLOY_ARGS+=(--env "MEMORY_ENDPOINT=$MEMORY_ENDPOINT")
        [ -z "$MEMORY_WORKSPACE_ID" ] || DEPLOY_ARGS+=(--env "MEMORY_WORKSPACE_ID=$MEMORY_WORKSPACE_ID")
        echo -e "${GREEN}NAMS memory: injecting MEMORY_API_KEY into runtime env${NC}"
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
