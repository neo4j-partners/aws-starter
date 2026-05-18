#!/usr/bin/env bash
# Copy .mcp-credentials.json from neo4j-agentcore-mcp-server to agent directories
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/../neo4j-agentcore-mcp-server/.mcp-credentials.json"
TARGETS=("fleet-agent" "orchestrator-agent" "finance-agent")

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

if [ ! -f "$SOURCE" ]; then
    echo -e "${RED}ERROR: Source not found: $SOURCE${NC}"
    echo "Deploy the Neo4j MCP server first: cd ../neo4j-agentcore-mcp-server && ./deploy.sh"
    exit 1
fi

YELLOW='\033[0;33m'

synced=0
for target in "${TARGETS[@]}"; do
    target_dir="$SCRIPT_DIR/$target"
    if [ ! -d "$target_dir" ]; then
        echo -e "${YELLOW}WARNING: Skipping missing directory: $target${NC}"
        continue
    fi
    cp "$SOURCE" "$target_dir/.mcp-credentials.json"
    echo -e "${GREEN}Copied to $target/.mcp-credentials.json${NC}"
    synced=$((synced + 1))
done

echo "Done. Credentials synced to $synced of ${#TARGETS[@]} agent directories."
