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
#   ./agent.sh deploy             Deploy and verify AgentCore Runtime
#   ./agent.sh status             Check deployment status
#   ./agent.sh verify             Check READY state and run an end-to-end smoke test
#   ./agent.sh logs [options]     Inspect AgentCore observability traces
#   ./agent.sh reset-config       Archive local AgentCore config and start fresh
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
CONFIG_FILE="$ROOT_DIR/.bedrock_agentcore.yaml"
# Keep wrapper state beside the toolkit's per-agent dependency cache.  The
# parent directory is already ignored and is safe to remove at any time.
DEPENDENCY_FINGERPRINT_FILE="$ROOT_DIR/.bedrock_agentcore/$AGENT_NAME/wrapper-dependency-fingerprint"
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

clear_stale_runtime_binding() {
    # `agentcore configure` intentionally preserves the previous deployment
    # identifier. Clear it only when it cannot refer to the configured region
    # or AWS confirms that the runtime was deleted. This lets deploy create a
    # replacement instead of attempting UpdateAgentRuntime on a stale ID.
    .venv/bin/python scripts/clear_stale_agentcore_runtime.py \
        --config "$ROOT_DIR/.bedrock_agentcore.yaml" \
        --agent "$AGENT_NAME"
}

dependency_fingerprint() {
    # Include both the declared constraints and the resolved lockfile.  The
    # legacy toolkit cache is lockfile-oriented, so this catches a constraint
    # edit even if the lockfile happens to resolve to the same versions.
    shasum pyproject.toml uv.lock | shasum | awk '{print $1}'
}

deployment_needs_dependency_rebuild() {
    local current_fingerprint
    current_fingerprint="$(dependency_fingerprint)"
    DEPENDENCY_FINGERPRINT="$current_fingerprint"

    if [ ! -f "$DEPENDENCY_FINGERPRINT_FILE" ]; then
        echo "Dependency fingerprint not found; rebuilding deployment dependencies."
        return 0
    fi

    if [ "$(<"$DEPENDENCY_FINGERPRINT_FILE")" != "$current_fingerprint" ]; then
        echo "Dependency inputs changed; rebuilding deployment dependencies."
        return 0
    fi
    return 1
}

record_dependency_fingerprint() {
    mkdir -p "$(dirname "$DEPENDENCY_FINGERPRINT_FILE")"
    printf '%s\n' "$DEPENDENCY_FINGERPRINT" > "$DEPENDENCY_FINGERPRINT_FILE"
}

verify_deployment() {
    .venv/bin/python scripts/verify_agentcore_runtime.py \
        --config "$CONFIG_FILE" \
        --agent "$AGENT_NAME"
}

archive_local_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "No local AgentCore config exists at $CONFIG_FILE."
        return 0
    fi

    local backup="$ROOT_DIR/.bedrock_agentcore.yaml.backup-$(date +%Y%m%d-%H%M%S)"
    mv "$CONFIG_FILE" "$backup"
    rm -f "$DEPENDENCY_FINGERPRINT_FILE"
    echo "Archived local AgentCore config to: $backup"
    echo "No AWS resources were changed. Run './agent.sh configure' to create a new config."
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
    echo "  ./agent.sh deploy             Deploy, then verify the runtime with a graph smoke test"
    echo "  ./agent.sh deploy --skip-smoke  Deploy without health verification (not recommended)"
    echo "  ./agent.sh status             Check deployment status"
    echo "  ./agent.sh verify             Check READY state and run the graph smoke test"
    echo "  ./agent.sh logs [--errors]    List recent AgentCore observability traces"
    echo "  ./agent.sh invoke-cloud \"prompt\"  Invoke deployed agent"
    echo "  ./agent.sh reset-config       Archive local config; does not delete AWS resources"
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
        SKIP_SMOKE=false
        FORCE_REBUILD=false
        shift
        for arg in "$@"; do
            case "$arg" in
                --skip-smoke) SKIP_SMOKE=true ;;
                --force-rebuild-deps) FORCE_REBUILD=true ;;
                *)
                    echo -e "${RED}Unknown deploy option: $arg${NC}"
                    echo "Supported options: --skip-smoke, --force-rebuild-deps"
                    exit 2
                    ;;
            esac
        done
        clear_stale_runtime_binding
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
        REBUILD_DEPENDENCIES=false
        if deployment_needs_dependency_rebuild; then
            REBUILD_DEPENDENCIES=true
        fi
        if [ "$FORCE_REBUILD" = true ]; then
            echo "Dependency rebuild explicitly requested."
            REBUILD_DEPENDENCIES=true
        fi
        if [ "$REBUILD_DEPENDENCIES" = true ]; then
            DEPLOY_ARGS+=(--force-rebuild-deps)
        fi
        echo -e "${GREEN}NAMS memory: injecting MEMORY_API_KEY into runtime env${NC}"
        echo ""
        uv run agentcore deploy "${DEPLOY_ARGS[@]}"
        echo ""
        if [ "$SKIP_SMOKE" = true ]; then
            record_dependency_fingerprint
            echo -e "${YELLOW}Deployment upload completed, but health verification was skipped.${NC}"
            echo "Run './agent.sh verify' before sending production traffic."
            exit 0
        fi

        echo "Validating READY state and executing an end-to-end graph smoke test..."
        if ! verify_deployment; then
            echo -e "${RED}Deployment was uploaded, but it was not verified as healthy.${NC}"
            echo "Inspect recent failures with: ./agent.sh logs --errors"
            echo "Re-run the check with: ./agent.sh verify"
            exit 1
        fi
        record_dependency_fingerprint
        echo -e "${GREEN}Deployment verified and ready for traffic.${NC}"
        ;;

    status)
        ensure_deps
        echo -e "${GREEN}Checking deployment status...${NC}"
        echo ""
        uv run agentcore status
        ;;

    verify)
        ensure_deps
        echo -e "${GREEN}Verifying deployed runtime...${NC}"
        echo ""
        verify_deployment
        ;;

    logs)
        ensure_deps
        shift
        echo -e "${GREEN}Listing recent AgentCore observability traces...${NC}"
        echo "Use './agent.sh logs --errors' to show failed traces only."
        echo ""
        uv run agentcore obs list --agent "$AGENT_NAME" "$@"
        ;;

    reset-config)
        archive_local_config
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
