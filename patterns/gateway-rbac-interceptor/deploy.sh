#!/bin/bash
#
# deploy.sh - Deploy Simple OAuth2 M2M Demo
#
# Usage:
#   ./deploy.sh [OPTIONS]
#
# Options:
#   --region REGION     AWS region (default: us-west-2)
#   --skip-build        Skip Docker image build (use existing image)
#   --destroy           Destroy the stack instead of deploying
#   --help              Show this help message
#
# Examples:
#   ./deploy.sh --region us-west-2           # Full deploy with image build
#   ./deploy.sh --skip-build                 # Quick deploy, reuse existing image
#   ./deploy.sh --destroy                    # Tear down the stack
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKIP_BUILD=false
DESTROY=false
REGION="us-west-2"
STACK_NAME="SimpleOAuthDemo"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${GREEN}==>${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}Warning:${NC} $1"
}

print_error() {
    echo -e "${RED}Error:${NC} $1"
}

show_help() {
    head -25 "$0" | tail -22 | sed 's/^#//' | sed 's/^ //'
    exit 0
}

# Unresolvable host used only to keep docker off the platform credential
# helper; see isolate_docker_config(). Never contacted.
NO_CREDSTORE_MARKER="deploy-sh-no-credstore.invalid"

DOCKER_CONFIG_TMP=""

release_docker_config() {
    if [ -n "$DOCKER_CONFIG_TMP" ]; then
        rm -rf "$DOCKER_CONFIG_TMP"
        DOCKER_CONFIG_TMP=""
    fi
}

# Runs on the normal path and on error, so the ECR token never outlives the run.
# ( ) subshells do not inherit this trap, so the dir survives until the push that
# needs it is done. The signal traps only turn the signal into an exit: cleaning
# up from the handler itself would pull the config dir out from under a deploy
# that bash then carried on with.
trap release_docker_config EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Prepare a throwaway docker config dir with no credsStore in DOCKER_CONFIG_TMP.
#
# `docker login` does not just authenticate; it saves the credential through the
# credsStore named in ~/.docker/config.json (osxkeychain on a Mac). A stale
# keychain item for the registry makes that save fail with errSecDuplicateItem
# (-25299) even though the ECR token is perfectly good, and the helper's exit 1
# fails the whole deploy. Pointing DOCKER_CONFIG at a dir with no credsStore
# keeps the token there for the life of the push, and never reads or writes the
# user's config or keychain.
isolate_docker_config() {
    local real_dir="${DOCKER_CONFIG:-$HOME/.docker}"
    local entry context

    DOCKER_CONFIG_TMP=$(mktemp -d)
    chmod 700 "$DOCKER_CONFIG_TMP"  # briefly holds the ECR token in plaintext

    # config.json is the only file we want to replace. Everything else in the
    # real dir still has to be visible: cli-plugins/ is where the buildx
    # subcommand itself comes from, buildx/ holds the arm64-builder instance,
    # and contexts/ resolves the docker endpoint (OrbStack, Colima, ...).
    # Dotfiles are left out on purpose: they are Docker Hub token bookkeeping
    # that an ECR push never reads, and not linking them keeps this code path
    # from writing anything back into the real dir.
    for entry in "$real_dir"/*; do
        [ -e "$entry" ] || continue
        if [ "$(basename "$entry")" = "config.json" ]; then
            continue
        fi
        ln -s "$entry" "$DOCKER_CONFIG_TMP/"
    done

    # An empty "auths" map is not enough: the docker CLI treats a config with no
    # credentials at all as unconfigured and auto-detects the platform helper
    # (osxkeychain), putting us right back in the keychain. One inert
    # placeholder entry makes the config count as configured, so the CLI stays
    # on its plain-file store. currentContext lives in config.json rather than
    # contexts/, so carry it over too or docker falls back to the default
    # socket and misses the active context's daemon.
    context=$(docker context show 2>/dev/null || true)
    if [ -n "$context" ]; then
        printf '{"auths":{"%s":{}},"currentContext":"%s"}\n' \
            "$NO_CREDSTORE_MARKER" "$context" > "$DOCKER_CONFIG_TMP/config.json"
    else
        printf '{"auths":{"%s":{}}}\n' \
            "$NO_CREDSTORE_MARKER" > "$DOCKER_CONFIG_TMP/config.json"
    fi
    chmod 600 "$DOCKER_CONFIG_TMP/config.json"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --destroy)
            DESTROY=true
            shift
            ;;
        --region)
            REGION="$2"
            shift 2
            ;;
        --help|-h)
            show_help
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

cd "$SCRIPT_DIR"

# The CDK stack is environment-agnostic, so `cdk deploy/destroy` resolves its
# target region from the ambient AWS environment, not from a CLI flag (cdk has
# no --region). Export the chosen region so every `uv run cdk` call below
# targets $REGION, matching the AWS CLI calls that already pass --region.
export AWS_REGION="$REGION"
export AWS_DEFAULT_REGION="$REGION"
export CDK_DEFAULT_REGION="$REGION"

# Check prerequisites
print_step "Checking prerequisites..."

if ! command -v aws &> /dev/null; then
    print_error "AWS CLI is not installed. Please install it first."
    exit 1
fi

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install it first."
    exit 1
fi

if ! command -v uv &> /dev/null; then
    print_error "uv is not installed. Install it: https://docs.astral.sh/uv/"
    exit 1
fi

# Verify AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    print_error "AWS credentials are not configured or have expired."
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REPO_NAME=$(echo "$STACK_NAME" | tr '[:upper:]' '[:lower:]')-mcp-server
echo "  AWS Account: $ACCOUNT_ID"
echo "  Region: $REGION"

# Setup Python environment (uv manages the venv and Python from pyproject.toml/uv.lock)
print_step "Setting up Python environment (uv)..."
uv sync --quiet

# Handle destroy
if [ "$DESTROY" = true ]; then
    print_step "Destroying stack..."
    JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run cdk destroy --force
    
    # Clean up ECR repository
    print_step "Cleaning up ECR repository..."
    aws ecr delete-repository --repository-name "$REPO_NAME" --region "$REGION" --force 2>/dev/null || true
    
    echo ""
    echo -e "${GREEN}Stack destroyed successfully!${NC}"
    exit 0
fi

# Build and push Docker image (unless skipped)
if [ "$SKIP_BUILD" = false ]; then
    print_step "Building Docker image for ARM64..."

    # Check if Docker daemon is running
    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running. Please start Docker first."
        exit 1
    fi

    # Setup buildx with QEMU for ARM64 cross-compilation
    print_step "Setting up Docker buildx for ARM64..."
    docker run --rm --privileged tonistiigi/binfmt --install arm64 > /dev/null 2>&1 || true

    # Create or use existing builder
    if ! docker buildx inspect arm64-builder &> /dev/null; then
        docker buildx create --name arm64-builder --use > /dev/null
    else
        docker buildx use arm64-builder
    fi

    # demo limitation: the ECR repository lifecycle is managed by this script
    # via the AWS CLI, outside the CDK stack. It is created here and deleted in
    # the cleanup step, so a stack destroy alone does not remove it. Production
    # code should model the repository as a CDK resource.
    # Create ECR repository if it doesn't exist
    print_step "Ensuring ECR repository exists..."
    if ! aws ecr describe-repositories --repository-names "$REPO_NAME" --region "$REGION" &> /dev/null; then
        aws ecr create-repository \
            --repository-name "$REPO_NAME" \
            --region "$REGION" \
            --image-scanning-configuration scanOnPush=true > /dev/null
        echo "  Created ECR repository: $REPO_NAME"
    else
        echo "  ECR repository exists: $REPO_NAME"
    fi

    REGISTRY="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
    IMAGE_URI="$REGISTRY/$REPO_NAME:latest"

    # Login and push share one throwaway docker config, so the token written by
    # `docker login` is visible to the pushing build. Exported in a subshell so
    # the rest of the deploy runs against the user's own docker config.
    isolate_docker_config
    (
        export DOCKER_CONFIG="$DOCKER_CONFIG_TMP"

        print_step "Logging in to ECR..."
        # Fetch the token as its own step instead of piping it straight into
        # docker: a pipeline reports only docker's exit status, so an AWS-side
        # failure would show up as docker choking on empty stdin and get blamed
        # on the wrong side.
        if ! ECR_PASSWORD=$(aws ecr get-login-password --region "$REGION" 2>&1); then
            print_error "aws ecr get-login-password failed for region $REGION"
            echo "$ECR_PASSWORD"
            print_error "No token was issued, so docker was never contacted. Check that"
            print_error "your AWS credentials are valid for account $ACCOUNT_ID in $REGION."
            exit 1
        fi

        # Keep the successful case quiet, but never swallow a failure: docker's
        # own message is the only thing that says why the login did not take.
        if ! LOGIN_OUTPUT=$(printf '%s' "$ECR_PASSWORD" | \
                docker login --username AWS --password-stdin "$REGISTRY" 2>&1); then
            print_error "docker login failed for $REGISTRY"
            echo "$LOGIN_OUTPUT"
            print_error "ECR issued the authorization token, so the AWS side is fine."
            print_error "The local credential store is already bypassed for this login,"
            print_error "so this is not a keychain/credsStore problem. Check that the"
            print_error "docker daemon is running (\`docker version\`) and that the"
            print_error "registry is reachable."
            exit 1
        fi

        print_step "Building and pushing image..."
        echo "  Image: $IMAGE_URI"

        docker buildx build \
            --platform linux/arm64 \
            -t "$IMAGE_URI" \
            --push \
            "$SCRIPT_DIR/mcp-server"
    )
    release_docker_config

    echo -e "  ${GREEN}Image pushed successfully!${NC}"
else
    print_warning "Skipping Docker build (--skip-build)"
fi

# Deploy CDK stack (may need retry due to Gateway Target timing)
print_step "Deploying CDK stack..."

# First attempt
if JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run cdk deploy --require-approval never 2>&1; then
    echo "  Deployment succeeded on first attempt"
else
    # Check if it failed due to GatewayTarget timing issue
    STACK_STATUS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" --query "Stacks[0].StackStatus" --output text 2>/dev/null || echo "DOES_NOT_EXIST")

    if [ "$STACK_STATUS" = "ROLLBACK_COMPLETE" ]; then
        print_warning "First deployment failed (Runtime may need time to stabilize). Cleaning up and retrying..."

        # Delete the failed stack
        aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
        aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"

        # Wait for services to stabilize
        echo "  Waiting 30 seconds for services to stabilize..."
        sleep 30

        # Retry deployment
        print_step "Retrying deployment..."
        JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run cdk deploy --require-approval never
    else
        print_error "Deployment failed with status: $STACK_STATUS"
        exit 1
    fi
fi

# =====================================================================
# WAIT FOR GATEWAY TO BE READY
# =====================================================================
# The interceptor is deployed inline with CDK. Just wait for Gateway to be operational.

print_step "Waiting for Gateway to be READY..."

GATEWAY_ID=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`GatewayId`].OutputValue' \
    --output text)

echo "  Gateway ID: $GATEWAY_ID"

MAX_ATTEMPTS=60
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    STATUS=$(aws bedrock-agentcore-control get-gateway \
        --gateway-identifier "$GATEWAY_ID" \
        --region "$REGION" \
        --query 'status' \
        --output text 2>/dev/null || echo "PENDING")

    if [ "$STATUS" = "READY" ]; then
        echo "  Gateway is READY"
        break
    fi

    echo "  Gateway status: $STATUS, waiting... (attempt $((ATTEMPT+1))/$MAX_ATTEMPTS)"
    sleep 5
    ATTEMPT=$((ATTEMPT+1))
done

if [ "$STATUS" != "READY" ]; then
    print_error "Gateway did not become READY within timeout"
    exit 1
fi

# Verify interceptor is configured
echo "  Verifying interceptor configuration..."
INTERCEPTOR_COUNT=$(aws bedrock-agentcore-control get-gateway \
    --gateway-identifier "$GATEWAY_ID" \
    --region "$REGION" \
    --query 'length(interceptorConfigurations)' \
    --output text 2>/dev/null || echo "0")

if [ "$INTERCEPTOR_COUNT" -gt 0 ]; then
    echo -e "  ${GREEN}Interceptor configured successfully!${NC}"
else
    print_warning "Interceptor not found - check CDK deployment logs"
fi

# Get outputs and print demo command
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo ""
echo "  Run the full test suite:"
echo "     ./test.sh"
echo ""
echo "  This will create test users and verify all auth modes:"
echo "     - M2M mode (admin tools blocked - no user groups)"
echo "     - Admin user (full access)"
echo "     - Regular user (admin tools blocked)"
echo ""
