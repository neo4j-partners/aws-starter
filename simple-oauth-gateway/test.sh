#!/bin/bash
#
# test.sh - Full Test Suite for OAuth2 RBAC Demo
#
# Runs complete test suite including user creation and all auth modes:
#   1. Creates test users (admin and regular user)
#   2. M2M mode - Admin tools should be blocked (no user groups)
#   3. Admin user - Full access (member of admin group)
#   4. Regular user - Admin tools should be blocked (not in admin group)
#
# Usage:
#   ./test.sh              # Run full test suite (create users + all tests)
#   ./test.sh --skip-users # Skip user creation, run tests only
#   ./test.sh --m2m        # Test M2M mode only
#   ./test.sh --admin      # Test admin user only
#   ./test.sh --user       # Test regular user only
#
# Prerequisites:
#   Stack deployed: ./deploy.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test user credentials
ADMIN_USER="admin@example.com"
ADMIN_PASS="AdminPass123!"
REGULAR_USER="user@example.com"
REGULAR_PASS="UserPass123!"

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

print_header() {
    echo ""
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}============================================================${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_fail() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

print_step() {
    echo -e "${GREEN}==>${NC} $1"
}

# Validate test result
check_result() {
    local test_name="$1"
    local expected_pattern="$2"
    local output="$3"

    if echo "$output" | grep -qE "$expected_pattern"; then
        print_success "$test_name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        print_fail "$test_name"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo -e "${RED}Error: Virtual environment not found. Run ./deploy.sh first.${NC}"
    exit 1
fi

setup_users() {
    print_header "Setup: Creating Test Users"
    print_info "Creating admin and regular test users in Cognito..."
    echo ""

    python setup_users.py

    echo ""
    print_success "Test users created"
}

run_m2m_test() {
    print_header "Test 1: M2M Mode (client_credentials)"
    print_info "Expected: Echo works, admin tools BLOCKED (no user groups)"
    echo ""

    # Capture output
    OUTPUT=$(python client/demo.py --mode m2m 2>&1)

    # Show relevant output
    echo "$OUTPUT" | grep -E "(Result:|admin_action|Access denied)" | head -5

    echo ""
    echo "Validating results:"
    check_result "Echo tool succeeds" "Echo: Hello from RBAC demo" "$OUTPUT"
    check_result "Admin tool blocked (no groups)" "Access denied.*admin" "$OUTPUT"

    echo ""
    print_success "M2M test completed"
}

run_admin_test() {
    print_header "Test 2: Admin User Mode"
    print_info "User: $ADMIN_USER"
    print_info "Password: $ADMIN_PASS"
    print_info "Expected: Full access (member of 'admin' group)"
    echo ""

    # Capture output
    OUTPUT=$(echo "$ADMIN_PASS" | python client/demo.py --mode user --username "$ADMIN_USER" 2>&1)

    # Show relevant output
    echo "$OUTPUT" | grep -E "(Result:|User groups:|success)" | head -5

    echo ""
    echo "Validating results:"
    check_result "Echo tool succeeds" "Echo: Hello from RBAC demo" "$OUTPUT"
    check_result "User has admin group" "admin" "$OUTPUT"
    check_result "Admin tool succeeds" "success.*true|completed successfully" "$OUTPUT"

    echo ""
    print_success "Admin user test completed"
}

run_user_test() {
    print_header "Test 3: Regular User Mode"
    print_info "User: $REGULAR_USER"
    print_info "Password: $REGULAR_PASS"
    print_info "Expected: Admin tools BLOCKED (not in 'admin' group)"
    echo ""

    # Capture output
    OUTPUT=$(echo "$REGULAR_PASS" | python client/demo.py --mode user --username "$REGULAR_USER" 2>&1)

    # Show relevant output
    echo "$OUTPUT" | grep -E "(Result:|User groups:|Access denied)" | head -5

    echo ""
    echo "Validating results:"
    check_result "Echo tool succeeds" "Echo: Hello from RBAC demo" "$OUTPUT"
    check_result "User has only 'users' group" "Groups:.*users" "$OUTPUT"
    check_result "Admin tool blocked" "Access denied.*admin" "$OUTPUT"

    echo ""
    print_success "Regular user test completed"
}

print_summary() {
    print_header "Test Summary"

    TOTAL_TESTS=$((TESTS_PASSED + TESTS_FAILED))

    echo "Results:"
    echo -e "  ${GREEN}Passed:${NC} $TESTS_PASSED"
    echo -e "  ${RED}Failed:${NC} $TESTS_FAILED"
    echo "  Total:  $TOTAL_TESTS"
    echo ""

    if [ $TESTS_FAILED -eq 0 ]; then
        echo -e "${GREEN}All tests passed!${NC}"
        echo ""
        echo "RBAC Behavior Verified:"
        echo "  ✓ M2M tokens have no groups, admin tools blocked by interceptor"
        echo "  ✓ Admin users have 'admin' group, full access to all tools"
        echo "  ✓ Regular users have 'users' group only, admin tools blocked"
        echo "  ✓ Lambda interceptor enforces RBAC at the Gateway level"
        return 0
    else
        echo -e "${RED}Some tests failed!${NC}"
        echo ""
        echo "Check the output above for details."
        return 1
    fi
}

# Parse arguments
RUN_M2M=false
RUN_ADMIN=false
RUN_USER=false
RUN_ALL=true
SKIP_USERS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-users)
            SKIP_USERS=true
            shift
            ;;
        --m2m)
            RUN_M2M=true
            RUN_ALL=false
            shift
            ;;
        --admin)
            RUN_ADMIN=true
            RUN_ALL=false
            shift
            ;;
        --user)
            RUN_USER=true
            RUN_ALL=false
            shift
            ;;
        --help|-h)
            head -20 "$0" | tail -17 | sed 's/^#//' | sed 's/^ //'
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Check stack is deployed
print_step "Checking stack deployment..."
STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name SimpleOAuthDemo \
    --query "Stacks[0].StackStatus" \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$STACK_STATUS" != "CREATE_COMPLETE" ] && [ "$STACK_STATUS" != "UPDATE_COMPLETE" ]; then
    echo -e "${RED}Error: Stack not deployed (status: $STACK_STATUS). Run ./deploy.sh first.${NC}"
    exit 1
fi
print_success "Stack deployed (status: $STACK_STATUS)"

# Run tests
print_header "OAuth2 RBAC Demo - Full Test Suite"
echo "Testing role-based access control with different authentication modes."
echo ""
echo "Test cases:"
echo "  1. M2M mode - Uses client_credentials flow (no user groups)"
echo "  2. Admin user - Uses password auth (member of 'admin' group)"
echo "  3. Regular user - Uses password auth (member of 'users' only)"

if [ "$RUN_ALL" = true ]; then
    # Create users unless skipped
    if [ "$SKIP_USERS" = false ]; then
        setup_users
    else
        print_info "Skipping user creation (--skip-users)"
    fi

    run_m2m_test
    run_admin_test
    run_user_test
    print_summary
else
    # Individual tests (skip user creation)
    [ "$RUN_M2M" = true ] && run_m2m_test
    [ "$RUN_ADMIN" = true ] && run_admin_test
    [ "$RUN_USER" = true ] && run_user_test
    print_summary
fi

# Exit with appropriate code
if [ $TESTS_FAILED -eq 0 ]; then
    exit 0
else
    exit 1
fi
