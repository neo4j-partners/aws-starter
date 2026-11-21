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
#   ./agent.sh destroy [--yes]    Remove from AgentCore (asks first)
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
# Deployment-specific settings are not written here. See DEPLOY_VARS below.
RUNTIME_ENV='{"MODEL_ID":"global.anthropic.claude-sonnet-5-5"}'
PROJECT_SPEC="agentcore/agentcore.json"
TARGET="default"
# The AgentCore Identity OAuth2 credential that holds the Gateway client
# secret. deploy and destroy declare it for the one CLI run, then restore the
# tracked agentcore.json. The construct then sets CREDENTIAL_FLEET_GATEWAY_NAME
# on the Runtime, which selects the cloud auth path in credentials.py.
GATEWAY_CREDENTIAL="fleet-gateway"
# `agentcore add credentials` writes the client secret, encrypted with a key
# in ~/.agentcore or the keychain, to this variable in agentcore/.env.local.
GATEWAY_SECRET_VAR="AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET"
ENV_LOCAL="agentcore/.env.local"
# The stack and the credential provider names the CLI derives, so destroy
# can check AWS for them directly. From resolveTargetStacks in
# @aws/agentcore-cdk 1.1.0 (underscores become hyphens) and providerName in
# @aws/agentcore 1.1.0.
STACK_NAME="AgentCore-${PROJECT_NAME//_/-}-${TARGET//_/-}"
GATEWAY_PROVIDER="${PROJECT_NAME}_${TARGET}_${GATEWAY_CREDENTIAL}"
# Local Gateway credentials, written by neo4j-mcp-server/deploy.py.
CREDENTIALS_FILE="${MCP_CREDENTIALS_FILE:-$ROOT_DIR/../.mcp-credentials.json}"
# AgentCore deployment region. AgentCore's primary region is us-east-1
# (also supported in us-west-2). Set AWS_REGION to override. The CLI creates
# the default deploy target from this region on the first deploy.
REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION="$REGION"
# The settings agentcore/cdk/lib/cdk-stack.ts copies into the Runtime
# environment. Synth fails and names any that are missing or malformed.
# GATEWAY_URL and GATEWAY_SCOPES come from gateway_url and scope in the
# credentials file. The MEM_NEO4J_* settings come from the shared ../.env.
DEPLOY_VARS=(
    GATEWAY_URL GATEWAY_SCOPES
    MEM_NEO4J_URI MEM_NEO4J_USERNAME MEM_NEO4J_DATABASE MEM_NEO4J_PASSWORD_SECRET_ARN
)
SHARED_ENV="$ROOT_DIR/../.env"
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
    echo "  ./agent.sh destroy [--yes]    Remove from AgentCore (asks first)"
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

# The code zip has no ignore file, so any secrets file in this folder would
# be uploaded with the code: .env*, .mcp-credentials*.json, .agentcore.json,
# credentials*.json, or *.pem. .venv is not zipped, but a venv/ folder
# without the dot is, so it is refused too. agentcore/ holds the CLI's own
# .env.local, which is not zipped. -L follows symlinks, so a link to a
# secrets file is caught. A find error stops the deploy instead of passing
# the check.
ensure_no_secrets_in_zip() {
    local found
    if ! found="$(find -L . \( -path ./.venv -o -path ./agentcore \) -prune \
        -o -type d -name venv -prune -print \
        -o -type f \( -name '.env*' -o -name '.mcp-credentials*.json' \
            -o -name '.agentcore.json' -o -name 'credentials*.json' -o -name '*.pem' \) \
        -print)"; then
        echo -e "${RED}ERROR: could not scan $ROOT_DIR for secret files${NC}"
        echo "Fix the find error above, then deploy again."
        exit 1
    fi
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
    CREATE_TMP="$(mktemp -d)"
    # A failed step exits through this trap, so the temporary project and a
    # partial spec do not stay behind.
    trap 'rm -rf "${CREATE_TMP:?}"; rm -f "$PROJECT_SPEC.tmp"' EXIT
    (cd "$CREATE_TMP" && agentcore create --name "$PROJECT_NAME" --skip-install --skip-git)
    # add runtime runs inside the temporary project, because it writes starter
    # docs to app/<name>/ next to agentcore/. The code lives here instead, so
    # only the temporary app/ is removed.
    (cd "$CREATE_TMP/$PROJECT_NAME" && agentcore add runtime \
        --name "$RUNTIME_NAME" \
        --language python \
        --description "Aircraft fleet supervisor with Maintenance and Operations specialists" \
        --environment-variables "$RUNTIME_ENV")
    rm -rf "${CREATE_TMP:?}/$PROJECT_NAME/app"
    mv "$CREATE_TMP/$PROJECT_NAME/agentcore" agentcore

    jq --arg name "$RUNTIME_NAME" --arg entry "$ENTRYPOINT" --arg ver "$RUNTIME_VERSION" \
        '(.runtimes[] | select(.name == $name)) |= (.codeLocation = "." | .entrypoint = $entry | .runtimeVersion = $ver)' \
        "$PROJECT_SPEC" > "$PROJECT_SPEC.tmp"
    mv "$PROJECT_SPEC.tmp" "$PROJECT_SPEC"
    trap - EXIT
    rm -rf "${CREATE_TMP:?}"
}

# The runtime gets its Gateway token from the fleet-gateway OAuth provider.
# The AgentCore CLI creates or updates that provider from the credentials
# entry in agentcore.json before CDK runs, and the construct grants the
# runtime access to it only while the entry exists. A deploy without the entry
# deletes the provider, so the entry is added for every deploy. destroy does
# not add it: see the destroy command. The tracked agentcore.json never holds
# it, so it carries no account details.
#
# The client ID and scope come from the fleet credentials file, and the
# discovery URL from the MCP server stack. The secret goes to the CLI on
# stdin, never in argv, and the CLI stores it in agentcore/.env.local. The
# EXIT trap removes that line and restores the tracked agentcore.json.
add_gateway_credential() {
    ensure_credentials
    if jq -e --arg name "$GATEWAY_CREDENTIAL" \
        '.credentials // [] | any(.name == $name)' "$PROJECT_SPEC" >/dev/null; then
        echo -e "${RED}ERROR: $PROJECT_SPEC already declares the $GATEWAY_CREDENTIAL credential${NC}"
        echo "An earlier run did not restore it. Restore the tracked spec, then run this again:"
        echo "  git checkout -- $PROJECT_SPEC"
        exit 1
    fi
    local client_id scope stack_name discovery_url
    client_id=$(jq -r '.client_id // empty' "$CREDENTIALS_FILE")
    scope=$(jq -r '.scope // empty' "$CREDENTIALS_FILE")
    stack_name=$(jq -r '.stack_name // empty' "$CREDENTIALS_FILE")
    if [ -z "$client_id" ] || [ -z "$scope" ] || [ -z "$stack_name" ] \
        || ! jq -e '.client_secret | type == "string" and length > 0' "$CREDENTIALS_FILE" >/dev/null; then
        echo -e "${RED}ERROR: $CREDENTIALS_FILE needs client_id, client_secret, scope, and stack_name${NC}"
        echo "Regenerate it with: cd neo4j-mcp-server && ./deploy.py --env fleet credentials"
        exit 1
    fi
    discovery_url=$(aws cloudformation describe-stacks --region "$REGION" \
        --stack-name "$stack_name" \
        --query "Stacks[0].Outputs[?OutputKey=='CognitoDiscoveryUrl'].OutputValue" \
        --output text)
    if [[ "$discovery_url" != https://* ]]; then
        echo -e "${RED}ERROR: stack $stack_name has no CognitoDiscoveryUrl output in $REGION${NC}"
        exit 1
    fi
    # Drop a line a killed run may have left, so the CLI writes a fresh one.
    strip_gateway_secret
    jq -r '.client_secret' "$CREDENTIALS_FILE" | agentcore add credentials oauth \
        --name "$GATEWAY_CREDENTIAL" \
        --client-id "$client_id" \
        --discovery-url "$discovery_url" \
        --scopes "$scope" \
        --client-secret -
}

# The copy strip_gateway_secret writes before it replaces .env.local. It
# holds the file's other lines. restore_project, which the EXIT trap runs,
# removes a copy an interrupt left behind.
ENV_STRIP_TMP=""

# Remove the client secret line, and the comment the CLI writes above it,
# from agentcore/.env.local. Every other line is kept. The secret line must
# start with the exact variable name, and the comment must match the whole
# line.
strip_gateway_secret() {
    [ -f "$ENV_LOCAL" ] || return 0
    local comment="# OAuth client secret for credential provider '$GATEWAY_CREDENTIAL' (set before deploy)"
    # The copy sits next to the file, so mv replaces the file in one step.
    # cp -p gives the copy the file's mode before the filtered lines go in.
    if ! ENV_STRIP_TMP=$(mktemp "$ENV_LOCAL.XXXXXX") \
        || ! cp -p "$ENV_LOCAL" "$ENV_STRIP_TMP" \
        || ! awk -v prefix="$GATEWAY_SECRET_VAR=" -v comment="$comment" \
            'index($0, prefix) != 1 && $0 != comment' "$ENV_LOCAL" > "$ENV_STRIP_TMP" \
        || ! mv -f "$ENV_STRIP_TMP" "$ENV_LOCAL"; then
        remove_strip_copy
        echo -e "${RED}Could not remove $GATEWAY_SECRET_VAR from $ENV_LOCAL. Delete that line by hand.${NC}" >&2
        return 1
    fi
    ENV_STRIP_TMP=""
}

# Clear the name before removing the file, as restore_project does for the
# spec backup, so a second run never acts on a stale name.
remove_strip_copy() {
    if [ -n "$ENV_STRIP_TMP" ]; then
        local copy="$ENV_STRIP_TMP"
        ENV_STRIP_TMP=""
        rm -f "$copy"
    fi
}

# Put back the tracked agentcore.json and remove the secret line. Returns
# nonzero if either step fails, and says what to do by hand.
restore_project() {
    local failed=0
    remove_strip_copy
    if [ -n "${SPEC_BACKUP:-}" ]; then
        if cp "$SPEC_BACKUP" "$PROJECT_SPEC"; then
            # Clear the name before removing the file. A second run, from the
            # EXIT trap after an interrupt, then skips the restore instead of
            # copying from a file that is already gone.
            local backup="$SPEC_BACKUP"
            SPEC_BACKUP=""
            rm -f "$backup"
        else
            echo -e "${RED}Could not restore $PROJECT_SPEC. The backup is at $SPEC_BACKUP${NC}" >&2
            failed=1
        fi
    fi
    strip_gateway_secret || failed=1
    return "$failed"
}

# Back up the tracked spec and arm the restore. INT and TERM exit through
# the EXIT trap, so Ctrl+C restores too. The EXIT trap ignores INT and TERM
# first, so a second Ctrl+C cannot stop the restore halfway.
begin_spec_restore() {
    SPEC_BACKUP=$(mktemp)
    # The trap is not armed yet, so a failed copy removes the backup here.
    if ! cp "$PROJECT_SPEC" "$SPEC_BACKUP"; then
        rm -f "$SPEC_BACKUP"
        exit 1
    fi
    trap "trap '' INT TERM; restore_project || exit 1" EXIT
    trap 'exit 130' INT TERM
}

# Restore while the traps are still armed, so an interrupt during the
# restore still finishes it through the EXIT trap. Then clear them.
end_spec_restore() {
    local status=0
    restore_project || status=$?
    trap - EXIT INT TERM
    return "$status"
}

# Ask before destroying. Anything but y or yes, including no input from a
# non-interactive shell, cancels. `destroy --yes` skips the question.
confirm_destroy() {
    local reply=""
    echo -e "${YELLOW}This deletes the $RUNTIME_NAME Runtime, the $GATEWAY_CREDENTIAL credential provider, and the stack in target '$TARGET'.${NC}"
    read -r -p "Continue? [y/N] " reply || true
    case "$reply" in
        y|Y|yes|YES) ;;
        *)
            echo "Cancelled. Nothing was changed."
            exit 1
            ;;
    esac
}

# The deploy target's region from agentcore/aws-targets.json. Before the
# first deploy writes the target, it is REGION.
target_region() {
    local region=""
    if [ -f agentcore/aws-targets.json ]; then
        region=$(jq -r --arg t "$TARGET" \
            '.[]? | select(.name == $t) | .region // empty' agentcore/aws-targets.json)
    fi
    echo "${region:-$REGION}"
}

# Run a read-only AWS lookup and keep its output in AWS_LOOKUP_OUTPUT.
# Returns 0 if the resource exists and 1 if the error text contains
# not_found. Any other failure exits, so an expired login or a missing
# permission never reads as deleted. Call it directly, not in $(...), so
# that exit stops the script.
aws_lookup() {
    local not_found="$1" output errors status=0
    shift
    output=$(mktemp)
    errors=$(mktemp)
    "$@" >"$output" 2>"$errors" || status=$?
    AWS_LOOKUP_OUTPUT=$(cat "$output")
    rm -f "$output"
    if [ "$status" -eq 0 ]; then
        rm -f "$errors"
        return 0
    fi
    if grep -q -F -- "$not_found" "$errors"; then
        rm -f "$errors"
        return 1
    fi
    echo -e "${RED}Could not check AWS for remaining resources:${NC}"
    cat "$errors"
    rm -f "$errors"
    exit 1
}

# Report everything destroy may have left. `agentcore status` reads the
# CLI's deployed-state.json, so a lost state file would read as clean. The
# stack and the credential provider are also looked up in AWS by name.
report_remaining() {
    local status errors remaining region
    errors=$(mktemp)
    if ! status=$(agentcore status --json --target "$TARGET" 2>"$errors"); then
        echo -e "${RED}Could not check what remains deployed:${NC}"
        cat "$errors"
        echo "$status"
        rm -f "$errors"
        exit 1
    fi
    rm -f "$errors"
    if ! remaining=$(printf '%s' "$status" | jq -r '
        def remaining: .[]? | objects
            | (select(.deploymentState != "local-only")
               | "  \(.resourceType) \(.name): \(.deploymentState)"),
              (.children | remaining);
        if (.resources | type) == "array" then .resources | remaining
        else error("no resources array") end'); then
        echo -e "${RED}Could not read the agentcore status output:${NC}"
        echo "$status"
        exit 1
    fi
    region=$(target_region)
    if aws_lookup "does not exist" aws cloudformation describe-stacks \
        --region "$region" --stack-name "$STACK_NAME" \
        --query 'Stacks[0].StackStatus' --output text; then
        remaining+="${remaining:+$'\n'}  stack $STACK_NAME: $AWS_LOOKUP_OUTPUT"
        remaining+=$'\n'"    Delete it with: aws cloudformation delete-stack --region $region --stack-name $STACK_NAME"
    fi
    if aws_lookup "ResourceNotFoundException" aws bedrock-agentcore-control \
        get-oauth2-credential-provider --region "$region" --name "$GATEWAY_PROVIDER"; then
        remaining+="${remaining:+$'\n'}  credential provider $GATEWAY_PROVIDER"
        remaining+=$'\n'"    Delete it with: aws bedrock-agentcore-control delete-oauth2-credential-provider --region $region --name $GATEWAY_PROVIDER"
    fi
    if [ -n "$remaining" ]; then
        echo -e "${RED}Still deployed in target '$TARGET':${NC}"
        echo "$remaining"
        exit 1
    fi
    echo -e "${GREEN}Cleanup complete. Nothing is deployed in target '$TARGET'.${NC}"
}

# Export DEPLOY_VARS from ../.env and the credentials file, which both sit
# outside the code zip. A value exported in the shell wins. The files are
# parsed, not sourced, and only these names are exported, so the passwords
# and the client secret in them stay out of the CDK process.
load_deploy_env() {
    ensure_deps
    ensure_credentials
    if [ ! -f "$SHARED_ENV" ]; then
        echo -e "${RED}ERROR: $SHARED_ENV not found${NC}"
        echo "Copy ../.env.sample to ../.env and set the deploy settings."
        exit 1
    fi
    local exports
    exports=$(uv run --quiet python - "$SHARED_ENV" "$CREDENTIALS_FILE" "${DEPLOY_VARS[@]}" <<'PY'
import json
import os
import shlex
import sys
from pathlib import Path

from dotenv import dotenv_values

env_file, credentials_file, *names = sys.argv[1:]
values = dotenv_values(env_file)
credentials = json.loads(Path(credentials_file).read_text(encoding="utf-8"))
values["GATEWAY_URL"] = credentials.get("gateway_url")
values["GATEWAY_SCOPES"] = credentials.get("scope")
for name in names:
    value = values.get(name)
    if not os.environ.get(name) and value:
        print(f"export {name}={shlex.quote(value)}")
PY
)
    eval "$exports"
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
        echo "Set the deploy settings in ../.env, then run './agent.sh deploy'"
        ;;

    deploy)
        ensure_project
        ensure_no_secrets_in_zip
        load_deploy_env
        begin_spec_restore
        add_gateway_credential
        echo -e "${GREEN}Deploying Aircraft Fleet Supervisor Agent to AgentCore Runtime...${NC}"
        echo "This may take several minutes..."
        echo ""
        agentcore deploy "${@:2}"
        end_spec_restore
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
        # %s prints the prompt as is, so a backslash in it is not an escape.
        printf '%bPrompt: %s%b\n' "$BLUE" "$PROMPT" "$NC"
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
        if [ "${2:-}" != "--yes" ]; then
            confirm_destroy
        fi
        echo -e "${YELLOW}Removing supervisor from AgentCore Runtime...${NC}"
        echo ""
        # The CLI has no destroy command. A deploy of a project that declares
        # nothing deployable removes the target's stack. The same deploy
        # deletes every credential provider that deployed-state.json records
        # and the spec no longer declares, so the fleet-gateway provider goes
        # without being declared. So remove the Runtime from the spec and
        # deploy. With no Runtime, the stack reads no deploy settings, so
        # destroy needs neither the credentials file nor the MCP server stack.
        begin_spec_restore
        agentcore remove runtime --name "$RUNTIME_NAME"
        agentcore deploy --target "$TARGET" --yes
        end_spec_restore
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
