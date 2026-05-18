#!/bin/bash
# Neo4j Fleet Agent - AgentCore Runtime
#
# A Strands ReAct agent that connects directly to Neo4j (no MCP server, no
# Gateway) and answers natural language questions using AWS Bedrock Claude +
# the neo4j-graphrag vector and Text2Cypher retrievers.
#
# Usage:
#   ./agent.sh start              Start locally (port 8080, ADOT tracing)
#   ./agent.sh stop               Stop local agent
#   ./agent.sh test               Test local agent with curl
#   ./agent.sh cli "prompt"       Ask the local agent (thin client)
#   ./agent.sh demo               Run the functionality showcase (local)
#   ./agent.sh configure          Configure for AWS deployment
#   ./agent.sh deploy             Deploy to AgentCore Runtime
#   ./agent.sh status             Check deployment status
#   ./agent.sh invoke-cloud "prompt"  Invoke deployed agent
#   ./agent.sh load-test [N]      Run load test (Ns interval, default 5)
#   ./agent.sh destroy            Remove from AgentCore
#
# Prerequisites:
#   - Neo4j connection env vars: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
#     (a .env at the agent root is auto-loaded for local runs)
#   - AWS credentials configured (for Bedrock access)

set -e

# The uv project (pyproject.toml, uv.lock, .venv, .env), the agent core
# (agent/), the thin clients (client/), the entrypoint (runtime_app.py), and
# this script all live at the agent root.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_usage() {
    echo "Neo4j Fleet Agent - AgentCore Runtime"
    echo ""
    echo "Usage:"
    echo "  ./agent.sh start              Start locally (port 8080)"
    echo "  ./agent.sh stop               Stop local agent"
    echo "  ./agent.sh test               Test local agent with curl"
    echo "  ./agent.sh cli \"prompt\"        Ask the local agent (thin client)"
    echo "  ./agent.sh demo               Run the functionality showcase (local)"
    echo "  ./agent.sh configure          Configure for AWS deployment"
    echo "  ./agent.sh deploy             Deploy to AgentCore Runtime"
    echo "  ./agent.sh status             Check deployment status"
    echo "  ./agent.sh invoke-cloud \"prompt\"  Invoke deployed agent"
    echo "  ./agent.sh load-test [N]      Run load test (Ns interval)"
    echo "  ./agent.sh destroy            Remove from AgentCore"
    echo "  ./agent.sh help               Show this help message"
}

ENTRYPOINT="runtime_app.py"
AGENT_NAME="fleet_agent"

ensure_deps() {
    if [ ! -d ".venv" ]; then
        echo -e "${YELLOW}Installing dependencies (first run)...${NC}"
        uv sync
        echo ""
    fi
}

# Load the agent-root .env (if present) and require Neo4j connection vars.
# The agent connects directly to Neo4j — there is no MCP/Gateway credential.
load_env() {
    if [ -f ".env" ]; then
        set -a
        # shellcheck disable=SC1091
        . ./.env
        set +a
    fi
    if [ -z "$NEO4J_URI" ] || [ -z "$NEO4J_PASSWORD" ]; then
        echo -e "${RED}ERROR: NEO4J_URI / NEO4J_PASSWORD not set${NC}"
        echo ""
        echo "Set Neo4j connection vars (e.g. in a .env at the agent root):"
        echo "  NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io"
        echo "  NEO4J_USERNAME=neo4j"
        echo "  NEO4J_PASSWORD=your-password"
        exit 1
    fi
}

# Build the `agentcore deploy` env-var flags from the loaded environment.
# Required Neo4j vars always go; optional overrides only when explicitly set.
deploy_env_args() {
    DEPLOY_ENV_ARGS=(
        -env "NEO4J_URI=$NEO4J_URI"
        -env "NEO4J_USERNAME=${NEO4J_USERNAME:-neo4j}"
        -env "NEO4J_PASSWORD=$NEO4J_PASSWORD"
        -env "NEO4J_DATABASE=${NEO4J_DATABASE:-neo4j}"
    )
    local var
    for var in MODEL_ID AWS_REGION VECTOR_INDEX_NAME EMBED_MODEL_ID \
               EMBED_DIMENSIONS; do
        if [ -n "${!var}" ]; then
            DEPLOY_ENV_ARGS+=(-env "$var=${!var}")
        fi
    done
}

case "${1:-help}" in
    start)
        ensure_deps
        load_env
        echo -e "${GREEN}Starting agent locally on port 8080 with OTEL instrumentation...${NC}"
        echo "Test with: curl -X POST http://localhost:8080/invocations -H 'Content-Type: application/json' -d '{\"prompt\": \"Hello\"}'"
        echo ""
        uv run opentelemetry-instrument python "$ENTRYPOINT"
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
            -d '{"prompt": "What is the database schema?"}' | python -m json.tool
        ;;

    cli)
        # Thin client — talks to the running agent over the wire; needs no
        # Neo4j credentials of its own (the server holds those).
        ensure_deps
        uv run python -m client.cli "${@:2}"
        ;;

    demo)
        ensure_deps
        uv run python -m client.demo "${@:2}"
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
        load_env
        deploy_env_args
        echo -e "${GREEN}Deploying agent to AgentCore Runtime...${NC}"
        echo "Passing Neo4j connection as Runtime environment variables."
        echo "This may take several minutes..."
        echo ""
        uv run agentcore deploy "${DEPLOY_ENV_ARGS[@]}"
        echo ""
        echo -e "${GREEN}Deployment complete!${NC}"
        echo "Run './agent.sh status' to check status"
        echo "Run './agent.sh invoke-cloud \"your question\"' to test"
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
            PROMPT="How many aircraft are in the database?"
            echo -e "${GREEN}Invoking deployed agent with default question...${NC}"
        else
            PROMPT="$2"
            echo -e "${GREEN}Invoking deployed agent...${NC}"
        fi
        echo "Prompt: $PROMPT"
        echo ""
        uv run agentcore invoke "{\"prompt\": \"$PROMPT\"}"
        ;;

    load-test)
        ensure_deps
        INTERVAL="${2:-5}"
        echo -e "${GREEN}Starting load test (${INTERVAL}s interval)...${NC}"
        echo "Press Ctrl+C to stop"
        echo ""
        uv run python -m client.invoke load-test "$INTERVAL"
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
