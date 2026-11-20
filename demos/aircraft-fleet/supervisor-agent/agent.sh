#!/bin/bash
# Aircraft Fleet Supervisor Agent - AgentCore Runtime
#
# A supervisor agent that routes queries to specialized workers:
# - Maintenance Agent: reliability, faults, components, sensors
# - Operations Agent: flights, delays, routes, airports
#
# Usage:
#   ./agent.sh start              Start supervisor locally (port 7071)
#   ./agent.sh test               Test local supervisor
#   ./agent.sh configure          Create the AgentCore project in agentcore/
#   ./agent.sh deploy             Deploy to AgentCore Runtime
#   ./agent.sh status             Check deployment status
#   ./agent.sh logs               Show recent runtime logs
#   ./agent.sh invoke-cloud           Send default question to deployed agent
#   ./agent.sh invoke-cloud "prompt"  Send custom question to deployed agent
#   ./agent.sh destroy            Remove from AgentCore
#
# The cloud commands use the AgentCore CLI (npm install -g @aws/agentcore).
# The project lives in agentcore/. Its runtime's codeLocation is this folder,
# so `agentcore deploy` zips everything here except .git, .venv,
# __pycache__, .pytest_cache, .DS_Store, node_modules, and agentcore/.

set -e

# This script, the uv project (pyproject.toml, uv.lock, .venv), and the
# runtime entrypoint main.py live at the agent root. All the code is in the
# fleet_supervisor/ package next to main.py. The local Gateway credentials
# file sits one level up, in demos/aircraft-fleet/, outside the code zip.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRYPOINT="main.py"
# The deployed runtime name is <project>_<target>_<runtime> and must be at
# most 48 characters, so both names are short.
PROJECT_NAME="fleetsupervisor"
RUNTIME_NAME="supervisor"
# Matches .python-version.
RUNTIME_VERSION="PYTHON_3_12"
# Non-secret runtime environment variables, written into agentcore.json.
# GATEWAY_CREDENTIAL_PROVIDER names the AgentCore Identity OAuth2 provider
# that holds the Gateway client secret. Setting it selects the cloud auth path.
RUNTIME_ENV='{"MODEL_ID":"global.anthropic.claude-sonnet-5-5","GATEWAY_URL":"REPLACE_WITH_FLEET_GATEWAY_URL","GATEWAY_CREDENTIAL_PROVIDER":"fleet-gateway"}'
# Local Gateway credentials, written by neo4j-mcp-server/deploy.py.
CREDENTIALS_FILE="${MCP_CREDENTIALS_FILE:-$ROOT_DIR/../.mcp-credentials.json}"
# AgentCore deployment region. AgentCore's primary region is us-east-1
# (also supported in us-west-2). Set AWS_REGION to override. The CLI creates
# the default deploy target from this region on the first deploy.
REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION="$REGION"
# Local server port. graphrag-agent uses 7070; AgentCore Runtime uses 8080.
LOCAL_PORT="${AGENT_PORT:-7071}"
cd "$ROOT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_usage() {
    echo "Aircraft Fleet Supervisor Agent - AgentCore Runtime"
    echo ""
    echo "Routes queries to Maintenance and Operations specialist agents."
    echo ""
    echo "Usage:"
    echo "  ./agent.sh start              Start supervisor locally (port 7071)"
    echo "  ./agent.sh stop               Stop local supervisor"
    echo "  ./agent.sh test               Test local supervisor"
    echo "  ./agent.sh test-maintenance   Test with maintenance query"
    echo "  ./agent.sh test-operations    Test with operations query"
    echo "  ./agent.sh configure          Create the AgentCore project in agentcore/"
    echo "  ./agent.sh deploy             Deploy to AgentCore Runtime"
    echo "  ./agent.sh status             Check deployment status"
    echo "  ./agent.sh logs [30m]         Show runtime logs from the last 30 minutes"
    echo "  ./agent.sh invoke-cloud       Send default question to deployed agent"
    echo "  ./agent.sh invoke-cloud \"q\"   Send custom question to deployed agent"
    echo "  ./agent.sh load-test          Cloud load test (random queries every 5s)"
    echo "  ./agent.sh load-test 10       Cloud load test with custom interval"
    echo "  ./agent.sh destroy            Remove from AgentCore"
    echo "  ./agent.sh help               Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./agent.sh test-maintenance   # Routes to Maintenance Agent"
    echo "  ./agent.sh test-operations    # Routes to Operations Agent"
    echo "  ./agent.sh invoke-cloud \"What are the most common faults?\""
    echo "  ./agent.sh load-test          # Continuous cloud load testing"
}

ensure_agentcore_cli() {
    if ! command -v agentcore >/dev/null 2>&1; then
        echo -e "${RED}ERROR: the AgentCore CLI is not installed${NC}"
        echo ""
        echo "Install it with:"
        echo "  npm install -g @aws/agentcore"
        exit 1
    fi
}

ensure_project() {
    ensure_agentcore_cli
    if [ ! -f "agentcore/agentcore.json" ]; then
        echo -e "${RED}ERROR: agentcore/agentcore.json not found${NC}"
        echo "Run './agent.sh configure' first."
        exit 1
    fi
}

# The code zip has no ignore file, so any .env* or .mcp-credentials*.json
# file in this folder would be uploaded with the code. .venv is not zipped,
# and agentcore/ holds the CLI's own .env.local, which is not zipped either.
ensure_no_secrets_in_zip() {
    local found
    found="$(find . \( -path ./.venv -o -path ./agentcore \) -prune -o \
        -type f \( -name '.env*' -o -name '.mcp-credentials*.json' \) -print)"
    if [ -n "$found" ]; then
        echo -e "${RED}ERROR: secret files are inside $ROOT_DIR${NC}"
        echo ""
        echo "$found"
        echo ""
        echo "agentcore deploy would upload them with the code. Move them out first."
        echo "The local credentials file belongs in demos/aircraft-fleet/.mcp-credentials.json."
        exit 1
    fi
}

# Print the deployed runtime ARN: AGENT_ARN if set, else from
# `agentcore status --json`. The match is on the ARN format because the
# status JSON layout is not documented.
runtime_arn() {
    if [ -n "${AGENT_ARN:-}" ]; then
        echo "$AGENT_ARN"
        return
    fi
    agentcore status --json 2>/dev/null \
        | jq -r '[.. | strings | select(test("^arn:aws[a-z0-9-]*:bedrock-agentcore:[^:]+:[0-9]+:runtime/[^/]+$"))][0] // empty'
}

# Create agentcore/ the way `agentcore create` and `agentcore add runtime`
# lay it out, then point the runtime at this folder's existing code.
create_project() {
    local tmp
    tmp="$(mktemp -d)"
    (cd "$tmp" && agentcore create --name "$PROJECT_NAME" --skip-install --skip-git)
    mv "$tmp/$PROJECT_NAME/agentcore" agentcore
    rm -rf "$tmp"

    agentcore add runtime \
        --name "$RUNTIME_NAME" \
        --language python \
        --description "Aircraft fleet supervisor with Maintenance and Operations specialists" \
        --environment-variables "$RUNTIME_ENV"
    # add runtime writes starter docs to app/<name>/; the code lives here instead.
    rm -rf app

    local spec="agentcore/agentcore.json"
    jq --arg name "$RUNTIME_NAME" --arg entry "$ENTRYPOINT" --arg ver "$RUNTIME_VERSION" \
        '(.runtimes[] | select(.name == $name)) |= (.codeLocation = "." | .entrypoint = $entry | .runtimeVersion = $ver)' \
        "$spec" > "$spec.tmp"
    mv "$spec.tmp" "$spec"
}

ensure_deps() {
    if [ ! -d ".venv" ]; then
        echo -e "${YELLOW}Installing dependencies (first run)...${NC}"
        uv sync
        echo ""
    fi
}

ensure_credentials() {
    if [ ! -f "$CREDENTIALS_FILE" ]; then
        echo -e "${RED}ERROR: $CREDENTIALS_FILE not found${NC}"
        echo ""
        echo "Copy it from the MCP server deployment:"
        echo "  cp \"$ROOT_DIR/../../../neo4j-mcp-server/.mcp-credentials.fleet.json\" \"$CREDENTIALS_FILE\""
        exit 1
    fi
}

case "${1:-help}" in
    start)
        ensure_deps
        ensure_credentials
        echo -e "${GREEN}Starting Aircraft Fleet Supervisor Agent on port ${LOCAL_PORT}...${NC}"
        echo -e "${BLUE}Agents: Maintenance (faults/components) + Operations (flights/delays)${NC}"
        echo ""
        echo "Test with:"
        echo "  ./agent.sh test-maintenance   # Routes to Maintenance Agent"
        echo "  ./agent.sh test-operations    # Routes to Operations Agent"
        echo ""
        AGENT_PORT="$LOCAL_PORT" uv run fleet-supervisor-server
        ;;

    stop)
        echo -e "${YELLOW}Stopping local supervisor...${NC}"
        pkill -f "fleet-supervisor-server" 2>/dev/null || echo "No supervisor process found"
        echo -e "${GREEN}Stopped.${NC}"
        ;;

    test)
        ensure_deps
        echo -e "${GREEN}Testing supervisor with a general query...${NC}"
        echo ""
        AGENT_PORT="$LOCAL_PORT" uv run fleet-supervisor-cli "${2:-What is the database schema?}"
        ;;

    test-maintenance)
        ensure_deps
        echo -e "${GREEN}Testing Maintenance Agent routing...${NC}"
        echo ""
        AGENT_PORT="$LOCAL_PORT" uv run fleet-supervisor-cli "What are the most common maintenance faults?"
        ;;

    test-operations)
        ensure_deps
        echo -e "${GREEN}Testing Operations Agent routing...${NC}"
        echo ""
        AGENT_PORT="$LOCAL_PORT" uv run fleet-supervisor-cli "What are the most common delay causes?"
        ;;

    configure)
        ensure_agentcore_cli
        if [ -f "agentcore/agentcore.json" ]; then
            echo -e "${GREEN}AgentCore project already exists in agentcore/${NC}"
        else
            echo -e "${GREEN}Creating AgentCore project in agentcore/...${NC}"
            echo ""
            create_project
        fi
        echo ""
        echo -e "${GREEN}Installing CDK dependencies...${NC}"
        (cd agentcore/cdk && npm install)
        echo ""
        echo -e "${GREEN}Configuration complete!${NC}"
        echo "Set GATEWAY_URL in agentcore/agentcore.json, then run './agent.sh deploy'"
        ;;

    deploy)
        ensure_project
        ensure_no_secrets_in_zip
        echo -e "${GREEN}Deploying Aircraft Fleet Supervisor Agent to AgentCore Runtime...${NC}"
        echo "This may take several minutes..."
        echo ""
        agentcore deploy "${@:2}"
        echo ""
        echo -e "${GREEN}Deployment complete!${NC}"
        echo "Run './agent.sh status' to check status"
        echo "Run './agent.sh invoke-cloud \"your question\"' to test"
        ;;

    status)
        ensure_project
        echo -e "${GREEN}Checking deployment status...${NC}"
        echo ""
        agentcore status "${@:2}"
        ;;

    logs)
        ensure_project
        agentcore logs runtime --name "$RUNTIME_NAME" --since "${2:-30m}"
        ;;

    invoke|invoke-cloud)
        ensure_project
        PROMPT="${2:-What are the most common maintenance faults across all aircraft?}"
        if [ -z "$2" ]; then
            echo -e "${YELLOW}Using default question${NC}"
        fi
        echo -e "${GREEN}Invoking deployed supervisor...${NC}"
        echo -e "${BLUE}Prompt: $PROMPT${NC}"
        echo ""
        # jq builds the JSON, so quotes in the prompt are escaped.
        agentcore invoke --runtime "$RUNTIME_NAME" --payload "$(jq -nc --arg p "$PROMPT" '{prompt: $p}')"
        ;;

    load-test)
        ensure_deps
        ensure_project
        ARN="$(runtime_arn)"
        if [ -z "$ARN" ]; then
            echo -e "${RED}ERROR: could not find the deployed runtime ARN${NC}"
            echo "Set AGENT_ARN, or run './agent.sh deploy' first."
            exit 1
        fi
        echo -e "${GREEN}Starting cloud load test...${NC}"
        echo -e "${BLUE}Tests routing to Maintenance and Operations agents${NC}"
        echo ""
        AGENT_ARN="$ARN" uv run fleet-supervisor-invoke load-test "${@:2}"
        ;;

    destroy)
        ensure_project
        echo -e "${YELLOW}Removing supervisor from AgentCore Runtime...${NC}"
        echo ""
        # The CLI has no destroy command. Emptying the project and deploying
        # deletes the target's stack. agentcore.json then has no runtime, so
        # restore it from git before deploying again.
        agentcore remove all --yes
        agentcore deploy --yes
        echo ""
        echo -e "${GREEN}Cleanup complete!${NC}"
        echo "Restore the project spec with: git checkout -- agentcore/agentcore.json"
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
