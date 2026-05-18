#!/bin/bash
# Refresh the vendored neo4j-agent-memory wheel.
#
# neo4j-agent-memory is not on PyPI. direct_code_deploy uploads only the
# finance-agent/ directory to CodeBuild, so the dependency must ship as a
# wheel inside vendor/. Run this whenever the labs library changes.
#
# Usage:  scripts/vendor-memory.sh [path-to-agent-memory-checkout]
# Default checkout: ../../../../neo4j-labs/agent-memory (relative to project)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC="${1:-$PROJECT_DIR/../../../../neo4j-labs/agent-memory}"

if [ ! -f "$SRC/pyproject.toml" ]; then
    echo "ERROR: agent-memory checkout not found at: $SRC" >&2
    echo "Pass the path explicitly: scripts/vendor-memory.sh /path/to/agent-memory" >&2
    exit 1
fi

echo "Building wheel from: $SRC"
( cd "$SRC" && uv build --wheel )

WHEEL="$(ls -t "$SRC"/dist/neo4j_agent_memory-*-py3-none-any.whl | head -n1)"
WHEEL_NAME="$(basename "$WHEEL")"

rm -f "$PROJECT_DIR"/vendor/neo4j_agent_memory-*-py3-none-any.whl
mkdir -p "$PROJECT_DIR/vendor"
cp "$WHEEL" "$PROJECT_DIR/vendor/"
echo "Vendored: vendor/$WHEEL_NAME"

# pyproject.toml pins the wheel by exact filename; keep it in sync on a
# version bump, then relock so uv.lock matches (CodeBuild runs --frozen).
sed -i.bak -E \
    "s#(neo4j-agent-memory = \{ path = \")vendor/[^\"]+(\" \})#\1vendor/$WHEEL_NAME\2#" \
    "$PROJECT_DIR/pyproject.toml"
rm -f "$PROJECT_DIR/pyproject.toml.bak"

( cd "$PROJECT_DIR" && uv lock )
echo "Done. uv.lock updated — commit vendor/$WHEEL_NAME, pyproject.toml, uv.lock."
