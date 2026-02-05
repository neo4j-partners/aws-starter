#!/usr/bin/env bash
# Copy .mcp-credentials.json from neo4j-agentcore-mcp-server to agent directories
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/../neo4j-agentcore-mcp-server/.mcp-credentials.json"
TARGETS=("basic-agent" "orchestrator-agent")

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

if [ ! -f "$SOURCE" ]; then
    echo -e "${RED}ERROR: Source not found: $SOURCE${NC}"
    echo "Deploy the Neo4j MCP server first: cd ../neo4j-agentcore-mcp-server && ./deploy.sh"
    exit 1
fi

for target in "${TARGETS[@]}"; do
    dest="$SCRIPT_DIR/$target/.mcp-credentials.json"
    cp "$SOURCE" "$dest"
    echo -e "${GREEN}Copied to $target/.mcp-credentials.json${NC}"
done

echo "Done. Credentials synced to ${#TARGETS[@]} agent directories."
