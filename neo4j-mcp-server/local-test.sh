#!/bin/bash
#
# local-test.sh - Test the local Neo4j MCP Server Docker container
#
# Usage:
#   ./local-test.sh [OPTIONS]
#
# Options:
#   --tools             List available tools
#   --call TOOL ARGS    Call a specific tool with JSON arguments
#   --verbose           Show full response bodies
#   --help              Show this help message
#
# Examples:
#   ./local-test.sh                         # Run all tests
#   ./local-test.sh --tools                 # List tools
#   ./local-test.sh --call echo '{"message": "hello"}'
#   ./local-test.sh --call server_info '{}'
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8000
BASE_URL="http://localhost:$PORT"
VERBOSE=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_step() {
    echo -e "${GREEN}==>${NC} $1"
}

print_pass() {
    echo -e "  ${GREEN}✓${NC} $1"
}

print_fail() {
    echo -e "  ${RED}✗${NC} $1"
}

print_info() {
    echo -e "  ${BLUE}ℹ${NC} $1"
}

show_help() {
    head -18 "$0" | tail -15 | sed 's/^#//' | sed 's/^ //'
    exit 0
}

# MCP JSON-RPC request helper (parses SSE response to extract JSON)
mcp_request() {
    local method=$1
    local params=$2
    local id=${3:-1}

    local payload=$(cat <<EOF
{
    "jsonrpc": "2.0",
    "id": $id,
    "method": "$method",
    "params": $params
}
EOF
)

    # FastMCP returns SSE format, extract JSON from "data:" lines
    curl -s -X POST "$BASE_URL/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d "$payload" | grep "^data:" | sed 's/^data: //'
}

# Check if server is running
check_server() {
    if ! curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/" 2>/dev/null | grep -qE "200|404|405"; then
        echo -e "${RED}Error:${NC} Server is not running at $BASE_URL"
        echo ""
        echo "Start the server first with:"
        echo "  ./local-build.sh"
        exit 1
    fi
}

# Initialize MCP session
initialize_session() {
    local response=$(mcp_request "initialize" '{
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {
            "name": "local-test",
            "version": "1.0.0"
        }
    }')
    echo "$response"
}

# List available tools
list_tools() {
    print_step "Listing available tools..."

    # Initialize first
    initialize_session > /dev/null 2>&1

    local response=$(mcp_request "tools/list" '{}')

    if echo "$response" | grep -q '"tools"'; then
        echo "$response" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    tools = data.get('result', {}).get('tools', [])
    if tools:
        for tool in tools:
            name = tool.get('name', 'unknown')
            desc = tool.get('description', 'No description')
            print(f'  {name}')
            print(f'    {desc[:80]}...' if len(desc) > 80 else f'    {desc}')
            print()
    else:
        print('  No tools found')
except Exception as e:
    print(f'  Error parsing response: {e}')
"
    else
        print_fail "Failed to list tools"
        if [ "$VERBOSE" = true ]; then
            echo "$response"
        fi
    fi
}

# Call a specific tool
call_tool() {
    local tool_name=$1
    local tool_args=$2

    print_step "Calling tool: $tool_name"

    # Initialize first
    initialize_session > /dev/null 2>&1

    local response=$(mcp_request "tools/call" "{
        \"name\": \"$tool_name\",
        \"arguments\": $tool_args
    }")

    if echo "$response" | grep -q '"result"'; then
        echo "$response" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    result = data.get('result', {})
    content = result.get('content', [])
    for item in content:
        if item.get('type') == 'text':
            text = item.get('text', '')
            try:
                parsed = json.loads(text)
                print(json.dumps(parsed, indent=2))
            except:
                print(text)
except Exception as e:
    print(f'Error: {e}')
"
    else
        print_fail "Tool call failed"
        echo "$response"
    fi
}

# Run test suite
run_tests() {
    local passed=0
    local failed=0

    print_step "Running MCP server tests..."
    echo ""

    # Test 1: Initialize
    echo "Test 1: Initialize session"
    local init_response=$(initialize_session 2>&1)
    if echo "$init_response" | grep -q '"protocolVersion"'; then
        print_pass "Initialize succeeded"
        ((passed++))
    else
        print_fail "Initialize failed"
        if [ "$VERBOSE" = true ]; then
            echo "$init_response"
        fi
        ((failed++))
    fi

    # Test 2: List tools
    echo ""
    echo "Test 2: List tools"
    local tools_response=$(mcp_request "tools/list" '{}' 2)
    if echo "$tools_response" | grep -q '"echo"'; then
        print_pass "Tools list contains 'echo'"
        ((passed++))
    else
        print_fail "Tools list missing 'echo'"
        ((failed++))
    fi

    if echo "$tools_response" | grep -q '"server_info"'; then
        print_pass "Tools list contains 'server_info'"
        ((passed++))
    else
        print_fail "Tools list missing 'server_info'"
        ((failed++))
    fi

    # Test 3: Echo tool
    echo ""
    echo "Test 3: Call echo tool"
    local echo_response=$(mcp_request "tools/call" '{
        "name": "echo",
        "arguments": {"message": "test123"}
    }' 3)
    if echo "$echo_response" | grep -q "test123"; then
        print_pass "Echo returned expected message"
        ((passed++))
    else
        print_fail "Echo did not return expected message"
        if [ "$VERBOSE" = true ]; then
            echo "$echo_response"
        fi
        ((failed++))
    fi

    # Test 4: Server info
    echo ""
    echo "Test 4: Call server_info tool"
    local info_response=$(mcp_request "tools/call" '{
        "name": "server_info",
        "arguments": {}
    }' 4)
    if echo "$info_response" | grep -q "Neo4j MCP Server"; then
        print_pass "Server info returned expected data"
        ((passed++))
    else
        print_fail "Server info did not return expected data"
        if [ "$VERBOSE" = true ]; then
            echo "$info_response"
        fi
        ((failed++))
    fi

    # Print summary
    echo ""
    echo "========================================"
    echo -e "Results: ${GREEN}$passed passed${NC}, ${RED}$failed failed${NC}"
    echo "========================================"

    if [ $failed -gt 0 ]; then
        exit 1
    fi
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --tools)
            check_server
            list_tools
            exit 0
            ;;
        --call)
            if [ -z "$2" ] || [ -z "$3" ]; then
                print_fail "Usage: --call TOOL_NAME '{\"args\": \"value\"}'"
                exit 1
            fi
            check_server
            call_tool "$2" "$3"
            exit 0
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            show_help
            ;;
        *)
            print_fail "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Default: run test suite
check_server
run_tests
