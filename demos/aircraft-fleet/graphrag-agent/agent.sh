#!/bin/bash
# Aircraft Fleet GraphRAG Agent - AgentCore deployment helper
#
# A Strands ReAct agent that connects directly to Neo4j (no MCP server, no
# Gateway) and answers natural language questions using AWS Bedrock Claude +
# the neo4j-graphrag vector and Text2Cypher retrievers.
#
# A thin wrapper over the AgentCore CLI (`npm install -g @aws/agentcore`)
# plus local start/stop/test shortcuts. The Runtime and its env vars are
# declared in agentcore/agentcore.json. Passwords never go there: the
# Runtime reads them from Secrets Manager through the *_SECRET_ARN vars.
#
# `start` runs the local server in the foreground (port 7070). The same
# server and the clients are also uv console scripts. See the README
# "Quick Start: Local". In short:
#
#   Terminal 1:  uv run fleet-server           # or ./agent.sh start
#                uv run opentelemetry-instrument fleet-server   # + tracing
#   Terminal 2:  uv run fleet-cli "question"
#                uv run fleet-demo
#                uv run fleet-invoke load-test
#
# Usage:
#   ./agent.sh start              Start the agent locally (port 7070)
#   ./agent.sh stop               Stop the local agent
#   ./agent.sh test               Test the local agent
#   ./agent.sh deploy             Deploy to AgentCore Runtime
#   ./agent.sh status             Check deployment status
#   ./agent.sh invoke-cloud "prompt"  Invoke deployed agent
#   ./agent.sh logs [args]        Search or tail the Runtime logs
#   ./agent.sh destroy            Remove from AgentCore
#
# Prerequisites:
#   - Local runs: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD in the shared
#     ../.env at the aircraft-fleet root
#   - Deploy: the AgentCore CLI on PATH, and the env var values in
#     agentcore/agentcore.json filled in for your Neo4j instances
#   - AWS credentials configured (for Bedrock access)

set -e

# The uv project (pyproject.toml, uv.lock, .venv), the fleet_graphrag
# package, the AgentCore entrypoint (main.py), and this script all live at
# the agent root.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_usage() {
    echo "Aircraft Fleet GraphRAG Agent - AgentCore helper"
    echo ""
    echo "Local:"
    echo "  ./agent.sh start              Start the agent locally (port 7070)"
    echo "  ./agent.sh stop               Stop the local agent"
    echo "  ./agent.sh test               Test the local agent"
    echo ""
    echo "Or run the server and clients directly:"
    echo "  Terminal 1:  uv run fleet-server           # Ctrl+C to stop"
    echo "               uv run opentelemetry-instrument fleet-server  # + tracing"
    echo "  Terminal 2:  uv run fleet-cli \"question\""
    echo "               uv run fleet-demo"
    echo "               uv run fleet-invoke load-test"
    echo ""
    echo "Deployment (AgentCore CLI):"
    echo "  ./agent.sh deploy             Deploy to AgentCore Runtime"
    echo "  ./agent.sh status             Check deployment status"
    echo "  ./agent.sh invoke-cloud \"prompt\"  Invoke deployed agent"
    echo "  ./agent.sh logs [args]        Search or tail the Runtime logs (--tail)"
    echo "  ./agent.sh destroy            Remove from AgentCore"
    echo "  ./agent.sh help               Show this help message"
}

# Must match the Runtime name in agentcore/agentcore.json and
# RUNTIME_NAME / DEPLOY_TARGET in client/transport.py.
RUNTIME_NAME="graphrag_agent"
TARGET="default"
PROJECT_SPEC="agentcore/agentcore.json"

ensure_deps() {
    if [ ! -d ".venv" ]; then
        echo -e "${YELLOW}Installing dependencies (first run)...${NC}"
        uv sync
        echo ""
    fi
}

ensure_cli() {
    if ! command -v agentcore >/dev/null 2>&1; then
        echo -e "${RED}ERROR: the agentcore CLI is not installed${NC}"
        echo "Install it with: npm install -g @aws/agentcore"
        exit 1
    fi
}

# The CodeZip build ships every file under this directory except agentcore/,
# .venv, .git, node_modules, and Python caches. Refuse to deploy while a
# secrets file is present anywhere it would be packaged.
refuse_secret_files() {
    local found
    found=$(find . \
        \( -path ./agentcore -o -name .venv -o -name .git -o -name node_modules \
           -o -name __pycache__ -o -name .pytest_cache \) -prune \
        -o \( -name '.env*' -o -name '.mcp-credentials*.json' \) -print)
    if [ -n "$found" ]; then
        echo -e "${RED}ERROR: secrets files would be packaged into the deployment:${NC}"
        echo "$found"
        echo ""
        echo "Move them out of $(pwd) before deploying."
        echo "Local runs read the shared ../.env at the aircraft-fleet root."
        exit 1
    fi
}

# TODO(deploy): fill the env var values in agentcore/agentcore.json before
# deploying. The *_PASSWORD_SECRET_ARN values name Secrets Manager secrets
# that hold the Neo4j passwords. Never put a password in that file.
refuse_placeholders() {
    if grep -q "REPLACE_ME" "$PROJECT_SPEC"; then
        echo -e "${RED}ERROR: $PROJECT_SPEC still has REPLACE_ME placeholders${NC}"
        echo "Set the Neo4j URIs and the password secret ARNs for your instances."
        exit 1
    fi
}

case "${1:-help}" in
    start)
        ensure_deps
        echo -e "${GREEN}Starting Aircraft Fleet GraphRAG Agent on port 7070...${NC}"
        echo "Test with: ./agent.sh test"
        echo ""
        uv run fleet-server
        ;;

    stop)
        echo -e "${YELLOW}Stopping local agent...${NC}"
        pkill -f "fleet-server" 2>/dev/null || echo "No agent process found"
        echo -e "${GREEN}Stopped.${NC}"
        ;;

    test)
        ensure_deps
        echo -e "${GREEN}Testing local agent...${NC}"
        echo ""
        uv run fleet-cli "How many aircraft are in the database?"
        ;;

    deploy)
        ensure_cli
        refuse_secret_files
        refuse_placeholders
        echo -e "${GREEN}Deploying agent to AgentCore Runtime...${NC}"
        echo "This may take several minutes..."
        echo ""
        agentcore deploy --target "$TARGET" "${@:2}"
        echo ""
        echo -e "${GREEN}Deployment complete!${NC}"
        echo "Run './agent.sh status' to check status"
        echo "Run './agent.sh invoke-cloud \"your question\"' to test"
        ;;

    status)
        ensure_cli
        echo -e "${GREEN}Checking deployment status...${NC}"
        echo ""
        agentcore status --target "$TARGET"
        ;;

    invoke|invoke-cloud)
        ensure_deps
        ensure_cli
        if [ -z "$2" ]; then
            PROMPT="How many aircraft are in the database?"
            echo -e "${GREEN}Invoking deployed agent with default question...${NC}"
        else
            PROMPT="$2"
            echo -e "${GREEN}Invoking deployed agent...${NC}"
        fi
        echo "Prompt: $PROMPT"
        echo ""
        # json.dumps escapes quotes and newlines in the prompt.
        PAYLOAD=$(uv run python -c 'import json, sys; print(json.dumps({"prompt": sys.argv[1]}))' "$PROMPT")
        agentcore invoke --runtime "$RUNTIME_NAME" --target "$TARGET" --payload "$PAYLOAD"
        ;;

    logs)
        ensure_cli
        agentcore logs runtime --name "$RUNTIME_NAME" --target "$TARGET" "${@:2}"
        ;;

    destroy)
        ensure_cli
        # CLI 1.1.0 has no destroy command. A deploy of a project that
        # declares nothing removes the target's stack, so remove the Runtime
        # from the spec, deploy, and put the spec back.
        echo -e "${YELLOW}Removing agent from AgentCore Runtime...${NC}"
        echo ""
        SPEC_BACKUP=$(mktemp)
        cp "$PROJECT_SPEC" "$SPEC_BACKUP"
        trap 'cp "$SPEC_BACKUP" "$PROJECT_SPEC"; rm -f "$SPEC_BACKUP"' EXIT
        agentcore remove runtime --name "$RUNTIME_NAME"
        agentcore deploy --target "$TARGET" --yes
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
