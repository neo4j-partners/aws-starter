# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository demonstrates deploying a **Neo4j MCP server to Amazon Bedrock AgentCore** and building AI agents that connect to it. The core workflow:

1. **Deploy MCP server** (Neo4j graph database tools) to AgentCore Runtime
2. **Connect AI agents** via AgentCore Gateway with OAuth2 authentication
3. **Explore patterns** for multi-agent orchestration, SageMaker notebooks, and Databricks integration

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) for detailed diagrams and component descriptions.

## Common Commands

### Neo4j MCP Server Deployment

```bash
cd neo4j-mcp-server

./deploy.py                  # Full deployment (build, push, CDK stack)
./deploy.py credentials      # Generate .mcp-credentials.json (required after deploy)
./deploy.py status           # Show stack status and outputs
./deploy.py redeploy         # Fast redeploy (build, push, update runtime)
./deploy.py cleanup          # Delete all AWS resources

# Testing
./cloud.sh                   # Test via Gateway (recommended)
./cloud.sh token             # Check token expiry
./cloud.sh tools             # List MCP tools
./cloud-http.sh              # Test direct Runtime (debugging)
./local.sh start             # Start local Docker server (no auth)
./local.sh test              # Test local server

# Named deployments: --env NAME reads .env.NAME, writes .mcp-credentials.NAME.json
./deploy.py --env fleet     # Aircraft fleet graph (supervisor-agent)
./deploy.py --env finance   # Fraud graph (fraud-memory-agent)

# Copy each deployment's credentials to the samples that use it
../scripts/sync-credentials.sh
```

### Quickstart: LangGraph Agent (Standalone)

```bash
cd quickstart

# Copy credentials from MCP server deployment
cp ../neo4j-mcp-server/.mcp-credentials.json .

uv sync                      # Install dependencies
./agent.sh "query"           # Run production agent (auto-refresh OAuth2)
uv run python -m neo4j_mcp_quickstart.simple_agent "query"  # Simple agent (static token)

# SageMaker Unified Studio inference profiles
./inference-profiles/setup-inference-profile.sh haiku     # Create haiku profile
./inference-profiles/setup-inference-profile.sh sonnet    # Create sonnet profile
./inference-profiles/setup-inference-profile.sh --list    # Show profiles with magic tag
./inference-profiles/setup-inference-profile.sh --test haiku  # Create and test
```

### Aircraft Fleet Demo

End-to-end GraphRAG demo. The pipeline populates Neo4j. The GraphRAG agent
answers questions over it with a direct Neo4j driver, with no MCP and no
Gateway. The supervisor agent queries the same graph through the MCP Gateway.
Point everything at the same Neo4j instance with a matching embedder.

```bash
cd demos/aircraft-fleet
cp .env.sample .env              # shared by pipeline/ and graphrag-agent/

# Step 1: populate the graph
cd pipeline
uv sync
./setup.sh                       # five-stage ingest (LOAD_FULL_DATASET=true for full)

# Step 2: run the GraphRAG agent locally
cd ../graphrag-agent
uv sync
uv run fleet-server              # Terminal 1 (port 7070)
uv run fleet-cli "How many aircraft are in the database?"   # Terminal 2
uv run fleet-demo

# Step 3: deploy to AgentCore Runtime (optional)
./agent.sh configure
./agent.sh deploy
./agent.sh invoke-cloud "query"

# Step 4: supervisor agent over the MCP Gateway (needs ./deploy.py --env fleet)
cd ../supervisor-agent
./agent.sh start
./agent.sh test-maintenance  # Test routing to Maintenance Agent
./agent.sh test-operations   # Test routing to Operations Agent
./agent.sh deploy
./agent.sh load-test         # Continuous cloud testing
```

### Fraud Investigation Demo

```bash
# Graph loader: loads data/ into Neo4j with a direct driver.
# Reads NEO4J_* from graph-loader/.env.
cd demos/fraud-amazon-quick/graph-loader
uv sync
uv run fraud-graph-load          # --reset deletes all graph data first
uv run fraud-graph-enrich        # GDS risk, community, and similarity signals
uv run fraud-graph-analyze       # read-only investigation queries

# Fraud memory agent: Strands agent over its own core/. agent.sh and
# Dockerfile live at the agent root; runtime_app.py is in server/.
# Needs ./deploy.py --env finance.
cd ../fraud-memory-agent
uv sync
uv run fraud-server              # Terminal 1 (port 7020)
uv run fraud-cli "Find circular transfer chains"   # Terminal 2
./agent.sh deploy
# (configure/deploy/status/verify/logs/reset-config/destroy)
```

### Integrations and Patterns

```bash
# OAuth2 Gateway with RBAC Lambda interceptor
cd patterns/gateway-rbac-interceptor
uv sync && uv run cdk bootstrap   # bootstrap first time only
./deploy.sh
uv run python setup_users.py
./test.sh
./deploy.sh --destroy

# Neo4j Aura Agents REST client
cd integrations/neo4j-aura-agents
uv sync
uv run python cli.py "What's in the graph?"
```

### Databricks Integration

```bash
cd integrations/databricks

# Configure secrets from MCP server credentials
./setup_databricks_secrets.sh

# Then import notebooks into Databricks workspace:
# - neo4j-mcp-http-connection.ipynb (setup HTTP connection)
# - neo4j-mcp-agent-deploy.ipynb (deploy LangGraph agent)
```

### Dependency Management (uv)

```bash
uv sync                              # Install dependencies
uv add <package>                     # Add dependency
uv run python script.py              # Run in venv
uv run cdk deploy                    # Run CDK commands
```

## Architecture

### Core Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **Neo4j MCP Server** | `neo4j-mcp-server/` | MCP server on AgentCore Runtime with Gateway auth |
| **Quickstart** | `quickstart/` | Standalone LangGraph ReAct agent, notebooks for SageMaker |
| **Aircraft Fleet Demo** | `demos/aircraft-fleet/` | GraphRAG pipeline, direct-to-Neo4j GraphRAG agent, and MCP supervisor agent |
| **Fraud Investigation Demo** | `demos/fraud-amazon-quick/` | Graph loader, fraud memory agent, and Iceberg loaders for Amazon Quick |
| **SEC Filings GraphRAG** | `demos/sec-filings-graphrag/` | Four levels of GraphRAG retrieval in one notebook |
| **Databricks Integration** | `integrations/databricks/` | Unity Catalog HTTP connection integration |
| **Neo4j Aura Agents** | `integrations/neo4j-aura-agents/` | REST client for Neo4j-hosted Aura Agents |
| **Gateway RBAC Pattern** | `patterns/gateway-rbac-interceptor/` | Cognito RBAC with a Lambda interceptor at the Gateway |

### Request Flow

```
Agent → Cognito (client_credentials) → JWT Token
Agent → Gateway + JWT → validates token
Gateway → OAuth Provider → Runtime token
Gateway → Runtime → MCP Server → Neo4j
```

### Gateway Tool Naming

MCP tools accessed via Gateway are prefixed with target name:
```
{target-name}___{tool-name}
```
Example: `neo4j-mcp-server-target___read-cypher`

### Authentication Layers

| Layer | Purpose |
|-------|---------|
| Cognito OAuth2 | M2M token for agent → Gateway |
| Gateway JWT | Validates agent identity |
| OAuth2 Provider | Gateway → Runtime token exchange |
| Neo4j (env vars) | Database credentials in container |

## Key Patterns

### MCP Server Pattern (FastMCP)
```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP(host="0.0.0.0", stateless_http=True)

@mcp.tool()
def my_tool(param: str) -> str:
    """Tool description becomes LLM-visible."""
    pass

mcp.run(transport="streamable-http")
```

### AgentCore App Pattern
```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
app = BedrockAgentCoreApp()

@app.entrypoint
async def invoke(payload: dict) -> dict:
    pass

app.run(port=8080)
```

### LangGraph ReAct Agent
```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain_aws import ChatBedrockConverse

llm = ChatBedrockConverse(model="global.anthropic.claude-sonnet-4-5-20250929-v1:0")
client = MultiServerMCPClient({"server": {"transport": "streamable_http", "url": url, "headers": {"Authorization": f"Bearer {token}"}}})
tools = await client.get_tools()
agent = create_react_agent(llm, tools)
```

## Configuration

### Environment Variables (.env)

```bash
# Neo4j Database (required)
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_DATABASE=neo4j
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password

# Stack Configuration
STACK_NAME=neo4j-mcp-server
AWS_REGION=us-east-1
```

### Credentials File (.mcp-credentials.json)

Generated by `./deploy.py credentials`, contains:
- `gateway_url` - AgentCore Gateway endpoint
- `client_id` / `client_secret` - OAuth2 credentials
- `access_token` - Pre-generated JWT (valid ~1 hour)
- `token_url` - Cognito endpoint for refresh

## AWS Requirements

- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`)
- Bedrock model access enabled (Claude Sonnet)
- Region: **us-east-1** for AgentCore features (also supported in `us-west-2`)
- Docker with buildx (for ARM64 images)

## AgentCore Runtime Requirements

- Architecture: **arm64** (aarch64)
- Python: 3.10-3.13
- Port: **8080** for agents, **8000** for MCP servers
- MCP servers must use `stateless_http=True`

## SageMaker Unified Studio Notes

Direct Bedrock model access is blocked by permissions boundary. Use inference profiles with the magic tag:

```bash
./inference-profiles/setup-inference-profile.sh haiku  # Creates profile with AmazonBedrockManaged=true tag
```

The script extracts DataZone IDs from Bedrock IDE exports (`amazon-bedrock-ide-app-export-*` folders).

## Resources

- [AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [AgentCore Samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples)
- [Neo4j MCP Server](https://github.com/neo4j/mcp)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [LangGraph Multi-Agent](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- [uv Package Manager](https://docs.astral.sh/uv/)
