#!/bin/bash
#
# local-build.sh - Build and run Neo4j MCP Server Docker image locally
#
# Usage:
#   ./local-build.sh [OPTIONS]
#
# Options:
#   --stop              Stop the running container
#   --logs              Show container logs
#   --shell             Start shell in container
#   --rebuild           Force rebuild the image
#   --help              Show this help message
#
# Environment Variables (optional):
#   NEO4J_URI           Neo4j connection URI
#   NEO4J_USERNAME      Neo4j username (default: neo4j)
#   NEO4J_PASSWORD      Neo4j password
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="neo4j-mcp-server-local"
CONTAINER_NAME="neo4j-mcp-local"
PORT=8000

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_step() {
    echo -e "${GREEN}==>${NC} $1"
}

print_info() {
    echo -e "${BLUE}   ${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}Warning:${NC} $1"
}

print_error() {
    echo -e "${RED}Error:${NC} $1"
}

show_help() {
    head -19 "$0" | tail -16 | sed 's/^#//' | sed 's/^ //'
    exit 0
}

stop_container() {
    if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
        print_step "Stopping container..."
        docker stop "$CONTAINER_NAME" > /dev/null
        echo "  Container stopped"
    else
        print_info "Container is not running"
    fi

    if docker ps -aq -f name="$CONTAINER_NAME" | grep -q .; then
        docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
    fi
}

show_logs() {
    if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
        docker logs -f "$CONTAINER_NAME"
    else
        print_error "Container is not running"
        exit 1
    fi
}

start_shell() {
    if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
        docker exec -it "$CONTAINER_NAME" /bin/bash
    else
        print_error "Container is not running"
        exit 1
    fi
}

# Parse arguments
REBUILD=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --stop)
            stop_container
            exit 0
            ;;
        --logs)
            show_logs
            exit 0
            ;;
        --shell)
            start_shell
            exit 0
            ;;
        --rebuild)
            REBUILD=true
            shift
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

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed"
    exit 1
fi

if ! docker info &> /dev/null; then
    print_error "Docker daemon is not running. Please start Docker first."
    exit 1
fi

echo "  Docker is available"

# Stop existing container if running
if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
    print_step "Stopping existing container..."
    docker stop "$CONTAINER_NAME" > /dev/null
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
fi

# Build image if needed
IMAGE_EXISTS=$(docker images -q "$IMAGE_NAME" 2>/dev/null)
if [ -z "$IMAGE_EXISTS" ] || [ "$REBUILD" = true ]; then
    print_step "Building Docker image..."
    docker build -t "$IMAGE_NAME" "$SCRIPT_DIR/mcp-server"
    echo -e "  ${GREEN}Image built successfully!${NC}"
else
    print_info "Using existing image (use --rebuild to force rebuild)"
fi

# Prepare environment variables
ENV_ARGS=""
if [ -n "$NEO4J_URI" ]; then
    ENV_ARGS="$ENV_ARGS -e NEO4J_URI=$NEO4J_URI"
fi
if [ -n "$NEO4J_USERNAME" ]; then
    ENV_ARGS="$ENV_ARGS -e NEO4J_USERNAME=$NEO4J_USERNAME"
fi
if [ -n "$NEO4J_PASSWORD" ]; then
    ENV_ARGS="$ENV_ARGS -e NEO4J_PASSWORD=$NEO4J_PASSWORD"
fi

# Run container
print_step "Starting container..."
docker run -d \
    --name "$CONTAINER_NAME" \
    -p "$PORT:8000" \
    $ENV_ARGS \
    "$IMAGE_NAME" > /dev/null

# Wait for server to be ready
print_step "Waiting for server to be ready..."
MAX_WAIT=30
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s "http://localhost:$PORT/health" > /dev/null 2>&1 || \
       curl -s "http://localhost:$PORT/mcp" > /dev/null 2>&1 || \
       curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/" 2>/dev/null | grep -qE "200|405"; then
        break
    fi
    sleep 1
    WAITED=$((WAITED + 1))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    print_warning "Server may not be fully ready (timeout after ${MAX_WAIT}s)"
    print_info "Check logs with: ./local-build.sh --logs"
else
    echo "  Server is ready!"
fi

# Print success message
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Local MCP Server Running${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  Container:  $CONTAINER_NAME"
echo "  Port:       $PORT"
echo "  Endpoint:   http://localhost:$PORT/mcp"
echo ""
echo "Commands:"
echo "  ./local-test.sh              # Run tests"
echo "  ./local-build.sh --logs      # View logs"
echo "  ./local-build.sh --shell     # Open shell in container"
echo "  ./local-build.sh --stop      # Stop container"
echo ""
