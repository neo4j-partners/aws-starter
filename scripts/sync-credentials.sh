#!/usr/bin/env bash
# Copy MCP server credentials from neo4j-mcp-server to each client directory.
# Each target gets the credentials for the deployment that serves its dataset.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_SERVER_DIR="$SCRIPT_DIR/../neo4j-mcp-server"

# Each entry is "target directory:source credentials file".
TARGETS=(
    "../quickstart:.mcp-credentials.json"
    "../demos/aircraft-fleet/supervisor-agent:.mcp-credentials.fleet.json"
    "../demos/fraud-amazon-quick/fraud-memory-agent:.mcp-credentials.finance.json"
)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

synced=0
for entry in "${TARGETS[@]}"; do
    target="${entry%%:*}"
    source_name="${entry#*:}"
    source_file="$MCP_SERVER_DIR/$source_name"
    target_dir="$SCRIPT_DIR/$target"

    if [ ! -d "$target_dir" ]; then
        echo -e "${YELLOW}WARNING: Skipping missing directory: $target${NC}"
        continue
    fi
    if [ ! -f "$source_file" ]; then
        env_name="${source_name#.mcp-credentials}"
        env_name="${env_name%.json}"
        env_name="${env_name#.}"
        env_flag="${env_name:+ --env $env_name}"
        echo -e "${YELLOW}WARNING: Skipping $target. Source not found: $source_file${NC}"
        echo "  Deploy the Neo4j MCP server first:"
        echo "  cd neo4j-mcp-server && ./deploy.py$env_flag && ./deploy.py$env_flag credentials"
        continue
    fi

    cp "$source_file" "$target_dir/.mcp-credentials.json"
    echo -e "${GREEN}Copied $source_name to $target/.mcp-credentials.json${NC}"
    synced=$((synced + 1))
done

if [ "$synced" -eq 0 ]; then
    echo -e "${RED}ERROR: No credentials were synced.${NC}"
    exit 1
fi
echo "Done. Credentials synced to $synced of ${#TARGETS[@]} directories."
