# Neo4j MCP Agent - AgentCore Runtime

AI agents deployed on **Amazon Bedrock AgentCore Runtime** that use **MCP** to query a Neo4j graph database. Each agent connects to the Neo4j MCP server via AgentCore Gateway, uses Claude Sonnet for reasoning, and executes Cypher queries through MCP tools.

## Quick Start (Finance Agent)

The fastest way to deploy an agent — no Docker required:

```bash
# 1. Sync credentials from the MCP server deployment
./sync-credentials.sh

# 2. Deploy to AgentCore
cd finance-agent-gateway
uv sync
agentcore deploy

# 3. Test the deployed agent
agentcore invoke '{"prompt": "What companies are in the database?"}'
```

## How It Works

```
User Query → AgentCore Runtime → Agent (Claude ReAct loop)
                                   ↓
                              MCP Client (streamable HTTP)
                                   ↓
                            AgentCore Gateway (JWT auth)
                                   ↓
                          Neo4j MCP Server → Neo4j Database
```

1. **Agent receives a query** via the AgentCore Runtime `/invocations` endpoint
2. **Loads credentials** from `.mcp-credentials.json` (gateway URL + Bearer token)
3. **Connects to the Neo4j MCP server** through AgentCore Gateway using `MultiServerMCPClient`
4. **Discovers MCP tools** (e.g., `read-cypher`, `write-cypher`, `get-schema`)
5. **Runs a ReAct loop** — Claude reasons about the query, calls MCP tools to execute Cypher queries, and synthesizes a response

## Agents

| Agent | Domain | Deployment | Description |
|-------|--------|------------|-------------|
| [finance-agent-gateway/](./finance-agent-gateway/) | SEC filings, companies, risk factors | `agentcore deploy` (no Docker) | Simple ReAct agent for financial analysis |
| [basic-agent/](./basic-agent/) | Aviation fleet data | `agentcore deploy` or Docker | Single ReAct agent with schema caching and token refresh |
| [orchestrator-agent/](./orchestrator-agent/) | Aviation fleet data | Docker | Multi-agent with routing to Maintenance and Operations specialists |
| [finance-agent/](./finance-agent/) | SEC filings | Local only | Connects directly to Neo4j Aura Agent MCP (no Gateway) |

### Domain Specialists (Orchestrator)

| Agent | Handles | Example Queries |
|-------|---------|-----------------|
| **Maintenance** | Faults, components, sensors, reliability | "Most common maintenance faults", "Hydraulic system issues" |
| **Operations** | Flights, delays, routes, airports | "Common delay causes", "Busiest routes" |

## Prerequisites

1. **Python 3.10+** and **uv** package manager
2. **AWS CLI** configured with credentials
3. **Bedrock Claude Sonnet model access** enabled in AWS console
4. **Deployed Neo4j MCP Server** with AgentCore Gateway (see [neo4j-agentcore-mcp-server](../neo4j-agentcore-mcp-server/))

## Key Technologies

- **Amazon Bedrock AgentCore** - Managed runtime for deploying and scaling AI agents
- **Model Context Protocol (MCP)** - Standard protocol for connecting LLMs to external tools and data sources
- **LangGraph** - Multi-agent orchestration with StateGraph and conditional routing
- **LangChain** - ReAct agent pattern and MCP tool adapters
- **Claude Sonnet** - LLM powering agent reasoning (via Bedrock Converse API)
- **OpenTelemetry** - Observability with AWS Distro for OpenTelemetry (ADOT)

## Deployment Options

### Step 0: Sync Credentials

Copy `.mcp-credentials.json` from the MCP server deployment to all agent directories:

```bash
./sync-credentials.sh
```

### Option 1: Finance Agent (Simplest — No Docker)

Deploy a finance-domain agent using `agentcore deploy` (zips Python code, no container build):

```bash
cd finance-agent-gateway
uv sync
agentcore deploy                                          # Deploy to AgentCore
agentcore invoke '{"prompt": "Tell me about Apple Inc"}'  # Test deployed agent

# Local testing
uv run python agent.py                                   # Start on port 8080
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What companies are in the database?"}'

# CLI mode (no server)
uv run python simple-agent.py "What are NVIDIA's risk factors?"
```

### Option 2: Basic Agent (Single Agent)

A single ReAct agent with schema caching and automatic token refresh:

```bash
cd basic-agent
uv sync                   # Install dependencies
./agent.sh start          # Run locally (port 8080)
./agent.sh test           # Test local agent
./agent.sh deploy         # Deploy to AgentCore
./agent.sh invoke-cloud "What is the database schema?"
```

### Option 3: Orchestrator Agent (Multi-Agent)

Routes queries to specialized Maintenance or Operations agents:

```bash
cd orchestrator-agent
uv sync                   # Install dependencies
./agent.sh start          # Run locally (port 8080)
./agent.sh test-maintenance   # Test routing to Maintenance Agent
./agent.sh test-operations    # Test routing to Operations Agent
./agent.sh deploy         # Deploy to AgentCore
./agent.sh load-test      # Continuous cloud testing with random queries
```

See [orchestrator-agent/README.md](./orchestrator-agent/README.md) for multi-agent architecture details.

### Option 4: Local Docker Testing

Test agents locally using Docker before deploying:

```bash
# Install dependencies (run from agentcore-neo4j-mcp-agent/)
uv sync

# Sync credentials from MCP server to agent directories
uv run local-test sync-credentials

# Build and test an agent (all-in-one)
uv run local-test all basic-agent

# Or step by step:
uv run local-test build basic-agent      # Build Docker image
uv run local-test run basic-agent        # Start container
uv run local-test test basic-agent       # Send test request
uv run local-test logs basic-agent       # View logs
uv run local-test stop basic-agent       # Stop container

# Check status of all containers
uv run local-test status
```

### Option 5: CloudFormation Deployment

Deploy to AgentCore using raw CloudFormation (no CDK):

```bash
cd cfn

# Deploy basic-agent
./deploy.sh basic-agent

# Deploy orchestrator-agent
./deploy.sh orchestrator-agent

# Custom stack name
./deploy.sh basic-agent my-custom-stack

# Cleanup
./cleanup.sh basic-agent
./cleanup.sh basic-agent my-custom-stack --delete-ecr
```

## References

**AgentCore:**
- [Bedrock AgentCore Starter Toolkit](https://aws.github.io/bedrock-agentcore-starter-toolkit/index.html)
- [AgentCore Runtime Quickstart](https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/quickstart.html)
- [Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)

**MCP & Neo4j:**
- [neo4j-agentcore-mcp-server](../neo4j-agentcore-mcp-server/) - The MCP server this agent connects to
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
- [Model Context Protocol](https://modelcontextprotocol.io/)

**Multi-Agent:**
- [ORCHESTRATOR.md](./ORCHESTRATOR.md) - Design document for multi-agent architecture
- [LangGraph Multi-Agent](https://langchain-ai.github.io/langgraph/concepts/multi_agent/) - LangGraph multi-agent patterns
