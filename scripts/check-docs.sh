#!/usr/bin/env bash
# Check documentation for broken relative links and retired names.
#
# Usage:
#   scripts/check-docs.sh            Run both checks
#   scripts/check-docs.sh links      Check relative links only
#   scripts/check-docs.sh names      Check retired names only
#
# Requires lychee (brew install lychee) for the link check.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Paths that may name old folders or packages on purpose.
EXCLUDED_PATHS=(
    "docs/slides/archive/"
    "docs/proposals/"
    "organize.md"
    "organize-audit-log.md"
    "scripts/check-docs.sh"
)

# Names retired by the reorganization. Each is a Perl-compatible regular
# expression. A name joins this list in the phase that removes it.
# data-agent is followed by a lookahead so the real S3 bucket names, such as
# data-agent-neo4j-euw1, still pass. The Databricks integration has its own
# neo4j_mcp_agent.py, so only the quickstart module paths are retired.
RETIRED_NAMES=(
    "neo4j-agentcore-agents"
    "neo4j-agentcore-mcp-server"
    "infra[-_]samples"
    "databrick[-_]samples"
    "fleet-agent-demo"
    "data-agent(?!-)"
    "langgraph-mcp-agent"
    "neo4j_mcp_agent[./](agent|simple_agent|core)\\b"
    "bedrock-graphrag-pipeline"
    "neo4j-fleet-agent"
    "neo4j-orchestrator-agent"
    "orchestrator-(server|invoke)"
    "sec-filings-graphrag-demo"
    "finance-agent"
    "finance-(server|cli|demo|invoke|traffic)\\b"
    "finance_graph"
    "(?<![-/\\w])aura-agents\\b"
    "simple-oauth-(gateway|mcp-server)"
)

# Retired everywhere except the gateway RBAC pattern, which has its own
# deploy.sh. CLAUDE.md lists the gateway pattern commands, so it is also
# allowed.
RETIRED_OUTSIDE_GATEWAY_PATTERN=(
    "deploy\\.sh"
)
GATEWAY_PATTERN_PATHS=(
    "patterns/gateway-rbac-interceptor/"
    "CLAUDE.md"
)

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

git_pathspec_excludes() {
    local path
    for path in "${EXCLUDED_PATHS[@]}" "$@"; do
        printf ':(exclude)%s\n' "$path"
    done
    printf ':(exclude,glob)**/uv.lock\n'
}

check_links() {
    if ! command -v lychee >/dev/null 2>&1; then
        echo -e "${RED}lychee is not installed. Run: brew install lychee${NC}"
        return 1
    fi

    local files=()
    local file
    while IFS= read -r file; do
        [ -f "$file" ] && files+=("$file")
    done < <(
        git ls-files --cached --others --exclude-standard -- \
            '*.md' '*.ipynb' $(git_pathspec_excludes)
    )

    echo "Checking relative links in ${#files[@]} files..."
    lychee --offline --no-progress "${files[@]}"
}

grep_names() {
    local pattern="$1"
    shift
    git grep --untracked -n -I -P "$pattern" -- . $(git_pathspec_excludes "$@")
}

check_names() {
    local found=0
    local name
    if [ ${#RETIRED_NAMES[@]} -eq 0 ] \
        && [ ${#RETIRED_OUTSIDE_GATEWAY_PATTERN[@]} -eq 0 ]; then
        echo "No retired names are listed yet."
        return 0
    fi

    for name in "${RETIRED_NAMES[@]}"; do
        if grep_names "$name"; then
            found=1
        fi
    done
    for name in "${RETIRED_OUTSIDE_GATEWAY_PATTERN[@]}"; do
        if grep_names "$name" "${GATEWAY_PATTERN_PATHS[@]}"; then
            found=1
        fi
    done

    if [ "$found" -ne 0 ]; then
        echo -e "${RED}Retired names found. Update the lines above.${NC}"
        return 1
    fi
    echo "No retired names found."
}

mode="${1:-all}"
status=0
case "$mode" in
    links) check_links || status=1 ;;
    names) check_names || status=1 ;;
    all)
        check_links || status=1
        check_names || status=1
        ;;
    *)
        echo "Usage: $0 [links|names|all]"
        exit 2
        ;;
esac

if [ "$status" -eq 0 ]; then
    echo -e "${GREEN}Documentation checks passed.${NC}"
fi
exit "$status"
