# Finance Agent

ReAct agent demo that connects to a **Neo4j Aura Agent MCP server** to answer questions about SEC filings, companies, risk factors, and institutional ownership.

```
User Query → LLM (Bedrock Claude) → Aura Agent MCP → Neo4j AuraDB
```

## Setup

```bash
cd agentcore-neo4j-mcp-agent/finance-agent
uv sync

export AURA_MCP_URL="https://your-aura-agent-mcp-endpoint"
export AURA_API_KEY="your-api-key"   # optional
```

## Run

```bash
uv run python simple-agent.py                             # Demo queries
uv run python simple-agent.py "Tell me about Apple Inc"   # Custom query
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AURA_MCP_URL` | Yes | Aura Agent MCP server URL |
| `AURA_API_KEY` | No | API key (sent as `x-api-key` header) |
| `MODEL_ID` | No | Bedrock model (default: Claude Sonnet) |
| `AWS_REGION` | No | AWS region (default: us-west-2) |
