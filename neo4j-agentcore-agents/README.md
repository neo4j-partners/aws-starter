# Neo4j MCP Agents on AgentCore Runtime

Three AI agents that answer natural language questions about a Neo4j graph by
generating Cypher. Each agent reaches Neo4j through the **Model Context
Protocol (MCP)**, connecting to a Neo4j MCP server over an **Amazon Bedrock
AgentCore Gateway** with OAuth2 auth, and reasons with Claude on Bedrock.

The three agents are progressively more advanced. Start with the finance agent
for the simplest path, then explore the basic agent for the framework split,
then the orchestrator for multi-agent routing.

## How It Works

```
User query
  -> AgentCore Runtime (/invocations)
     -> Agent (Claude ReAct loop on Bedrock)
        -> MCP client (streamable HTTP)
           -> AgentCore Gateway (OAuth2 JWT)
              -> Neo4j MCP Server -> Neo4j
```

Every agent loads `.mcp-credentials.json` for the Gateway URL and OAuth2
client credentials, mints a Bearer token, and refreshes it in memory before it
expires. A long-running deployment keeps working without re-syncing
credentials. See [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) for the
full system design.

## The Agents

| Agent | Domain | What it demonstrates | Deploy |
|-------|--------|----------------------|--------|
| [finance-agent/](./finance-agent/) | SEC filings, companies, risk factors | Simplest path. One `common/` core wired to both LangGraph and Strands. Strands variant adds Neo4j-backed semantic memory. Defaults to low-cost Haiku 4.5. | `agentcore deploy` (no Docker) |
| [basic-agent/](./basic-agent/) | Aviation fleet | Single ReAct agent with database-schema caching and OAuth2 token refresh, built once and run on either LangGraph or Strands. | `agentcore deploy` or Docker |
| [orchestrator-agent/](./orchestrator-agent/) | Aviation fleet | Multi-agent supervisor. Classifies intent and routes to Maintenance or Operations specialists, then synthesizes cross-domain answers. | `agentcore deploy` or Docker |

`finance-agent` and `basic-agent` each ship two framework variants over a
shared, framework-agnostic `common/` package:

- `langgraph/` uses LangChain `create_react_agent`.
- `strands/` uses the Strands `Agent` with `BedrockModel`.

Both variants produce the same answers through the same Gateway path. They
differ only in the agent framework, which makes this a side-by-side comparison.

## Prerequisites

1. Python 3.10+ and the `uv` package manager.
2. AWS CLI configured, with Bedrock model access enabled.
3. A deployed Neo4j MCP server with an AgentCore Gateway. See
   [../neo4j-agentcore-mcp-server/](../neo4j-agentcore-mcp-server/).

## Quick Start

```bash
# 1. Copy MCP credentials to every agent directory
./sync-credentials.sh

# 2. Pick the simplest agent and deploy it (no Docker)
cd finance-agent
uv sync
langgraph/agent.sh deploy
langgraph/agent.sh invoke-cloud "What companies are in the database?"
```

Run any agent locally before deploying. The variant scripts serve on port
8080:

```bash
cd finance-agent && uv sync
langgraph/agent.sh start          # serves http://localhost:8080
langgraph/agent.sh test           # sends a sample query
```

## Local Docker Testing

`basic-agent` and `orchestrator-agent` also run as containers through the
`local-test` harness:

```bash
uv sync                                    # from this directory
uv run local-test sync-credentials
uv run local-test all basic-agent          # build, run, test
uv run local-test build basic-agent --variant strands
```

The harness keys the image and container by agent name and ignores the
variant. The two `basic-agent` variants therefore cannot run as separate
containers at the same time. Run one variant at a time. `finance-agent` has no
Docker path. Use its variant `agent.sh` scripts instead.

## CloudFormation Deployment

Deploy without the CDK using raw CloudFormation:

```bash
cd cfn
./deploy.sh basic-agent
./deploy.sh orchestrator-agent
./cleanup.sh basic-agent
```

## References

- [Bedrock AgentCore Starter Toolkit](https://aws.github.io/bedrock-agentcore-starter-toolkit/index.html)
- [Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
- [LangGraph Multi-Agent](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
