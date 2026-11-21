#!/bin/bash
# Aircraft Fleet GraphRAG Agent - AgentCore deployment helper
#
# A Strands ReAct agent that connects directly to Neo4j (no MCP server, no
# Gateway) and answers natural language questions using AWS Bedrock Claude +
# the neo4j-graphrag vector and Text2Cypher retrievers.
#
# A thin wrapper over the AgentCore CLI (`npm install -g @aws/agentcore`)
# plus local start/stop/test shortcuts. agentcore/agentcore.json declares the
# Runtime. `deploy` loads the Neo4j settings from the shared ../.env and
# agentcore/cdk/lib/cdk-stack.ts passes them to the Runtime. Passwords never
# reach the stack: the Runtime reads them from Secrets Manager through the
# *_SECRET_ARN vars.
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
#   ./agent.sh destroy [--yes]    Remove from AgentCore (asks first)
#
# Prerequisites:
#   - Local runs: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD in the shared
#     ../.env at the aircraft-fleet root
#   - Deploy: the AgentCore CLI on PATH, and the DEPLOY_VARS below set in
#     ../.env or the shell
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
    echo "  ./agent.sh destroy [--yes]    Remove from AgentCore (asks first)"
    echo "  ./agent.sh help               Show this help message"
}

# Must match the Runtime name in agentcore/agentcore.json and
# RUNTIME_NAME / DEPLOY_TARGET in client/transport.py.
RUNTIME_NAME="graphrag_agent"
TARGET="default"
PROJECT_SPEC="agentcore/agentcore.json"
# The first deploy records each target's account and region here. Git ignores it.
TARGETS_FILE="agentcore/aws-targets.json"

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
# .venv, .git, node_modules, __pycache__, and .pytest_cache. It ships
# .ruff_cache, so the scan covers it. Refuse to deploy while a
# secrets file is present anywhere it would be packaged. -L follows symlinks,
# so a link to a secrets file is caught too. A find error stops the deploy
# instead of passing the check.
refuse_secret_files() {
    local found
    if ! found=$(find -L . \
        \( -path ./agentcore -o -name .venv -o -name .git -o -name node_modules \
           -o -name __pycache__ -o -name .pytest_cache \) -prune \
        -o \( -name '.env*' -o -name '.mcp-credentials*.json' \) -print); then
        echo -e "${RED}ERROR: could not scan $(pwd) for secrets files${NC}"
        echo "Fix the find error above, then deploy again."
        exit 1
    fi
    if [ -n "$found" ]; then
        echo -e "${RED}ERROR: secrets files would be packaged into the deployment:${NC}"
        echo "$found"
        echo ""
        echo "Move them out of $(pwd) before deploying."
        echo "Local runs read the shared ../.env at the aircraft-fleet root."
        exit 1
    fi
}

# Ask before destroying. Anything but y or yes, including no input from a
# non-interactive shell, cancels. `destroy --yes` skips the question.
confirm_destroy() {
    local reply=""
    echo -e "${YELLOW}This deletes the $RUNTIME_NAME Runtime and its stack in target '$TARGET'.${NC}"
    read -r -p "Continue? [y/N] " reply || true
    case "$reply" in
        y|Y|yes|YES) ;;
        *)
            echo "Cancelled. Nothing was changed."
            exit 1
            ;;
    esac
}

# Put the project spec back after destroy. A failure returns 1, so destroy
# stops before it reports status from the wrong spec.
restore_spec() {
    if ! cp "$SPEC_BACKUP" "$PROJECT_SPEC"; then
        echo -e "${RED}Could not restore $PROJECT_SPEC. The backup is at $SPEC_BACKUP${NC}" >&2
        return 1
    fi
    rm -f "$SPEC_BACKUP"
}

# Report every resource that `agentcore status` still shows as deployed.
# The CloudFormation stack the CLI deploys for $TARGET. @aws/agentcore-cdk
# 1.1.0 (resolveTargetStacks) names it AgentCore-<project>-<target>, with each
# underscore replaced by a dash.
stack_name() {
    uv run --quiet python -c '
import json
import sys
from pathlib import Path

name = json.loads(Path(sys.argv[1]).read_text())["name"]
print(f"AgentCore-{name}-{sys.argv[2]}".replace("_", "-"))
' "$PROJECT_SPEC" "$TARGET"
}

require_aws() {
    if ! command -v aws >/dev/null 2>&1; then
        echo "The aws CLI is not installed." >&2
        return 1
    fi
}

# Print the account and the region that $TARGET deploys to, or fail.
target_entry() {
    uv run --quiet python -c '
import json
import sys
from pathlib import Path

try:
    targets = json.loads(Path(sys.argv[1]).read_text())
    entries = [(t["account"], t["region"]) for t in targets if t.get("name") == sys.argv[2]]
except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
    sys.exit(f"{sys.argv[1]}: {error}")
if len(entries) != 1:
    sys.exit(f"{sys.argv[1]} has {len(entries)} entries for this target.")
print(*entries[0])
' "$TARGETS_FILE" "$TARGET"
}

# Print the account of the active AWS credentials, or fail.
caller_account() {
    require_aws || return 1
    aws sts get-caller-identity --query Account --output text --region "$1"
}

# Exit unless the active AWS credentials belong to the account of $TARGET.
# Credentials for another account would deploy there and read the stack as
# absent. $1 is the region for the STS call, by default the target's region.
require_target_account() {
    local entry account target_region caller
    if ! entry=$(target_entry); then
        echo -e "${RED}Could not read the account for target '$TARGET' from $TARGETS_FILE.${NC}"
        exit 1
    fi
    read -r account target_region <<<"$entry"
    if ! caller=$(caller_account "${1:-$target_region}"); then
        echo -e "${RED}Could not check the active AWS account with STS.${NC}"
        exit 1
    fi
    if [ "$caller" != "$account" ]; then
        echo -e "${RED}The active AWS credentials belong to account $caller, but target '$TARGET' is in account $account.${NC}"
        echo "Use credentials for account $account, for example with AWS_PROFILE, and run destroy again."
        exit 1
    fi
}

# Print the stack status, "absent" when the stack does not exist, or fail.
# stderr goes to its own file in $REPORT_TMP, so a CLI warning cannot be read
# as the status.
stack_status() {
    local stack="$1" region="$2" output err_file="$REPORT_TMP/describe-stacks.err" err
    require_aws || return 1
    if output=$(aws cloudformation describe-stacks --stack-name "$stack" --region "$region" \
            --query 'Stacks[0].StackStatus' --output text 2>"$err_file"); then
        cat "$err_file" >&2
        echo "$output"
        return 0
    fi
    err=$(cat "$err_file")
    if [[ "$err" == *"does not exist"* ]]; then
        echo "absent"
    else
        echo "$err" >&2
        return 1
    fi
}

report_remaining() {
    local status parsed region remaining status_err parse_err stack cfn_status
    # The stderr files below go in one folder that the EXIT trap removes, so
    # Ctrl+C leaves nothing behind. stack_status writes there from its
    # command substitution, which does not run this shell's traps. destroy
    # has cleared its own EXIT trap before this point.
    if ! REPORT_TMP=$(mktemp -d); then
        echo -e "${RED}Could not create a temp folder for the status check.${NC}"
        exit 1
    fi
    trap 'rm -rf "$REPORT_TMP"' EXIT
    status_err="$REPORT_TMP/status.err"
    parse_err="$REPORT_TMP/parse.err"
    # stderr goes to its own file, so a CLI banner or warning cannot break
    # the JSON. It is printed only when the call fails.
    if ! status=$(agentcore status --json --target "$TARGET" 2>"$status_err"); then
        echo -e "${RED}Could not check what remains deployed:${NC}"
        cat "$status_err"
        echo "$status"
        exit 1
    fi
    # The first line is the target region. Each later line is a resource that
    # status does not report as local-only. stderr goes to its own file, so a
    # uv warning cannot be read as the region.
    if ! parsed=$(printf '%s' "$status" | uv run --quiet python -c '
import json
import sys


def walk(resources):
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        state = resource.get("deploymentState")
        if state != "local-only":
            kind, name = resource.get("resourceType"), resource.get("name")
            print(f"  {kind} {name}: {state}")
        walk(resource.get("children") or [])


status = json.load(sys.stdin)
region = status.get("region")
resources = status.get("resources")
if not isinstance(region, str) or not region or not isinstance(resources, list):
    sys.exit("The status output has no region or no resources list.")
print(region)
walk(resources)
' 2>"$parse_err"); then
        echo -e "${RED}Could not read the agentcore status output:${NC}"
        cat "$parse_err"
        echo "$status"
        exit 1
    fi
    cat "$parse_err" >&2
    region=$(head -n 1 <<<"$parsed")
    remaining=$(tail -n +2 <<<"$parsed")
    # agentcore status reads agentcore/.cli/deployed-state.json. If that file
    # is lost, every resource reads local-only while the stack still exists,
    # so ask CloudFormation directly.
    if ! stack=$(stack_name); then
        echo -e "${RED}Could not read the project name from $PROJECT_SPEC.${NC}"
        exit 1
    fi
    # The stack check uses the active credentials. destroy checked the
    # account before deploy, but the credentials can change since then
    # (an expiring session, a profile switch), so check again.
    require_target_account "$region"
    if ! cfn_status=$(stack_status "$stack" "$region"); then
        echo -e "${RED}Could not check stack $stack in $region with CloudFormation.${NC}"
        exit 1
    fi
    if [ "$cfn_status" != "absent" ] && [ "$cfn_status" != "DELETE_COMPLETE" ]; then
        remaining="${remaining:+$remaining
}  stack $stack: $cfn_status"
    fi
    if [ -n "$remaining" ]; then
        echo -e "${RED}Still deployed in target '$TARGET':${NC}"
        echo "$remaining"
        exit 1
    fi
    echo -e "${GREEN}Cleanup complete. Stack $stack does not exist in $region.${NC}"
}

# The settings agentcore/cdk/lib/cdk-stack.ts copies into the Runtime
# environment. Synth fails and names any that are missing.
DEPLOY_VARS=(
    NEO4J_URI NEO4J_USERNAME NEO4J_DATABASE NEO4J_PASSWORD_SECRET_ARN
    MEM_NEO4J_URI MEM_NEO4J_USERNAME MEM_NEO4J_DATABASE MEM_NEO4J_PASSWORD_SECRET_ARN
)
SHARED_ENV="$ROOT_DIR/../.env"

# Export DEPLOY_VARS from the shared .env, which sits outside the code zip.
# A value exported in the shell wins over the file. The file is parsed, not sourced, and
# only these names are exported, so passwords in it stay out of the CDK
# process.
load_deploy_env() {
    ensure_deps
    if [ ! -f "$SHARED_ENV" ]; then
        echo -e "${RED}ERROR: $SHARED_ENV not found${NC}"
        echo "Copy ../.env.sample to ../.env and set the deploy settings."
        exit 1
    fi
    local exports
    exports=$(uv run --quiet python - "$SHARED_ENV" "${DEPLOY_VARS[@]}" <<'PY'
import os
import shlex
import sys

from dotenv import dotenv_values

values = dotenv_values(sys.argv[1])
for name in sys.argv[2:]:
    value = values.get(name)
    if not os.environ.get(name) and value:
        print(f"export {name}={shlex.quote(value)}")
PY
)
    eval "$exports"
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
        load_deploy_env
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
        # Check the account before anything changes, so credentials for
        # another account cannot deploy the empty project there.
        require_target_account
        if [ "${2:-}" != "--yes" ]; then
            confirm_destroy
        fi
        # CLI 1.1.0 has no destroy command. A deploy of a project that
        # declares nothing removes the target's stack, so remove the Runtime
        # from the spec, deploy, and put the spec back.
        echo -e "${YELLOW}Removing agent from AgentCore Runtime...${NC}"
        echo ""
        # With the Runtime removed, synth skips the Neo4j settings, so destroy
        # does not need ../.env.
        SPEC_BACKUP=$(mktemp)
        cp "$PROJECT_SPEC" "$SPEC_BACKUP"
        trap restore_spec EXIT
        agentcore remove runtime --name "$RUNTIME_NAME"
        agentcore deploy --target "$TARGET" --yes
        # Status lists only what the spec declares, so restore it first.
        trap - EXIT
        restore_spec || exit 1
        echo ""
        report_remaining
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
