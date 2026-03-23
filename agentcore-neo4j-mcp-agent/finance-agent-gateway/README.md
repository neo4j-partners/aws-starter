# Finance Agent (AgentCore Gateway)

A simple ReAct agent for financial data analysis that connects to the Neo4j MCP server via AgentCore Gateway.

## Setup

```bash
# Copy credentials from the MCP server deployment
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .

# Install dependencies
uv sync
```

## Usage

```bash
# Run demo queries (SEC filings, companies, risk factors)
uv run python simple-agent.py

# Ask a specific question
uv run python simple-agent.py "What companies are in the database?"
uv run python simple-agent.py "Who are the largest institutional owners of NVIDIA?"
```

## Prerequisites

- Neo4j MCP server deployed to AgentCore (see `neo4j-agentcore-mcp-server/`)
- Valid `.mcp-credentials.json` with a current `access_token`
- AWS credentials configured with Bedrock model access (Claude Sonnet)

If the token has expired, regenerate credentials:

```bash
cd ../../neo4j-agentcore-mcp-server
./deploy.sh credentials
cd -
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
```
