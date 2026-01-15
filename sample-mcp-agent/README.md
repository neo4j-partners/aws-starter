# Neo4j MCP Agent

A ReAct agent that connects to the Neo4j MCP server via AWS Bedrock AgentCore Gateway and answers natural language questions using Claude.

## Quick Start

```bash
# Install dependencies
./agent.sh setup

# Copy credentials from simple-neo4j-mcp-server deployment
cp ../simple-neo4j-mcp-server/.mcp-credentials.json .

# Run demo queries
./agent.sh

# Ask a question
./agent.sh "How many aircraft are in the database?"
```

## Two Agent Versions

| File | Description |
|------|-------------|
| `simple-agent.py` | Basic agent using bearer token auth (no token refresh) |
| `agent.py` | Production agent with automatic OAuth2 token refresh |

### Simple Agent (basic)

Uses the `access_token` from credentials file directly. Good for testing.

```bash
uv run python simple-agent.py                      # Run demo
uv run python simple-agent.py "What is the schema?"
```

### Production Agent (with token refresh)

Auto-refreshes expired tokens using OAuth2 client credentials flow.

```bash
./agent.sh                      # Run demo
./agent.sh "What is the schema?"
```

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   User Input    │────▶│  LangGraph Agent │────▶│   AgentCore     │
│  (Natural Lang) │     │  (ReAct Pattern) │     │    Gateway      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │                        │
                               │ MCP Protocol           │ OAuth2 JWT
                               │ over HTTP              │
                               ▼                        ▼
                        ┌──────────────────┐     ┌─────────────────┐
                        │   langchain-mcp  │     │   Neo4j MCP     │
                        │    -adapters     │     │    Server       │
                        └──────────────────┘     └─────────────────┘
                               │
                               │ AWS Bedrock
                               ▼
                        ┌──────────────────┐
                        │  Claude Sonnet 4 │
                        │  (Converse API)  │
                        └──────────────────┘
```

## Configuration

### Credentials File

Copy `.mcp-credentials.json` from your `simple-neo4j-mcp-server` deployment:

```bash
cp ../simple-neo4j-mcp-server/.mcp-credentials.json .
```

Required fields:

| Field | Description |
|-------|-------------|
| `gateway_url` | AgentCore Gateway endpoint URL |
| `token_url` | Cognito token endpoint for OAuth2 |
| `client_id` | OAuth2 client ID |
| `client_secret` | OAuth2 client secret |
| `scope` | OAuth2 scope for MCP invocation |
| `region` | AWS region for Bedrock access |

The agent automatically refreshes tokens when they expire using the client credentials flow.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_CREDENTIALS_FILE` | Path to credentials file | `.mcp-credentials.json` |
| `AWS_REGION` | AWS region (overrides credentials) | From credentials |
| `AWS_PROFILE` | AWS CLI profile to use | default |

## Commands

| Command | Description |
|---------|-------------|
| `./agent.sh` | Run demo queries |
| `./agent.sh "<question>"` | Ask a question |
| `./agent.sh setup` | Install dependencies |
| `./agent.sh help` | Show help |

## Example Questions (Aircraft Maintenance Database)

```bash
./agent.sh "What is the database schema?"
./agent.sh "How many aircraft are in the database?"
./agent.sh "Show aircraft with recent maintenance events"
./agent.sh "What sensors monitor the engines?"
./agent.sh "Find components needing attention"
./agent.sh "List 5 airports with their city and country"
./agent.sh "Show me 3 recent maintenance events with their severity"
```

## Example Output

```
======================================================================
Neo4j MCP Agent
======================================================================

Loading credentials...
Refreshing OAuth2 token...
Token refreshed. New expiry: 2026-01-06T21:10:25.158870+00:00

Gateway: https://your-gateway.amazonaws.com/mcp
Token expires: 2026-01-06T21:10:25.158870+00:00

Initializing LLM (Bedrock, region: us-west-2)...
Using: us.anthropic.claude-sonnet-4-20250514-v1:0

Connecting to MCP server...
Loaded 3 tools:
  - neo4j-mcp-server-target___get-schema
  - neo4j-mcp-server-target___read-cypher
  - neo4j-mcp-server-target___write-cypher

Creating agent...
======================================================================
Question: How many Aircraft are in the database?
======================================================================

Answer:
----------------------------------------------------------------------
There are **60 Aircraft** in the database.
----------------------------------------------------------------------
```

## Gateway Tool Naming

When tools are accessed via AgentCore Gateway, they include a target prefix:

```
{target-name}___{tool-name}
```

For example: `neo4j-mcp-server-target___get-schema`

The `langchain-mcp-adapters` library handles this automatically - the LLM sees the full prefixed names and uses them correctly.

## Prerequisites

1. **Python 3.10+** - Required runtime
2. **uv** - Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
3. **AWS CLI** - Configured with credentials that have Bedrock access
4. **Deployed Neo4j MCP Server** - `simple-neo4j-mcp-server` with AgentCore Gateway

## How It Works

1. **Load Credentials**: Reads gateway URL and OAuth2 credentials from `.mcp-credentials.json`
2. **Auto-Refresh Token**: If token is expired or expiring soon, refreshes using client credentials
3. **Initialize LLM**: Creates AWS Bedrock Claude client via Converse API
4. **Connect to MCP**: Uses `MultiServerMCPClient` with streamable HTTP transport
5. **Load Tools**: Discovers and converts MCP tools to LangChain format
6. **Create Agent**: Builds ReAct agent with system prompt for database queries
7. **Process Query**: Agent reasons, calls tools, and returns formatted answer

## Troubleshooting

### Token Refresh Failed
```
ERROR: Token refresh failed: 401
```
Check that `client_id` and `client_secret` in `.mcp-credentials.json` are correct.

### AWS Credentials Not Found
```
botocore.exceptions.NoCredentialsError
```
Configure AWS CLI: `aws configure` or set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.

### Bedrock Access Denied
```
AccessDeniedException: You don't have access to the model
```
Enable Claude Sonnet 4 model access in your AWS Bedrock console.

### Connection Failed
```
httpx.ConnectError
```
Verify the gateway URL is correct and the MCP server is deployed.

## Dependencies

```toml
[project]
dependencies = [
    "langgraph>=0.2.0",
    "langchain-mcp-adapters>=0.1.0",
    "langchain-aws>=0.2.0",
    "httpx>=0.27.0",
    "boto3>=1.35.0",
]
```

## References

- [simple-neo4j-mcp-server](../simple-neo4j-mcp-server/) - The MCP server this agent connects to
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [AWS Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html)
