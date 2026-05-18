#!/bin/bash
# Finance Agent - AgentCore Runtime
#
# A ReAct agent for financial data analysis that connects to the Neo4j MCP
# server via AgentCore Gateway.
#
# Usage:
#   ./agent.sh start              Start agent locally (port 8080)
#   ./agent.sh stop               Stop local agent
#   ./agent.sh test               Test local agent with curl
#   ./agent.sh configure          Configure for AWS deployment
#   ./agent.sh deploy             Deploy to AgentCore Runtime
#   ./agent.sh status             Check deployment status
#   ./agent.sh invoke-cloud "prompt"  Invoke deployed agent
#   ./agent.sh memory-demo        Cross-session Context Graph memory demo
#   ./agent.sh destroy            Remove from AgentCore
#
# Prerequisites:
#   - .mcp-credentials.json at the agent root (from Neo4j MCP deployment)
#   - AWS credentials configured (for Bedrock access)

set -e

# uv project (pyproject.toml, uv.lock, .venv, .mcp-credentials.json) lives at
# the agent root; this script and the entrypoint live in this variant dir.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VARIANT="$(basename "$SCRIPT_DIR")"
ENTRYPOINT="$VARIANT/agent.py"
AGENT_NAME="finance_${VARIANT}"
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
    echo "Finance Agent (${VARIANT}) - AgentCore Runtime"
    echo ""
    echo "Usage:"
    echo "  ./agent.sh start              Start agent locally (port 8080)"
    echo "  ./agent.sh stop               Stop local agent"
    echo "  ./agent.sh test               Test local agent with curl"
    echo "  ./agent.sh configure          Configure for AWS deployment"
    echo "  ./agent.sh deploy             Deploy to AgentCore Runtime"
    echo "  ./agent.sh status             Check deployment status"
    echo "  ./agent.sh invoke-cloud \"prompt\"  Invoke deployed agent"
    echo "  ./agent.sh memory-demo        Cross-session Context Graph memory demo"
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
    start)
        ensure_deps
        if [ ! -f ".mcp-credentials.json" ]; then
            echo -e "${RED}ERROR: .mcp-credentials.json not found${NC}"
            echo ""
            echo "Copy credentials from your Neo4j MCP server deployment:"
            echo "  cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json ."
            exit 1
        fi
        echo -e "${GREEN}Starting agent locally on port 8080...${NC}"
        echo "Test with: curl -X POST http://localhost:8080/invocations -H 'Content-Type: application/json' -d '{\"prompt\": \"Hello\"}'"
        echo ""
        uv run python "$ENTRYPOINT"
        ;;

    stop)
        echo -e "${YELLOW}Stopping local agent...${NC}"
        pkill -f "python $ENTRYPOINT" 2>/dev/null || echo "No agent process found"
        echo -e "${GREEN}Stopped.${NC}"
        ;;

    test)
        echo -e "${GREEN}Testing local agent...${NC}"
        echo ""
        curl -s -X POST http://localhost:8080/invocations \
            -H "Content-Type: application/json" \
            -d '{"prompt": "What companies are in the database?"}' | python -m json.tool
        ;;

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
            PROMPT="What companies are in the database?"
            echo -e "${GREEN}Invoking deployed agent with default question...${NC}"
        else
            PROMPT="$2"
            echo -e "${GREEN}Invoking deployed agent...${NC}"
        fi
        echo "Prompt: $PROMPT"
        echo ""
        uv run agentcore invoke "{\"prompt\": \"$PROMPT\"}"
        ;;

    memory-demo)
        ensure_deps
        if [ "$VARIANT" != "strands" ]; then
            echo -e "${YELLOW}WARNING: memory tools exist only in the Strands variant.${NC}"
            echo -e "${YELLOW}This demo is only meaningful against a deployed Strands agent.${NC}"
            echo ""
        fi
        echo -e "${GREEN}Running cross-session Context Graph memory demo...${NC}"
        echo ""
        DEMO_ARGS=(memory-demo)
        [ -n "$2" ] && DEMO_ARGS+=(--user-id "$2")
        uv run python invoke_agent.py "${DEMO_ARGS[@]}"
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
