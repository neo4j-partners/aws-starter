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
# fleet_supervisor/ package next to main.py. The shared .env sits one level
# up, in demos/aircraft-fleet/, outside the code zip.
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
CDK_DIR="agentcore/cdk"
TARGET="default"
# The deploy targets. The first deploy writes this file, and git ignores it.
TARGETS_FILE="agentcore/aws-targets.json"
# AgentCore writes each Runtime's logs to <prefix><runtime-id>-<endpoint>.
RUNTIME_LOG_PREFIX="/aws/bedrock-agentcore/runtimes/"
# The stack name the CLI derives, so destroy can check AWS for it directly.
# From resolveTargetStacks in @aws/agentcore-cdk 1.2.0, where underscores
# become hyphens.
STACK_NAME="AgentCore-${PROJECT_NAME//_/-}-${TARGET//_/-}"
# AgentCore deployment region. AgentCore's primary region is us-east-1
# (also supported in us-west-2). Set AWS_REGION to override. The CLI creates
# the default deploy target from this region on the first deploy.
REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION="$REGION"
# The settings agentcore/cdk/lib/cdk-stack.ts copies into the Runtime
# environment. Synth fails and names any that are missing or malformed.
# All of them come from the shared ../.env. The NEO4J_* settings name the
# fleet graph, and the MEM_NEO4J_* settings name the memory database.
DEPLOY_VARS=(
    NEO4J_URI NEO4J_USERNAME NEO4J_DATABASE NEO4J_PASSWORD_SECRET_ARN
    MEM_NEO4J_URI MEM_NEO4J_USERNAME MEM_NEO4J_DATABASE MEM_NEO4J_PASSWORD_SECRET_ARN
)
SHARED_ENV="$ROOT_DIR/../.env"
# Local server port. AgentCore Runtime uses 8080.
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

# agentcore deploy refuses to run without agentcore/cdk/node_modules, and
# git ignores that folder, so a fresh clone has none. Install it from the
# tracked package-lock.json before deploy or destroy. npm writes
# node_modules/.package-lock.json only after a complete install, so a
# partial install from a failed npm ci is installed again. A package-lock.json
# newer than that file, as after a pull that changes it, is installed again
# too, so deploy does not run on the old CDK libraries.
ensure_cdk_deps() {
    if [ -f "$CDK_DIR/node_modules/.package-lock.json" ] \
        && ! [ "$CDK_DIR/package-lock.json" -nt "$CDK_DIR/node_modules/.package-lock.json" ]; then
        return
    fi
    local install
    install=$(cdk_install_command)
    if ! command -v npm >/dev/null 2>&1; then
        echo -e "${RED}ERROR: npm is not installed, so the CDK dependencies cannot be installed${NC}"
        echo "Install Node.js, then run: (cd $CDK_DIR && $install)"
        exit 1
    fi
    echo -e "${YELLOW}Installing the CDK dependencies...${NC}"
    # $install is two words, npm and its command, so it is left unquoted.
    if ! (cd "$CDK_DIR" && $install); then
        echo -e "${RED}ERROR: $install failed in $CDK_DIR${NC}"
        echo "Fix the error above, then run: (cd $CDK_DIR && $install)"
        exit 1
    fi
    echo ""
}

# Print the npm command that installs the CDK dependencies. npm ci installs
# exactly what package-lock.json lists and never rewrites it, but it refuses
# to run without one. agentcore create --skip-install leaves agentcore/cdk
# with no package-lock.json, so npm install writes it there.
cdk_install_command() {
    if [ -f "$CDK_DIR/package-lock.json" ]; then
        echo "npm ci"
    else
        echo "npm install"
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
        echo "The deploy settings belong in demos/aircraft-fleet/.env."
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
    CREATE_TMP=$(make_temp -d) || exit 1
    # A failed step exits through this trap, so a partial spec does not stay
    # behind. on_exit removes the temporary project with TMP_ROOT.
    trap 'rm -f "$PROJECT_SPEC.tmp"; on_exit' EXIT
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
    trap on_exit EXIT
    rm -rf "${CREATE_TMP:?}"
}

# Temporary files go in one folder per run, which on_exit removes, so Ctrl+C
# leaves none behind. The name is fixed before the folder exists, so a file
# whose name an interrupt lost inside $(make_temp) is removed with it.
TMP_ROOT="${TMPDIR:-/tmp}"
TMP_ROOT="${TMP_ROOT%/}/fleet-supervisor.$$"

# Print the name of a new temporary file in TMP_ROOT, or a folder with -d.
# A TMP_ROOT that already exists is used only if this user owns it and it is
# not a link.
make_temp() {
    if ! mkdir -m 700 "$TMP_ROOT" 2>/dev/null; then
        if [ -L "$TMP_ROOT" ] || [ ! -d "$TMP_ROOT" ] || [ ! -O "$TMP_ROOT" ]; then
            echo -e "${RED}Cannot use $TMP_ROOT for temporary files.${NC}" >&2
            return 1
        fi
    fi
    mktemp "$@" "$TMP_ROOT/tmp.XXXXXX"
}

# Set when the spec backup in TMP_ROOT could not be copied back, so on_exit
# keeps the folder that the error message points to.
KEEP_TMP_ROOT=""

# Set while a deploy or destroy has the tracked spec changed.
RESTORE_ARMED=""

# The signal that stopped the run while the restore was armed, which on_exit
# raises again.
STOP_SIGNAL=""

# The EXIT trap for the whole run, Ctrl+C included. It ignores INT, TERM,
# and HUP first, so a second Ctrl+C, a kill, or a closed terminal cannot
# stop the restore halfway. A failed restore exits 1. Otherwise, if one of
# those signals stopped the run, the script dies by that same signal, so a
# calling shell loop sees a signal death and stops too. A failed restore
# exits 1 even after a signal. A signal death says only that the run was
# stopped, and a caller would take the checkout as clean. Exit 1 goes with
# the error that names the file left to fix.
on_exit() {
    local failed=0
    trap '' INT TERM HUP
    if [ -n "$RESTORE_ARMED" ]; then
        restore_project || failed=1
    fi
    if [ -z "$KEEP_TMP_ROOT" ] && [ -d "$TMP_ROOT" ] && [ ! -L "$TMP_ROOT" ] && [ -O "$TMP_ROOT" ]; then
        rm -rf "${TMP_ROOT:?}"
    fi
    if [ "$failed" -ne 0 ]; then
        exit 1
    fi
    if [ -n "$STOP_SIGNAL" ]; then
        trap - "$STOP_SIGNAL"
        kill -s "$STOP_SIGNAL" "$$"
    fi
}

# Put back the tracked agentcore.json. Returns nonzero if the copy fails,
# and says where the backup is.
restore_project() {
    local failed=0
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
            KEEP_TMP_ROOT=1
            failed=1
        fi
    fi
    return "$failed"
}

# Back up the tracked spec and arm the restore. INT, TERM, and HUP exit
# through on_exit, so Ctrl+C, a kill, and a closed terminal restore too.
# Each records its signal for on_exit and exits with 128 plus the signal
# number, the status left if the signal cannot be raised again. The
# restore is not armed yet when the backup fails, and on_exit removes a
# partial backup with TMP_ROOT.
begin_spec_restore() {
    if ! SPEC_BACKUP=$(make_temp) || ! cp "$PROJECT_SPEC" "$SPEC_BACKUP"; then
        exit 1
    fi
    RESTORE_ARMED=1
    trap 'STOP_SIGNAL=INT; exit 130' INT
    trap 'STOP_SIGNAL=TERM; exit 143' TERM
    trap 'STOP_SIGNAL=HUP; exit 129' HUP
}

# Restore while the restore is still armed, so an interrupt during it still
# finishes it through on_exit. Then disarm it.
end_spec_restore() {
    local status=0
    restore_project || status=$?
    RESTORE_ARMED=""
    trap - INT TERM HUP
    return "$status"
}

# Ask before destroying. Anything but y or yes, including no input from a
# non-interactive shell, cancels. `destroy --yes` skips the question.
confirm_destroy() {
    local reply=""
    echo -e "${YELLOW}This deletes the $RUNTIME_NAME Runtime and the stack in target '$TARGET'.${NC}"
    read -r -p "Continue? [y/N] " reply || true
    case "$reply" in
        y|Y|yes|YES) ;;
        *)
            echo "Cancelled. Nothing was changed."
            exit 1
            ;;
    esac
}

# The deploy target's region from $TARGETS_FILE. Before the first deploy
# writes the target, it is REGION.
target_region() {
    local region=""
    if [ -f "$TARGETS_FILE" ]; then
        region=$(jq -r --arg t "$TARGET" \
            '.[]? | select(.name == $t) | .region // empty' "$TARGETS_FILE")
    fi
    echo "${region:-$REGION}"
}

# The account that $TARGET deploys to, from $TARGETS_FILE, where the first
# deploy records it. Fails unless there is exactly one, and it is a string
# of 12 digits.
target_account() {
    jq -r -e --arg t "$TARGET" '
        [.[] | select(.name == $t) | .account]
        | if length == 1 and (.[0] | type == "string" and test("^[0-9]{12}$")) then .[0]
          else error("no single 12-digit account for the target") end' \
        "$TARGETS_FILE" 2>/dev/null
}

# Exit unless the active AWS credentials belong to the account of $TARGET.
# Credentials for another account would deploy there and read the stack and
# provider as gone. $1 is the region for the STS call, by default the
# target's region.
require_target_account() {
    local account caller
    # The first deploy writes this file, and git ignores it, so a fresh
    # checkout has none.
    if [ ! -e "$TARGETS_FILE" ]; then
        echo -e "${RED}No deployment is recorded in this checkout: $TARGETS_FILE is missing. Run destroy from the checkout that deployed.${NC}"
        exit 1
    fi
    if ! account=$(target_account); then
        echo -e "${RED}Could not read the account for target '$TARGET' from $TARGETS_FILE.${NC}"
        exit 1
    fi
    if ! caller=$(aws sts get-caller-identity --query Account --output text --region "${1:-$(target_region)}"); then
        echo -e "${RED}Could not check the active AWS account with STS.${NC}"
        exit 1
    fi
    if [ "$caller" != "$account" ]; then
        echo -e "${RED}The active AWS credentials belong to account $caller, but target '$TARGET' is in account $account.${NC}"
        echo "Use credentials for account $account, for example with AWS_PROFILE, and run destroy again."
        exit 1
    fi
}

# Run a read-only AWS lookup and keep its output in AWS_LOOKUP_OUTPUT.
# Returns 0 if the resource exists and 1 if the error text contains
# not_found. Any other failure prints failure, then the AWS error, and
# exits, so an expired login or a missing permission never reads as
# deleted. Call it directly, not in $(...), so that exit stops the script.
aws_lookup() {
    local failure="$1" not_found="$2" output errors status=0
    shift 2
    # aws_lookup runs inside if, where set -e is off, so check these.
    if ! output=$(make_temp) || ! errors=$(make_temp); then
        exit 1
    fi
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
    echo -e "${RED}$failure${NC}"
    cat "$errors"
    rm -f "$errors"
    exit 1
}

# Print the ID of $RUNTIME_NAME's Runtime from $STACK_NAME, or fail. CLI
# 1.2.0 does not record the ID in its deployed state. The stack names the
# Runtime ApplicationRuntime<Name>Runtime<hash>: the 'Application' construct
# in agentcore/cdk/lib/cdk-stack.ts, the RuntimeEnvironment and
# AgentCoreRuntime construct IDs from @aws/agentcore-cdk, and the
# 8-character hash CDK adds. Its physical ID is the Runtime ARN. Exactly one
# resource must match, and the ID must match the AgentCore pattern, so the
# log group prefix built from it can only match this Runtime. The stack
# delete removes the resource, so destroy reads it first. destroy calls this
# inside if, where set -e is off, so every step is checked.
runtime_id() {
    local region resources
    region=$(target_region) || return 1
    resources=$(aws cloudformation describe-stack-resources --stack-name "$STACK_NAME" \
        --region "$region" --output json) || return 1
    jq -r -e --arg n "$RUNTIME_NAME" '
        def pascal: [splits("[-_]")] | map((.[:1] | ascii_upcase) + .[1:]) | join("");
        "[a-zA-Z][a-zA-Z0-9_]{0,99}-[a-zA-Z0-9]{10}" as $id
        | "\\AApplicationRuntime\($n | pascal)Runtime[0-9A-F]{8}\\z" as $logical
        | [.StackResources[]
            | select(.ResourceType == "AWS::BedrockAgentCore::Runtime"
                and (.LogicalResourceId | type) == "string"
                and (.LogicalResourceId | test($logical)))]
        | if length == 1 then .[0].PhysicalResourceId
          else error("the stack has \(length) Runtime resources for \($n), not 1") end
        | if type != "string" then error("the \($n) Runtime has no physical ID")
          elif test("\\Aarn:aws[a-z-]*:bedrock-agentcore:[a-z0-9-]+:[0-9]{12}:runtime/\($id)\\z")
            then sub("\\A.*:runtime/"; "")
          elif test("\\A\($id)\\z") then .
          else error("the \($n) Runtime has an invalid ID: \(.)") end' <<<"$resources"
}

# Delete the CloudWatch log groups of Runtime $1 in region $2. Neither the
# CLI nor the stack deletes them. The prefix ends with the dash after the
# full ID, so it cannot match another Runtime's group. A missing group is
# not an error. A failed delete does not stop the others. The function
# names each group it could not delete and returns 1.
delete_runtime_logs() {
    local prefix="$RUNTIME_LOG_PREFIX$1-" region="$2" names name errors
    local failed="" found=""
    errors=$(make_temp) || return 1
    if ! names=$(aws logs describe-log-groups --log-group-name-prefix "$prefix" \
            --region "$region" --query 'logGroups[].[logGroupName]' --output text \
            2>"$errors"); then
        cat "$errors" >&2
        rm -f "$errors"
        echo -e "${RED}Could not list the log groups under $prefix in $region.${NC}"
        return 1
    fi
    while IFS= read -r name; do
        if [ -z "$name" ] || [[ "$name" != "$prefix"* ]]; then
            continue
        fi
        found=yes
        if aws logs delete-log-group --log-group-name "$name" --region "$region" \
                2>"$errors" </dev/null; then
            echo "Removed: log group $name"
        elif grep -q "ResourceNotFoundException" "$errors"; then
            echo "Not found: log group $name"
        else
            cat "$errors" >&2
            failed+="${failed:+$'\n'}  $name"
        fi
    done <<<"$names"
    rm -f "$errors"
    if [ -z "$found" ]; then
        echo "Not found: log groups under $prefix in $region"
    fi
    if [ -n "$failed" ]; then
        echo -e "${RED}Could not delete these log groups in $region:${NC}"
        echo "$failed"
        return 1
    fi
}

# Report everything destroy may have left. `agentcore status` reads the
# CLI's deployed-state.json, so a lost state file would read as clean. The
# stack is also looked up in AWS by name. When $1 holds a Runtime ID and
# nothing remains, delete that Runtime's log groups too.
report_remaining() {
    local status errors remaining region
    local failure="Could not check AWS for remaining resources:"
    errors=$(make_temp) || exit 1
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
    # The lookups below use the active credentials. destroy checked the
    # account before the deploy, but the credentials can change after that,
    # for example when a session expires or a profile changes. So check again.
    require_target_account "$region"
    if aws_lookup "$failure" "does not exist" aws cloudformation describe-stacks \
        --region "$region" --stack-name "$STACK_NAME" \
        --query 'Stacks[0].StackStatus' --output text; then
        remaining+="${remaining:+$'\n'}  stack $STACK_NAME: $AWS_LOOKUP_OUTPUT"
        remaining+=$'\n'"    Delete it with: aws cloudformation delete-stack --region $region --stack-name $STACK_NAME"
    fi
    if [ -n "$remaining" ]; then
        echo -e "${RED}Still deployed in target '$TARGET':${NC}"
        echo "$remaining"
        exit 1
    fi
    if [ -n "${1:-}" ] && ! delete_runtime_logs "$1" "$region"; then
        exit 1
    fi
    echo -e "${GREEN}Cleanup complete. Nothing is deployed in target '$TARGET'.${NC}"
}

# Export DEPLOY_VARS from ../.env, which sits outside the code zip. A value
# exported in the shell wins. The file is parsed, not sourced, and only these
# names are exported, so the passwords in it stay out of the CDK process.
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

env_file, *names = sys.argv[1:]
values = dotenv_values(env_file)
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

trap on_exit EXIT

case "${1:-help}" in
    start)
        ensure_deps
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
        # $install is two words, npm and its command, so it is left unquoted.
        install=$(cdk_install_command)
        (cd "$CDK_DIR" && $install)
        echo ""
        echo -e "${GREEN}Configuration complete!${NC}"
        echo "Set the deploy settings in ../.env, then run './agent.sh deploy'"
        ;;

    deploy)
        ensure_project
        ensure_no_secrets_in_zip
        load_deploy_env
        ensure_cdk_deps
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
        # Check the account before anything changes, so credentials for
        # another account cannot deploy the empty project there.
        require_target_account
        # The deploy below fails when the target has no stack. With no stack
        # there is nothing to remove, so skip the prompt and the deploy. The
        # report still looks up the stack, so a leftover fails the run.
        stack_region=$(target_region)
        if ! aws_lookup "Could not check stack $STACK_NAME in $stack_region with CloudFormation:" \
            "does not exist" aws cloudformation describe-stacks \
            --region "$stack_region" --stack-name "$STACK_NAME" \
            --query 'Stacks[0].StackStatus' --output text; then
            echo -e "${YELLOW}Stack $STACK_NAME does not exist in $stack_region, so there is nothing to remove.${NC}"
            echo ""
            report_remaining
            exit 0
        fi
        if [ "${2:-}" != "--yes" ]; then
            confirm_destroy
        fi
        # destroy runs agentcore deploy too. Install before the spec changes,
        # so a failed install stops with nothing changed.
        ensure_cdk_deps
        # The Runtime's log groups outlive the stack. Read its ID now, while
        # the stack still holds the Runtime, and delete them once the
        # report confirms nothing remains.
        if ! RUNTIME_ID=$(runtime_id); then
            RUNTIME_ID=""
            echo -e "${YELLOW}No Runtime ID was found in the stack, so destroy will not remove the Runtime's log groups.${NC}"
        fi
        echo -e "${YELLOW}Removing supervisor from AgentCore Runtime...${NC}"
        echo ""
        # The CLI has no destroy command. A deploy of a project that declares
        # nothing deployable removes the target's stack. So remove the
        # Runtime from the spec and deploy. That deploy fails when the target
        # has no stack, which the check above rules out. With no Runtime, the
        # stack reads no deploy settings, so destroy does not need ../.env.
        begin_spec_restore
        agentcore remove runtime --name "$RUNTIME_NAME"
        agentcore deploy --target "$TARGET" --yes
        end_spec_restore
        echo ""
        report_remaining "$RUNTIME_ID"
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
