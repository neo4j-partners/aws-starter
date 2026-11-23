#!/bin/bash
# Fraud Memory Agent - AgentCore Runtime
#
# A Strands agent that investigates the fraud graph through the Neo4j MCP
# Gateway and keeps its memory in the Neo4j Agent Memory Service (NAMS).
#
# `start` runs the local server in the foreground (port 7020). The same
# server and the clients are also uv console scripts. See the README
# "Local run". In short:
#
#   Terminal 1:  uv run fraud-server          # or ./agent.sh start
#   Terminal 2:  uv run fraud-cli "question"
#                uv run fraud-demo
#                uv run fraud-invoke memory-demo
#
# Usage:
#   ./agent.sh start                  Start the agent locally (port 7020)
#   ./agent.sh stop                   Stop the local agent
#   ./agent.sh test                   Test the local agent
#   ./agent.sh deploy [--skip-smoke]  Deploy, then verify the Runtime
#   ./agent.sh status                 Check deployment status
#   ./agent.sh verify                 Check READY state and run a graph smoke test
#   ./agent.sh logs [30m]             Show Runtime logs from the last 30 minutes
#   ./agent.sh invoke-cloud "prompt"  Invoke the deployed agent (FRAUD_USER_ID, default demo-user)
#   ./agent.sh destroy [--yes]        Remove from AgentCore (asks first)
#
# The cloud commands use the AgentCore CLI (npm install -g @aws/agentcore).
# The project lives in agentcore/. Its runtime's codeLocation is this folder,
# so `agentcore deploy` zips everything here except .git, .venv,
# __pycache__, .pytest_cache, .DS_Store, node_modules, and agentcore/.

set -e

# This script, the uv project (pyproject.toml, uv.lock, .venv), and the
# runtime entrypoint main.py live at the agent root. The local secrets,
# .env and .mcp-credentials.json, sit one level up in
# demos/fraud-amazon-quick/, outside the code zip.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The deployed runtime name is <project>_<target>_<runtime> and must be at
# most 48 characters. FraudMemory_default_fraud_memory_agent is 38.
PROJECT_NAME="FraudMemory"
RUNTIME_NAME="fraud_memory_agent"
PROJECT_SPEC="agentcore/agentcore.json"
CDK_DIR="agentcore/cdk"
TARGET="default"
# The deploy targets. The first deploy writes this file, and git ignores it.
TARGETS_FILE="agentcore/aws-targets.json"
# AgentCore writes each Runtime's logs to <prefix><runtime-id>-<endpoint>.
RUNTIME_LOG_PREFIX="/aws/bedrock-agentcore/runtimes/"
# The two AgentCore Identity credentials the Runtime reads. deploy declares
# them for the one CLI run, then restores the tracked agentcore.json. The
# stack in agentcore/cdk/lib/cdk-stack.ts then sets
# CREDENTIAL_FRAUD_GATEWAY_NAME and CREDENTIAL_NAMS_API_KEY_NAME on the
# Runtime and grants it exactly these two providers.
# - fraud-gateway: an OAuth2 provider that holds the Gateway client secret.
# - nams-api-key: an API key provider that holds MEMORY_API_KEY.
GATEWAY_CREDENTIAL="fraud-gateway"
NAMS_CREDENTIAL="nams-api-key"
# `agentcore add credentials` writes each secret, encrypted with a key in
# ~/.agentcore or the keychain, to these variables in agentcore/.env.local,
# each under a comment line. The names and comments are from
# @aws/agentcore 1.2.0.
GATEWAY_SECRET_VAR="AGENTCORE_CREDENTIAL_FRAUD_GATEWAY_CLIENT_SECRET"
GATEWAY_SECRET_COMMENT="# OAuth client secret for credential provider '$GATEWAY_CREDENTIAL' (set before deploy)"
NAMS_SECRET_VAR="AGENTCORE_CREDENTIAL_NAMS_API_KEY"
NAMS_SECRET_COMMENT="# API key for credential provider '$NAMS_CREDENTIAL' (set before deploy)"
ENV_LOCAL="agentcore/.env.local"
# The stack and the credential provider names the CLI derives, so destroy
# can check AWS for them directly. From resolveTargetStacks in
# @aws/agentcore-cdk 1.2.0 (underscores become hyphens) and providerName in
# @aws/agentcore 1.2.0.
STACK_NAME="AgentCore-${PROJECT_NAME//_/-}-${TARGET//_/-}"
GATEWAY_PROVIDER="${PROJECT_NAME}_${TARGET}_${GATEWAY_CREDENTIAL}"
NAMS_PROVIDER="${PROJECT_NAME}_${TARGET}_${NAMS_CREDENTIAL}"
# Local Gateway credentials, written by neo4j-mcp-server/deploy.py.
CREDENTIALS_FILE="${MCP_CREDENTIALS_FILE:-$ROOT_DIR/../.mcp-credentials.json}"
# The NAMS settings and MEMORY_API_KEY.
SHARED_ENV="$ROOT_DIR/../.env"
# AgentCore deployment region. AgentCore's primary region is us-east-1
# (also supported in us-west-2). Set AWS_REGION to override. The CLI creates
# the default deploy target from this region on the first deploy.
REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION="$REGION"
# The settings agentcore/cdk/lib/cdk-stack.ts copies into the Runtime
# environment. Synth fails and names any that are missing or malformed.
# GATEWAY_URL and GATEWAY_SCOPES come from gateway_url and scope in the
# credentials file. The optional MEMORY_* settings come from ../.env.
# MEMORY_API_KEY is not one of them: it goes to the nams-api-key provider.
DEPLOY_VARS=(GATEWAY_URL GATEWAY_SCOPES MEMORY_ENDPOINT MEMORY_WORKSPACE_ID MEMORY_TOOLS)
# The local server's port. fraud-server reads PORT, default 7020.
LOCAL_PORT="${PORT:-7020}"
# The NAMS user that invoke-cloud sends. The runtime requires one.
INVOKE_USER_ID="${FRAUD_USER_ID:-demo-user}"
cd "$ROOT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_usage() {
    echo "Fraud Memory Agent - AgentCore Runtime"
    echo ""
    echo "Local:"
    echo "  ./agent.sh start              Start the agent locally (port 7020)"
    echo "  ./agent.sh stop               Stop the local agent"
    echo "  ./agent.sh test               Test the local agent"
    echo ""
    echo "Or run the server and clients directly:"
    echo "  Terminal 1:  uv run fraud-server          # Ctrl+C to stop"
    echo "  Terminal 2:  uv run fraud-cli \"question\""
    echo "               uv run fraud-demo"
    echo "               uv run fraud-invoke memory-demo"
    echo ""
    echo "Deployment:"
    echo "  ./agent.sh deploy             Deploy, then verify the Runtime with a graph smoke test"
    echo "  ./agent.sh deploy --skip-smoke  Deploy without the smoke test (not recommended)"
    echo "  ./agent.sh status             Check deployment status"
    echo "  ./agent.sh verify             Check READY state and run the graph smoke test"
    echo "  ./agent.sh logs [30m]         Show Runtime logs from the last 30 minutes"
    echo "  ./agent.sh invoke-cloud \"prompt\"  Invoke the deployed agent"
    echo "  ./agent.sh destroy [--yes]    Remove from AgentCore (asks first)"
    echo "  ./agent.sh help               Show this help message"
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
    if [ ! -f "$PROJECT_SPEC" ]; then
        echo -e "${RED}ERROR: $PROJECT_SPEC not found${NC}"
        echo "It is tracked in git. Restore it with: git checkout -- $PROJECT_SPEC"
        exit 1
    fi
}

# agentcore deploy refuses to run without agentcore/cdk/node_modules, and
# git ignores that folder, so a fresh clone has none. Install it from the
# tracked package-lock.json before deploy or destroy. npm ci installs
# exactly what the lock lists and never rewrites it. npm writes
# node_modules/.package-lock.json only after a complete install, so a
# partial install from a failed npm ci is installed again. A package-lock.json
# newer than that file, as after a pull that changes it, is installed again
# too, so deploy does not run on the old CDK libraries.
ensure_cdk_deps() {
    if [ -f "$CDK_DIR/node_modules/.package-lock.json" ] \
        && ! [ "$CDK_DIR/package-lock.json" -nt "$CDK_DIR/node_modules/.package-lock.json" ]; then
        return
    fi
    if ! command -v npm >/dev/null 2>&1; then
        echo -e "${RED}ERROR: npm is not installed, so the CDK dependencies cannot be installed${NC}"
        echo "Install Node.js, then run: (cd $CDK_DIR && npm ci)"
        exit 1
    fi
    echo -e "${YELLOW}Installing the CDK dependencies...${NC}"
    if ! (cd "$CDK_DIR" && npm ci); then
        echo -e "${RED}ERROR: npm ci failed in $CDK_DIR${NC}"
        echo "Fix the error above, then run: (cd $CDK_DIR && npm ci)"
        exit 1
    fi
    echo ""
}

# The code zip has no ignore file, so any secrets file in this folder would
# be uploaded with the code: .env*, .mcp-credentials*.json, .mcp.json,
# .agentcore.json, credentials*.json, or *.pem. .venv is not zipped, but a
# venv/ folder without the dot is, so it is refused too. agentcore/ holds
# the CLI's own .env.local, which is not zipped. -L follows symlinks, so a
# link to a secrets file is caught. A find error stops the deploy instead
# of passing the check.
ensure_no_secrets_in_zip() {
    local found
    if ! found="$(find -L . \( -path ./.venv -o -path ./agentcore \) -prune \
        -o -type d -name venv -prune -print \
        -o -type f \( -name '.env*' -o -name '.mcp-credentials*.json' -o -name '.mcp.json' \
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
        echo ".env and .mcp-credentials.json belong in demos/fraud-amazon-quick/."
        exit 1
    fi
}

# Print the deployed runtime ARN: AGENT_ARN if set, else the arn field of
# the runtime resource in `agentcore status --json`. CLI 1.2.0 sets that
# field from the stack's RuntimeArn output once the runtime is deployed.
runtime_arn() {
    if [ -n "${AGENT_ARN:-}" ]; then
        echo "$AGENT_ARN"
        return
    fi
    agentcore status --json --target "$TARGET" 2>/dev/null \
        | jq -r --arg n "$RUNTIME_NAME" \
            '[.resources[]? | select(.resourceType == "runtime" and .name == $n) | .arn // empty][0] // empty' \
            2>/dev/null
}

# Exit if $PROJECT_SPEC already declares credential $1. A spec that holds it
# means an earlier run did not restore the tracked file.
refuse_declared_credential() {
    if jq -e --arg name "$1" '.credentials // [] | any(.name == $name)' "$PROJECT_SPEC" >/dev/null; then
        echo -e "${RED}ERROR: $PROJECT_SPEC already declares the $1 credential${NC}"
        echo "An earlier run did not restore it. Restore the tracked spec, then run this again:"
        echo "  git checkout -- $PROJECT_SPEC"
        exit 1
    fi
}

# The runtime gets its Gateway token from the fraud-gateway OAuth provider.
# The AgentCore CLI creates or updates that provider from the credentials
# entry in agentcore.json before CDK runs. A deploy without the entry
# deletes the provider, so the entry is added for every deploy. destroy does
# not add it: see the destroy command. The tracked agentcore.json never holds
# it, so it carries no account details.
#
# The client ID and scope come from the credentials file, and the discovery
# URL from the MCP server stack. The secret goes to the CLI on stdin, never
# in argv, and the CLI stores it in agentcore/.env.local. The EXIT trap
# removes that line and restores the tracked agentcore.json.
add_gateway_credential() {
    ensure_credentials
    refuse_declared_credential "$GATEWAY_CREDENTIAL"
    local client_id scope stack_name discovery_url
    client_id=$(jq -r '.client_id // empty' "$CREDENTIALS_FILE")
    scope=$(jq -r '.scope // empty' "$CREDENTIALS_FILE")
    stack_name=$(jq -r '.stack_name // empty' "$CREDENTIALS_FILE")
    if [ -z "$client_id" ] || [ -z "$scope" ] || [ -z "$stack_name" ] \
        || ! jq -e '.client_secret | type == "string" and length > 0' "$CREDENTIALS_FILE" >/dev/null; then
        echo -e "${RED}ERROR: $CREDENTIALS_FILE needs client_id, client_secret, scope, and stack_name${NC}"
        echo "Regenerate it with: cd neo4j-mcp-server && ./deploy.py --env finance credentials"
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
    # Drop lines a killed run may have left, so the CLI writes fresh ones.
    strip_credential_secrets
    jq -r '.client_secret' "$CREDENTIALS_FILE" | agentcore add credentials oauth \
        --name "$GATEWAY_CREDENTIAL" \
        --client-id "$client_id" \
        --discovery-url "$discovery_url" \
        --scopes "$scope" \
        --client-secret -
}

# Run the NAMS key helper. With `check` it exits 0 when MEMORY_API_KEY is
# set, and with `print` it writes the key to stdout. A value exported in the
# shell wins over ../.env. The file is parsed, not sourced.
nams_api_key() {
    uv run --quiet python - "$1" "$SHARED_ENV" <<'PY'
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

mode, env_file = sys.argv[1:]
key = os.environ.get("MEMORY_API_KEY", "").strip()
if not key and Path(env_file).is_file():
    key = (dotenv_values(env_file).get("MEMORY_API_KEY") or "").strip()
if not key:
    sys.exit(1)
if mode == "print":
    sys.stdout.write(key)
PY
}

# The runtime reads MEMORY_API_KEY from the nams-api-key API key provider on
# its first request. The CLI creates or updates that provider from the
# credentials entry, as for the Gateway credential above. The key goes to
# the CLI on stdin, never in argv, and the CLI stores it in
# agentcore/.env.local. The EXIT trap removes that line.
add_nams_credential() {
    refuse_declared_credential "$NAMS_CREDENTIAL"
    if ! nams_api_key check; then
        echo -e "${RED}ERROR: MEMORY_API_KEY is not set${NC}"
        echo "NAMS memory is required. Set it in $SHARED_ENV and run './agent.sh deploy' again."
        exit 1
    fi
    strip_credential_secrets
    nams_api_key print | agentcore add credentials api-key \
        --name "$NAMS_CREDENTIAL" \
        --api-key -
}

# Temporary files go in one folder per run, which on_exit removes, so Ctrl+C
# leaves none behind. The name is fixed before the folder exists, so a file
# whose name an interrupt lost inside $(make_temp) is removed with it.
TMP_ROOT="${TMPDIR:-/tmp}"
TMP_ROOT="${TMP_ROOT%/}/fraud-memory-agent.$$"

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
    remove_strip_copy
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

# The copy strip_credential_secrets writes before it replaces .env.local
# holds the file's other lines. Its name is this prefix, which ends in the
# PID, plus a random suffix from mktemp. on_exit removes every name with
# this prefix, so a copy whose name an interrupt lost inside $(mktemp) is
# removed too, and another run's copy is not.
ENV_STRIP_PREFIX="$ENV_LOCAL.strip.$$"
ENV_STRIP_TMP=""

# Remove both secret lines, and the comment the CLI writes above each, from
# agentcore/.env.local. Every other line is kept. A secret line is matched
# in each form the CLI reads: optional leading space, an optional export,
# the exact variable name, then optional space before the =. Space is
# [[:space:]], which covers the ASCII characters that \s matches in the
# CLI's pattern. A comment must match the whole line. A failure before a
# deploy is tried again by the restore, so only restore_project, the last
# try, says to delete the lines by hand.
strip_credential_secrets() {
    [ -f "$ENV_LOCAL" ] || return 0
    # The copy sits next to the file, so mv replaces the file in one step.
    # mktemp makes the copy with a random suffix, refuses a name that
    # already exists, and creates it with mode 0600, the mode the CLI writes
    # .env.local with. Nothing can be planted at the name ahead of time. The
    # umask 077 subshells keep the copy 0600 even so. The copy must then be
    # a regular file, not a link. .env.local is checked for a link again
    # right before mv, which would replace the link and leave the secrets in
    # its target.
    # awk's redirect would follow a link swapped in after mktemp. Only someone
    # who can write to agentcore/ could do that, and they could replace
    # .env.local anyway.
    if ! ENV_STRIP_TMP=$(umask 077 && mktemp "$ENV_STRIP_PREFIX.XXXXXX") \
        || ! (umask 077 \
                && awk -v gateway="$GATEWAY_SECRET_VAR" -v gateway_comment="$GATEWAY_SECRET_COMMENT" \
                    -v nams="$NAMS_SECRET_VAR" -v nams_comment="$NAMS_SECRET_COMMENT" '
                    function secret(name) {
                        return $0 ~ ("^[[:space:]]*(export[[:space:]]+)?" name "[[:space:]]*=")
                    }
                    !secret(gateway) && !secret(nams) && $0 != gateway_comment && $0 != nams_comment' \
                    "$ENV_LOCAL" > "$ENV_STRIP_TMP") \
        || [ ! -f "$ENV_STRIP_TMP" ] || [ -L "$ENV_STRIP_TMP" ] \
        || [ -L "$ENV_LOCAL" ] \
        || ! mv -f "$ENV_STRIP_TMP" "$ENV_LOCAL"; then
        remove_strip_copy
        if [ -L "$ENV_LOCAL" ]; then
            echo -e "${RED}$ENV_LOCAL is a symbolic link, so it was not replaced.${NC}" >&2
        fi
        echo -e "${RED}Could not remove $GATEWAY_SECRET_VAR and $NAMS_SECRET_VAR from $ENV_LOCAL.${NC}" >&2
        return 1
    fi
}

# Exit if .env.local is a symbolic link. mv would replace the link with a
# regular file and leave the secrets in the link's target, so deploy and
# destroy check this before anything changes.
refuse_linked_env_local() {
    if [ -L "$ENV_LOCAL" ]; then
        echo -e "${RED}$ENV_LOCAL is a symbolic link. Replace it with a regular file and run again.${NC}"
        exit 1
    fi
}

# Remove this run's copies by their prefix. The dot after the PID keeps out
# a run whose PID starts with the same digits. A copy that is already gone
# leaves the pattern unmatched, and rm -f ignores it.
remove_strip_copy() {
    rm -f "$ENV_STRIP_PREFIX".*
}

# Put back the tracked agentcore.json and remove the secret lines. Returns
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
            KEEP_TMP_ROOT=1
            failed=1
        fi
    fi
    if ! strip_credential_secrets; then
        echo -e "${RED}Delete the $GATEWAY_SECRET_VAR and $NAMS_SECRET_VAR lines from $ENV_LOCAL by hand.${NC}" >&2
        failed=1
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
    echo -e "${YELLOW}This deletes the $RUNTIME_NAME Runtime, the $GATEWAY_CREDENTIAL and $NAMS_CREDENTIAL credential providers, and the stack in target '$TARGET'.${NC}"
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
# providers as gone. $1 is the region for the STS call, by default the
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
# stack and both credential providers are also looked up in AWS by name.
# When $1 holds a Runtime ID and nothing remains, delete that Runtime's log
# groups too.
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
    if aws_lookup "$failure" "ResourceNotFoundException" aws bedrock-agentcore-control \
        get-oauth2-credential-provider --region "$region" --name "$GATEWAY_PROVIDER"; then
        remaining+="${remaining:+$'\n'}  credential provider $GATEWAY_PROVIDER"
        remaining+=$'\n'"    Delete it with: aws bedrock-agentcore-control delete-oauth2-credential-provider --region $region --name $GATEWAY_PROVIDER"
    fi
    if aws_lookup "$failure" "ResourceNotFoundException" aws bedrock-agentcore-control \
        get-api-key-credential-provider --region "$region" --name "$NAMS_PROVIDER"; then
        remaining+="${remaining:+$'\n'}  credential provider $NAMS_PROVIDER"
        remaining+=$'\n'"    Delete it with: aws bedrock-agentcore-control delete-api-key-credential-provider --region $region --name $NAMS_PROVIDER"
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

# Export DEPLOY_VARS from ../.env and the credentials file, which both sit
# outside the code zip. A value exported in the shell wins. The files are
# parsed, not sourced, and only these names are exported, so the NAMS key
# and the client secret in them stay out of the CDK process.
load_deploy_env() {
    ensure_deps
    ensure_credentials
    if [ ! -f "$SHARED_ENV" ]; then
        echo -e "${RED}ERROR: $SHARED_ENV not found${NC}"
        echo "Copy ../.env.sample to ../.env and set MEMORY_API_KEY."
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
        echo "  cp \"$ROOT_DIR/../../../neo4j-mcp-server/.mcp-credentials.finance.json\" \"$CREDENTIALS_FILE\""
        exit 1
    fi
}

# Check READY state and run the graph smoke test against the deployed
# Runtime.
verify_deployment() {
    local arn
    arn="$(runtime_arn)"
    if [ -z "$arn" ]; then
        echo -e "${RED}ERROR: could not find the deployed runtime ARN${NC}"
        echo "Set AGENT_ARN, or run './agent.sh deploy' first."
        return 1
    fi
    .venv/bin/python scripts/verify_agentcore_runtime.py --runtime-arn "$arn"
}

# `agentcore invoke` writes the Runtime's SSE stream as it arrives and exits
# 0 even when the runtime sends an error event. That event is
# BedrockAgentCoreApp's `data: {"error": ..., "error_type": ...}`. Show the
# response as it arrives, then fail when it holds an error event.
invoke_deployed() {
    local output status
    output=$(make_temp) || exit 1
    set +e
    agentcore invoke --runtime "$RUNTIME_NAME" --payload "$1" | tee "$output"
    status=${PIPESTATUS[0]}
    set -e
    if [ "$status" -ne 0 ]; then
        rm -f "$output"
        return "$status"
    fi
    # Strip any color codes first, in case FORCE_COLOR is set.
    if sed $'s/\x1b\\[[0-9;]*m//g' "$output" \
        | grep -Eq '^[[:space:]]*(data:[[:space:]]*)?\{"error":'; then
        rm -f "$output"
        echo -e "${RED}The agent returned an error event. See the response above.${NC}"
        return 1
    fi
    rm -f "$output"
}

# Print the PIDs of local fraud-server processes listening on LOCAL_PORT. A
# process on the port that is not fraud-server is left alone.
local_server_pids() {
    local pid
    for pid in $(lsof -t -iTCP:"$LOCAL_PORT" -sTCP:LISTEN 2>/dev/null); do
        if ps -o command= -p "$pid" 2>/dev/null | grep -q "fraud-server"; then
            echo "$pid"
        fi
    done
}

trap on_exit EXIT

case "${1:-help}" in
    start)
        ensure_deps
        echo -e "${GREEN}Starting Fraud Memory Agent on port ${LOCAL_PORT}...${NC}"
        echo "Test with: ./agent.sh test"
        echo ""
        PORT="$LOCAL_PORT" uv run fraud-server
        ;;

    stop)
        echo -e "${YELLOW}Stopping local agent...${NC}"
        PIDS=$(local_server_pids)
        if [ -z "$PIDS" ]; then
            echo "No fraud-server process is listening on port $LOCAL_PORT"
        else
            # $PIDS is one PID per line, so it is left unquoted.
            kill $PIDS
            echo -e "${GREEN}Stopped.${NC}"
        fi
        ;;

    test)
        ensure_deps
        echo -e "${GREEN}Testing local agent...${NC}"
        echo ""
        uv run fraud-cli "Find circular transfer chains"
        ;;

    deploy)
        SKIP_SMOKE=false
        for arg in "${@:2}"; do
            case "$arg" in
                --skip-smoke) SKIP_SMOKE=true ;;
                *)
                    echo -e "${RED}Unknown deploy option: $arg${NC}"
                    echo "Supported options: --skip-smoke"
                    exit 2
                    ;;
            esac
        done
        ensure_project
        refuse_linked_env_local
        ensure_no_secrets_in_zip
        load_deploy_env
        ensure_cdk_deps
        begin_spec_restore
        add_gateway_credential
        add_nams_credential
        # The key is in the provider now. Keep a shell export of it out of
        # the CDK process.
        unset MEMORY_API_KEY
        echo -e "${GREEN}Deploying Fraud Memory Agent to AgentCore Runtime...${NC}"
        echo "This may take several minutes..."
        echo ""
        agentcore deploy
        end_spec_restore
        echo ""
        if [ "$SKIP_SMOKE" = true ]; then
            echo -e "${YELLOW}Deployment completed, but the smoke test was skipped.${NC}"
            echo "Run './agent.sh verify' before sending production traffic."
            exit 0
        fi
        echo "Validating READY state and executing an end-to-end graph smoke test..."
        if ! verify_deployment; then
            echo -e "${RED}Deployment completed, but it was not verified as healthy.${NC}"
            echo "Inspect recent logs with: ./agent.sh logs"
            echo "Re-run the check with: ./agent.sh verify"
            exit 1
        fi
        echo -e "${GREEN}Deployment verified and ready for traffic.${NC}"
        ;;

    status)
        ensure_project
        echo -e "${GREEN}Checking deployment status...${NC}"
        echo ""
        agentcore status "${@:2}"
        ;;

    verify)
        ensure_project
        ensure_deps
        echo -e "${GREEN}Verifying deployed runtime...${NC}"
        echo ""
        verify_deployment
        ;;

    logs)
        ensure_project
        agentcore logs runtime --name "$RUNTIME_NAME" --since "${2:-30m}"
        ;;

    invoke|invoke-cloud)
        ensure_project
        if [ -z "${2:-}" ]; then
            PROMPT="Which accounts have the highest risk scores, and who do they transfer money to?"
            echo -e "${GREEN}Invoking deployed agent with default question...${NC}"
        else
            PROMPT="$2"
            echo -e "${GREEN}Invoking deployed agent...${NC}"
        fi
        # %s prints the prompt as is, so a backslash in it is not an escape.
        printf '%bPrompt: %s%b\n' "$BLUE" "$PROMPT" "$NC"
        echo ""
        # jq builds the JSON, so quotes in the prompt are escaped. The
        # runtime rejects a request with no user_id.
        invoke_deployed "$(jq -nc --arg p "$PROMPT" --arg u "$INVOKE_USER_ID" '{prompt: $p, user_id: $u}')"
        ;;

    destroy)
        ensure_project
        refuse_linked_env_local
        # Check the account before anything changes, so credentials for
        # another account cannot deploy the empty project there.
        require_target_account
        # The deploy below fails when the target has no stack. With no stack
        # there is nothing to remove, so skip the prompt and the deploy.
        # Secret lines an interrupted deploy left in .env.local are still
        # removed, as the restore after a deploy does. The report still looks
        # up the stack and the providers, so a leftover fails the run.
        stack_region=$(target_region)
        if ! aws_lookup "Could not check stack $STACK_NAME in $stack_region with CloudFormation:" \
            "does not exist" aws cloudformation describe-stacks \
            --region "$stack_region" --stack-name "$STACK_NAME" \
            --query 'Stacks[0].StackStatus' --output text; then
            echo -e "${YELLOW}Stack $STACK_NAME does not exist in $stack_region, so there is nothing to remove.${NC}"
            if ! strip_credential_secrets; then
                echo -e "${RED}Delete the $GATEWAY_SECRET_VAR and $NAMS_SECRET_VAR lines from $ENV_LOCAL by hand.${NC}" >&2
                exit 1
            fi
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
        echo -e "${YELLOW}Removing the agent from AgentCore Runtime...${NC}"
        echo ""
        # The CLI has no destroy command. A deploy of a project that declares
        # nothing deployable removes the target's stack. The same deploy
        # deletes every credential provider that deployed-state.json records
        # and the spec no longer declares, so both providers go without being
        # declared. So remove the Runtime from the spec and deploy. That
        # deploy fails when the target has no stack, which the check above
        # rules out. With no Runtime, the stack reads no deploy settings, so
        # destroy needs neither the credentials file nor ../.env.
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
