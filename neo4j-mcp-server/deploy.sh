#!/bin/bash
#
# deploy.sh - Deploy Neo4j MCP Server to AgentCore
#
# This script deploys the official Neo4j MCP server to AWS Bedrock AgentCore
# using a Gateway REQUEST interceptor for header transformation. The interceptor
# transforms X-Neo4j-Authorization to Authorization, enabling per-request
# Neo4j credentials without modifying the official server.
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
# Required Environment Variables (via .env file):
#   NEO4J_URI           Neo4j database URI (e.g., neo4j+s://xxx.databases.neo4j.io)
#   NEO4J_USERNAME      Neo4j username (default: neo4j)
#   NEO4J_PASSWORD      Neo4j password
#
# Examples:
#   ./deploy.sh                    # Full deploy with image build
#   ./deploy.sh --skip-build       # Quick deploy, reuse existing image
#   ./deploy.sh --destroy          # Tear down the stack
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKIP_BUILD=false
DESTROY=false

# Default values (can be overridden by .env)
REGION="${AWS_REGION:-us-west-2}"
STACK_NAME="${STACK_NAME:-neo4j-mcp-server}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

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
    head -30 "$0" | tail -27 | sed 's/^#//' | sed 's/^ //'
    exit 0
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

# Load .env file if it exists
# This sets STACK_NAME, AWS_REGION, NEO4J_* and other configuration
if [ -f ".env" ]; then
    print_step "Loading configuration from .env..."
    set -a
    source .env
    set +a
fi

# Apply defaults after .env loading (command-line args take precedence)
STACK_NAME="${STACK_NAME:-neo4j-mcp-server}"
REGION="${AWS_REGION:-${REGION:-us-west-2}}"

# Export for CDK (app.py reads these)
export STACK_NAME
export AWS_REGION="$REGION"

# Check prerequisites
print_step "Checking prerequisites..."

if ! command -v aws &> /dev/null; then
    print_error "AWS CLI is not installed"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed"
    exit 1
fi

if ! command -v uv &> /dev/null; then
    print_error "uv is not installed. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Verify AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    print_error "AWS credentials are not configured or have expired"
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REPO_NAME="${STACK_NAME}-mcp-server"
echo "  AWS Account: $ACCOUNT_ID"
echo "  Region: $REGION"

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

# Validate required environment variables for deployment
if [ -z "$NEO4J_URI" ]; then
    print_error "NEO4J_URI is required but not set"
    echo ""
    echo "Create a .env file with the following variables:"
    echo ""
    echo "  NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io"
    echo "  NEO4J_USERNAME=neo4j"
    echo "  NEO4J_PASSWORD=your-password"
    echo ""
    exit 1
fi

echo "  Neo4j URI: $NEO4J_URI"
echo "  Neo4j Username: ${NEO4J_USERNAME:-neo4j}"

# Sync dependencies
print_step "Installing dependencies..."
uv sync --no-install-project --quiet

# =====================================================================
# ENSURE ECR REPOSITORY EXISTS (required for CDK even with --skip-build)
# =====================================================================
# The ECR repository must exist before CDK runs because it uses
# from_repository_name() to look it up. Create it here, outside the
# Docker build block.

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

    # Login to ECR
    print_step "Logging in to ECR..."
    aws ecr get-login-password --region "$REGION" | \
        docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com" > /dev/null

    # Copy local Neo4j MCP repo with HTTPAuthMode support into build context
    # NOTE: The HTTPAuthMode feature is pending PR merge to the official repo
    # Once merged, update Dockerfile to clone from github.com/neo4j/mcp instead
    MCP_SRC_DIR="$SCRIPT_DIR/mcp-server/neo4j-mcp-src"
    LOCAL_MCP_REPO="/Users/ryanknight/projects/mcp"

    if [ -d "$LOCAL_MCP_REPO" ]; then
        print_step "Copying local Neo4j MCP repo (with HTTPAuthMode support)..."
        rm -rf "$MCP_SRC_DIR"
        mkdir -p "$MCP_SRC_DIR"
        # Copy source files (exclude .git, .idea, etc.)
        rsync -a --exclude='.git' --exclude='.idea' --exclude='scripts' "$LOCAL_MCP_REPO/" "$MCP_SRC_DIR/"
        echo "  Copied from: $LOCAL_MCP_REPO"
    else
        print_error "Local Neo4j MCP repo not found at $LOCAL_MCP_REPO"
        print_error "The HTTPAuthMode feature is required but not in the official repo yet."
        exit 1
    fi

    # Build and push image
    IMAGE_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO_NAME:latest"
    print_step "Building and pushing image..."
    echo "  Image: $IMAGE_URI"

    docker buildx build \
        --platform linux/arm64 \
        -t "$IMAGE_URI" \
        --push \
        "$SCRIPT_DIR/mcp-server"

    # Clean up copied source
    rm -rf "$MCP_SRC_DIR"

    echo -e "  ${GREEN}Image pushed successfully!${NC}"
else
    print_warning "Skipping Docker build (--skip-build)"
    print_warning "Make sure the Docker image already exists in ECR!"
fi

# =====================================================================
# DEPLOY CDK STACK (with retry logic for timing issues)
# =====================================================================
# The CDK stack includes the Gateway with interceptor configuration.
# Gateway role has lambda:InvokeFunction permission for the interceptor.
# Sometimes the first deployment fails due to Runtime timing - retry if needed.

print_step "Deploying CDK stack..."

# First attempt
if JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run cdk deploy --require-approval never 2>&1; then
    echo "  Deployment succeeded"
else
    # Check if it failed due to timing issue
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

print_step "Waiting for Gateway to be READY..."

GATEWAY_ID=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`GatewayId`].OutputValue' \
    --output text)

GATEWAY_URL=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`GatewayUrl`].OutputValue' \
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

# Print success message
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Gateway URL: $GATEWAY_URL"
echo ""
echo "Neo4j credentials will be sent per-request via X-Neo4j-Authorization header."
echo "The Gateway interceptor transforms this to Authorization for the official server."
echo ""
echo "To test the deployment:"
echo ""
echo "  uv run python client/demo.py"
echo ""
