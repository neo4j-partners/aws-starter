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

if ! command -v python3 &> /dev/null; then
    print_error "Python3 is not installed. Please install it first."
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

# Setup Python virtual environment
print_step "Setting up Python environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

# Handle destroy
if [ "$DESTROY" = true ]; then
    print_step "Destroying stack..."
    JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 cdk destroy --force
    
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

    # Login to ECR
    print_step "Logging in to ECR..."
    aws ecr get-login-password --region "$REGION" | \
        docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com" > /dev/null

    # Build and push image
    IMAGE_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO_NAME:latest"
    print_step "Building and pushing image..."
    echo "  Image: $IMAGE_URI"

    docker buildx build \
        --platform linux/arm64 \
        -t "$IMAGE_URI" \
        --push \
        "$SCRIPT_DIR/mcp-server"

    echo -e "  ${GREEN}Image pushed successfully!${NC}"
else
    print_warning "Skipping Docker build (--skip-build)"
fi

# Deploy CDK stack (may need retry due to Gateway Target timing)
print_step "Deploying CDK stack..."

# First attempt
if JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 cdk deploy --require-approval never 2>&1; then
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
        JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 cdk deploy --require-approval never
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
