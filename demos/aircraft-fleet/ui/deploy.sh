#!/bin/bash
# Aircraft Fleet UI - AWS Lambda with a streaming function URL
#
# Hosts the browser UI on Lambda, behind a Cognito sign-in, against the
# supervisor that ../supervisor-agent/agent.sh deploy put on AgentCore.
#
# Usage:
#   ./deploy.sh deploy             Build the image, deploy the stack, and print the URL
#   ./deploy.sh status             Show the stack status and the URL
#   ./deploy.sh add-user EMAIL     Create a user. Cognito emails them a temporary password
#   ./deploy.sh destroy [--yes]    Delete the stack and its users (asks first)
#
# The CDK app is in infra/. It uses the account's existing CDK bootstrap.

set -e

UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$UI_DIR/infra"
SUPERVISOR_DIR="$UI_DIR/../supervisor-agent"
# The same shared file that ./agent.sh deploy writes AGENT_ARN to.
SHARED_ENV="$UI_DIR/../.env"
# Must match STACK_NAME in infra/lib/ui-stack.ts.
STACK_NAME="FleetUi"
# The settings infra/lib/ui-stack.ts passes to the function. Synth fails and
# names any that are missing or malformed.
DEPLOY_VARS=(AGENT_ARN NEO4J_URI NEO4J_USERNAME NEO4J_DATABASE NEO4J_PASSWORD_SECRET_ARN)
cd "$UI_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_usage() {
    echo "Aircraft Fleet UI - AWS Lambda with a streaming function URL"
    echo ""
    echo "Usage:"
    echo "  ./deploy.sh deploy             Build the image, deploy the stack, and print the URL"
    echo "  ./deploy.sh status             Show the stack status and the URL"
    echo "  ./deploy.sh add-user EMAIL     Create a user. Cognito emails them a temporary password"
    echo "  ./deploy.sh destroy [--yes]    Delete the stack and its users (asks first)"
    echo "  ./deploy.sh help               Show this help message"
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo -e "${RED}ERROR: $1 is not installed. $2${NC}"
        exit 1
    fi
}

# Export DEPLOY_VARS and AWS_REGION from $SHARED_ENV. A value exported in the
# shell wins. The file is parsed, not sourced, and only these names are
# exported, so the passwords in it stay out of the CDK process. Nothing is
# printed.
load_shared_env() {
    require_command uv "Install it from https://docs.astral.sh/uv/."
    if [ ! -f "$SHARED_ENV" ]; then
        echo -e "${RED}ERROR: $SHARED_ENV not found${NC}"
        echo "Copy ../.env.sample to ../.env and set the fleet settings."
        exit 1
    fi
    local exports
    exports=$(uv run --project "$SUPERVISOR_DIR" --quiet python - "$SHARED_ENV" "${DEPLOY_VARS[@]}" AWS_REGION <<'PY'
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

# The UI deploys to the region of the runtime it calls. Without AGENT_ARN,
# as after ./agent.sh destroy, it is AWS_REGION, which destroy keeps.
resolve_region() {
    local region=""
    if [ -n "${AGENT_ARN:-}" ]; then
        IFS=: read -r _ _ _ region _ <<<"$AGENT_ARN"
    fi
    export AWS_REGION="${region:-${AWS_REGION:-us-east-1}}"
}

# Stop before a build when either setting the stack cannot do without is
# missing. Synth checks the rest.
require_deploy_settings() {
    if [ -z "${AGENT_ARN:-}" ]; then
        echo -e "${RED}ERROR: AGENT_ARN is not set in $SHARED_ENV or the shell.${NC}"
        echo "Deploy the supervisor first: cd ../supervisor-agent && ./agent.sh deploy"
        echo "It writes AGENT_ARN to $SHARED_ENV."
        exit 1
    fi
    if [ -z "${NEO4J_PASSWORD_SECRET_ARN:-}" ]; then
        echo -e "${RED}ERROR: NEO4J_PASSWORD_SECRET_ARN is not set in $SHARED_ENV or the shell.${NC}"
        echo "Create the read-only fleet secret: cd ../supervisor-agent && uv run fleet-supervisor-secrets"
        echo "Then add the ARN line it prints to $SHARED_ENV."
        exit 1
    fi
}

# Exit unless the active AWS credentials belong to the account in AGENT_ARN,
# where the stack deploys.
require_runtime_account() {
    local account caller
    IFS=: read -r _ _ _ _ account _ <<<"$AGENT_ARN"
    if ! caller=$(aws sts get-caller-identity --query Account --output text); then
        echo -e "${RED}ERROR: could not check the active AWS account with STS.${NC}"
        exit 1
    fi
    if [ "$caller" != "$account" ]; then
        echo -e "${RED}ERROR: the active AWS credentials belong to account $caller, but AGENT_ARN is in account $account.${NC}"
        echo "Use credentials for account $account, for example with AWS_PROFILE."
        exit 1
    fi
}

# Install infra/node_modules from the tracked package-lock.json when it is
# missing, incomplete, or older than the lock. npm ci never rewrites the lock.
ensure_infra_deps() {
    require_command npm "Install Node.js 20 or later."
    if [ -f "$INFRA_DIR/node_modules/.package-lock.json" ] \
        && ! [ "$INFRA_DIR/package-lock.json" -nt "$INFRA_DIR/node_modules/.package-lock.json" ]; then
        return
    fi
    echo -e "${YELLOW}Installing the CDK dependencies...${NC}"
    if ! (cd "$INFRA_DIR" && npm ci); then
        echo -e "${RED}ERROR: npm ci failed in $INFRA_DIR${NC}"
        exit 1
    fi
}

# Print stack output $1, or nothing when the stack or the output is missing.
stack_output() {
    aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
        --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" \
        --output text 2>/dev/null | grep -v '^None$' || true
}

# Ask before destroying. Anything but y or yes, including no input from a
# non-interactive shell, cancels.
confirm_destroy() {
    local reply=""
    echo -e "${YELLOW}This deletes the $STACK_NAME stack in $AWS_REGION, with its Cognito users.${NC}"
    read -r -p "Continue? [y/N] " reply || true
    case "$reply" in
        y|Y|yes|YES) ;;
        *)
            echo "Cancelled. Nothing was changed."
            exit 1
            ;;
    esac
}

case "${1:-help}" in
    deploy)
        load_shared_env
        require_deploy_settings
        resolve_region
        require_command aws "Install the AWS CLI."
        require_command docker "The image builds with Docker for linux/arm64."
        if ! docker info >/dev/null 2>&1; then
            echo -e "${RED}ERROR: Docker is not running. Start it, then deploy again.${NC}"
            exit 1
        fi
        require_runtime_account
        ensure_infra_deps
        echo -e "${GREEN}Deploying the fleet UI to $AWS_REGION...${NC}"
        echo "The first deploy builds the image and takes several minutes."
        echo ""
        (cd "$INFRA_DIR" && npm run --silent build && npx cdk deploy "$STACK_NAME" "${@:2}")
        url=$(stack_output UiUrl)
        echo ""
        echo -e "${GREEN}Deployment complete!${NC}"
        echo "Open $url"
        echo "Add a user first: ./deploy.sh add-user you@example.com"
        ;;

    status)
        load_shared_env
        resolve_region
        require_command aws "Install the AWS CLI."
        status=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
            --query 'Stacks[0].StackStatus' --output text 2>/dev/null) || status=""
        if [ -z "$status" ]; then
            echo "The $STACK_NAME stack is not deployed in $AWS_REGION."
            exit 0
        fi
        echo "Stack:  $STACK_NAME ($status) in $AWS_REGION"
        echo "URL:    $(stack_output UiUrl)"
        echo "Users:  $(stack_output UserPoolId)"
        ;;

    add-user)
        email="${2:-}"
        if [[ ! "$email" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
            echo -e "${RED}ERROR: give the user's email address: ./deploy.sh add-user you@example.com${NC}"
            exit 1
        fi
        load_shared_env
        resolve_region
        require_command aws "Install the AWS CLI."
        pool=$(stack_output UserPoolId)
        if [ -z "$pool" ]; then
            echo -e "${RED}ERROR: the $STACK_NAME stack is not deployed in $AWS_REGION. Run ./deploy.sh deploy first.${NC}"
            exit 1
        fi
        # Cognito makes the temporary password and emails it. The response
        # holds no password, and it is discarded anyway.
        aws cognito-idp admin-create-user --user-pool-id "$pool" --username "$email" \
            --user-attributes Name=email,Value="$email" Name=email_verified,Value=true \
            --desired-delivery-mediums EMAIL >/dev/null
        echo -e "${GREEN}Created $email.${NC} Cognito emailed them a temporary password."
        echo "They set a new password at their first sign-in at $(stack_output UiUrl)"
        ;;

    destroy)
        load_shared_env
        resolve_region
        require_command aws "Install the AWS CLI."
        if ! aws cloudformation describe-stacks --stack-name "$STACK_NAME" >/dev/null 2>&1; then
            echo "The $STACK_NAME stack is not deployed in $AWS_REGION. Nothing to delete."
            exit 0
        fi
        if [ "${2:-}" != "--yes" ]; then
            confirm_destroy
        fi
        # Deleting the stack directly needs no synth, so it works after
        # ./agent.sh destroy has removed AGENT_ARN.
        echo -e "${YELLOW}Deleting $STACK_NAME...${NC}"
        aws cloudformation delete-stack --stack-name "$STACK_NAME"
        if ! aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"; then
            echo -e "${RED}ERROR: $STACK_NAME did not delete. Check its events in the CloudFormation console.${NC}"
            exit 1
        fi
        echo -e "${GREEN}Deleted $STACK_NAME.${NC}"
        echo "The image stays in the CDK bootstrap repository, as every CDK image asset does."
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
