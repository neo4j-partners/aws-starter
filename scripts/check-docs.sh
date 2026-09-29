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
    "scripts/check-docs.sh"
)

# Names retired by the reorganization. Each is a Perl-compatible regular
# expression, matched case-insensitively. A name joins this list in the phase
# that removes it. (?-i) makes a name case-sensitive:
# E2E-TEST-PLAN was the old file name, and e2e-test-plan.md is the current one.
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
    "finance-(server|cli|demo|invoke|traffic)(?![-\\w])"
    "finance_graph"
    "(?<![-\\w])aura-agents\\b"
    "simple-oauth-(gateway|mcp-server)"
    "neo4j-agentcore-"
    "orchestrator"
    "finance[-_ ]agent"
    "finance-graph-(load|enrich|analyze)"
    "simple-neo4j-mcp-server"
    "databrick(?!s)"
    "fintech-demo"
    "(?-i)E2E-TEST-PLAN"
    "FIX_32"
    "FINANCE_AGENTCORE"
    "\\.env\\.example"
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

# Retired everywhere except the end-to-end test plan, whose run history
# records the old fleet_agent Runtime and the old fleet-agent/ folder.
RETIRED_OUTSIDE_E2E_HISTORY=(
    "fleet[-_ ]agent"
)
E2E_HISTORY_PATHS=(
    "demos/aircraft-fleet/docs/e2e-test-plan.md"
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
    local notebooks=()
    local file
    while IFS= read -r file; do
        [ -f "$file" ] || continue
        case "$file" in
            *.ipynb) notebooks+=("$file") ;;
            *) files+=("$file") ;;
        esac
    done < <(
        git ls-files --cached --others --exclude-standard -- \
            '*.md' '*.ipynb' $(git_pathspec_excludes)
    )

    local status=0
    echo "Checking relative links in ${#files[@]} files..."
    lychee --offline --no-progress "${files[@]}" || status=1

    # lychee reads .ipynb as plain text and finds no relative links, so
    # check each notebook's markdown cells as Markdown, resolved from the
    # notebook's own folder.
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    echo "Checking relative links in ${#notebooks[@]} notebooks..."
    for file in "${notebooks[@]}"; do
        if ! python3 - "$file" > "$tmp_dir/cells.md" <<'EOF'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    cells = json.load(f)["cells"]
for cell in cells:
    if cell["cell_type"] == "markdown":
        print("".join(cell["source"]), end="\n\n")
EOF
        then
            echo -e "${RED}Could not read markdown cells from $file${NC}"
            status=1
            continue
        fi
        if ! lychee --offline --no-progress \
            --base-url "file://$ROOT_DIR/$(dirname "$file")/" \
            "$tmp_dir/cells.md" >"$tmp_dir/out.txt" 2>&1; then
            echo -e "${RED}Broken links in $file:${NC}"
            cat "$tmp_dir/out.txt"
            status=1
        fi
    done
    rm -rf "$tmp_dir"
    return "$status"
}

grep_names() {
    local pattern="$1"
    shift
    git grep --untracked -n -I -i -P "$pattern" -- . $(git_pathspec_excludes "$@")
}

# Returns 1 when the pattern is found or git grep fails, 0 when it is clean.
check_pattern() {
    local rc=0
    grep_names "$@" || rc=$?
    case "$rc" in
        0) return 1 ;;
        1) return 0 ;;
        *)
            echo -e "${RED}git grep failed (exit $rc) on pattern: $1${NC}"
            return 1
            ;;
    esac
}

check_names() {
    local found=0
    local name
    if [ ${#RETIRED_NAMES[@]} -eq 0 ] \
        && [ ${#RETIRED_OUTSIDE_GATEWAY_PATTERN[@]} -eq 0 ] \
        && [ ${#RETIRED_OUTSIDE_E2E_HISTORY[@]} -eq 0 ]; then
        echo "No retired names are listed yet."
        return 0
    fi

    for name in "${RETIRED_NAMES[@]}"; do
        check_pattern "$name" || found=1
    done
    for name in "${RETIRED_OUTSIDE_GATEWAY_PATTERN[@]}"; do
        check_pattern "$name" "${GATEWAY_PATTERN_PATHS[@]}" || found=1
    done
    for name in "${RETIRED_OUTSIDE_E2E_HISTORY[@]}"; do
        check_pattern "$name" "${E2E_HISTORY_PATHS[@]}" || found=1
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
