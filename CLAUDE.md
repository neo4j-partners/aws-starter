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
cd neo4j-agentcore-mcp-server

./deploy.sh                  # Full deployment (build, push, CDK stack)
./deploy.sh credentials      # Generate .mcp-credentials.json (required after deploy)
./deploy.sh status           # Show stack status and outputs
./deploy.sh redeploy         # Fast redeploy (build, push, update runtime)
./deploy.sh cleanup          # Delete all AWS resources

# Testing
./cloud.sh                   # Test via Gateway (recommended)
./cloud.sh token             # Check token expiry
./cloud.sh tools             # List MCP tools
./cloud-http.sh              # Test direct Runtime (debugging)
./local.sh start             # Start local Docker server (no auth)
./local.sh test              # Test local server
```

### LangGraph Agent (Standalone)

```bash
cd langgraph-neo4j-mcp-agent

# Copy credentials from MCP server deployment
cp ../neo4j-agentcore-mcp-server/.mcp-credentials.json .

uv sync                      # Install dependencies
./agent.sh "query"           # Run production agent (auto-refresh OAuth2)
uv run python simple-agent.py "query"  # Simple agent (static token)

# SageMaker Unified Studio inference profiles
./setup-inference-profile.sh haiku     # Create haiku profile
./setup-inference-profile.sh sonnet    # Create sonnet profile
./setup-inference-profile.sh --list    # Show profiles with magic tag
./setup-inference-profile.sh --test haiku  # Create and test
```

### AgentCore Agents (Cloud Deployment)

```bash
cd neo4j-agentcore-agents

# Fleet Agent — LangGraph and Strands variants over a shared common/ core.
# uv project (pyproject.toml, uv.lock, .venv) is at the agent root, with a
# shared agent.sh; each variant has its own runtime_app.py + Dockerfile.
cd fleet-agent
uv sync                          # Install deps (also installs the common package)
./agent.sh langgraph start       # Run LangGraph variant locally (port 8080)
./agent.sh langgraph test        # Test local agent
./agent.sh langgraph deploy      # Deploy LangGraph variant to AgentCore Runtime
./agent.sh langgraph invoke-cloud "query"
./agent.sh strands start         # Run Strands variant locally (port 8080)
./agent.sh strands deploy        # Deploy Strands variant (distinct agent name)

# Finance Agent — same LangGraph/Strands split over its own common/ core
cd ../finance-agent
uv sync
langgraph/agent.sh start     # LangGraph variant
strands/agent.sh start       # Strands variant
# (start/test/configure/deploy/status/invoke-cloud/destroy)

# Orchestrator Agent (multi-agent with routing)
cd ../orchestrator-agent
./agent.sh start
./agent.sh test-maintenance  # Test routing to Maintenance Agent
./agent.sh test-operations   # Test routing to Operations Agent
./agent.sh deploy
./agent.sh load-test         # Continuous cloud testing
```

### Local Docker Testing (AgentCore Agents)

```bash
cd neo4j-agentcore-agents
uv sync

uv run local-test sync-credentials   # Copy creds from MCP server
uv run local-test all fleet-agent    # Build, run, test all-in-one
uv run local-test build fleet-agent  # Build Docker image (default: langgraph variant)
uv run local-test build fleet-agent --variant strands  # Build Strands variant
uv run local-test run fleet-agent    # Start container
uv run local-test test fleet-agent   # Send test request
uv run local-test logs fleet-agent   # View container logs
uv run local-test stop fleet-agent   # Stop container
uv run local-test status             # Check all containers
```

### Infra Samples

```bash
# Simple agent (Hello World)
cd infra_samples/simple-agentcore-agent
uv sync && uv run cdk bootstrap && uv run cdk deploy
uv run python test_agent.py
uv run cdk destroy

# Sample MCP server (Calculator/Greeter tools)
cd infra_samples/sample-agentcore-mcp-server
uv sync && uv run cdk deploy
uv run python test_mcp_server.py
uv run cdk destroy
```

### Databricks Integration

```bash
cd databrick_samples

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
| **Neo4j MCP Server** | `neo4j-agentcore-mcp-server/` | MCP server on AgentCore Runtime with Gateway auth |
| **LangGraph Agent** | `langgraph-neo4j-mcp-agent/` | Standalone ReAct agent, notebooks for SageMaker |
| **AgentCore Agents** | `neo4j-agentcore-agents/` | Cloud-deployed agents (basic + orchestrator) |
| **Databricks Samples** | `databrick_samples/` | Unity Catalog HTTP connection integration |
| **Infra Samples** | `infra_samples/` | Educational baseline examples |

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
STACK_NAME=neo4j-agentcore-mcp-server
AWS_REGION=us-east-1
```

### Credentials File (.mcp-credentials.json)

Generated by `./deploy.sh credentials`, contains:
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
./setup-inference-profile.sh haiku  # Creates profile with AmazonBedrockManaged=true tag
```

The script extracts DataZone IDs from Bedrock IDE exports (`amazon-bedrock-ide-app-export-*` folders).

## Resources

- [AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [AgentCore Samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples)
- [Neo4j MCP Server](https://github.com/neo4j/mcp)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [LangGraph Multi-Agent](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- [uv Package Manager](https://docs.astral.sh/uv/)
