# Neo4j MCP Agent - AgentCore Runtime

This project demonstrates how to build and deploy AI agents on **Amazon Bedrock AgentCore Runtime** that use the **Model Context Protocol (MCP)** to query a Neo4j graph database.

## Project Structure

The project is organized into progressive steps:

| Folder | Description |
|--------|-------------|
| [basic-agent/](./basic-agent/) | **Basic Agent** - A ReAct agent using LangChain that connects to Neo4j MCP server via AgentCore Gateway |
| *advanced-agent/* | **Advanced Orchestration Agent** - *(Coming soon)* Multi-agent orchestration patterns |

## Quick Start

### Basic Agent

The basic agent uses a single ReAct loop powered by LangChain to answer natural language questions about data in a Neo4j database.

```bash
cd basic-agent
./agent.sh setup          # Install dependencies
./agent.sh start          # Run agent locally (port 8080)
./agent.sh test           # Test local agent
./agent.sh deploy         # Deploy to AgentCore Runtime
./agent.sh invoke-cloud "What is the database schema?"
```

See [basic-agent/README.md](./basic-agent/README.md) for detailed documentation.

## Prerequisites

1. **Python 3.10+** and **uv** package manager
2. **AWS CLI** configured with credentials
3. **Bedrock Claude Sonnet model access** enabled in AWS console
4. **Deployed Neo4j MCP Server** with AgentCore Gateway

## Key Technologies

- **Amazon Bedrock AgentCore** - Managed runtime for deploying and scaling AI agents
- **Model Context Protocol (MCP)** - Standard protocol for connecting LLMs to external tools and data sources
- **LangChain/LangGraph** - Framework for building the ReAct agent pattern
- **Claude Sonnet 4** - The LLM powering the agent's reasoning (via Bedrock Converse API)

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   User Input    │────▶│  BedrockAgentCore│────▶│   AgentCore     │
│  (via API)      │     │      App         │     │    Gateway      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │                        │
                               │ LangChain              │ OAuth2 JWT
                               │ ReAct Agent            │
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

## References

- [Bedrock AgentCore Starter Toolkit](https://aws.github.io/bedrock-agentcore-starter-toolkit/index.html)
- [AgentCore Runtime Quickstart](https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/quickstart.html)
- [Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [neo4j-agentcore-mcp-server](../neo4j-agentcore-mcp-server/) - The MCP server this agent connects to
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
- [Model Context Protocol](https://modelcontextprotocol.io/)
