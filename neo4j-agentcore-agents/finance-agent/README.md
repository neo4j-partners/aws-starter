# Finance Agent

A ReAct agent for financial data analysis over SEC filings, companies, risk
factors, and institutional ownership. It connects to a Neo4j MCP server
through an AgentCore Gateway and reasons with Claude on Bedrock. This is the
simplest agent to deploy: `agentcore deploy` zips the Python source and
uploads it, with no Docker image required.

## Architecture

```
AgentCore Runtime
  agent.py (BedrockAgentCoreApp)
    -> Claude on Bedrock (ReAct loop)
    -> MCP client -> AgentCore Gateway (OAuth2 JWT) -> Neo4j MCP Server -> Neo4j
```

The local CLI and the deployed agent take the same Gateway path.
`.mcp-credentials.json` supplies the Gateway URL and OAuth2 client
credentials. The access token is minted and refreshed in memory, so a
long-running deployment keeps working without re-syncing credentials.

## Unique Features

- **Two framework variants, one core.** `common/` holds the
  framework-agnostic credentials, token refresh, model config, and system
  prompt. `langgraph/` and `strands/` are thin wrappers that produce the same
  answers through the same Gateway. Compare frameworks side by side.
- **Neo4j-backed semantic memory (Strands variant).** When `NEO4J_URI` and
  `NEO4J_PASSWORD` are set, the Strands variant adds Context Graph memory
  tools: `search_context`, `get_entity_graph`, `add_memory`, and
  `get_user_preferences`. Memory is scoped per request by `user_id`. It is
  best-effort and disables cleanly when those env vars are absent.
- **Low-cost default model.** Defaults to Claude Haiku 4.5. Override with
  `MODEL_ID` to use a larger model.

## Layout

| Path | Use |
|------|-----|
| `common/` | Shared credentials, token refresh, model config, prompt |
| `langgraph/agent.py`, `strands/agent.py` | AgentCore Runtime entrypoint, port 8080 or cloud |
| `langgraph/simple-agent.py`, `strands/simple-agent.py` | Local CLI, run queries directly in the terminal |
| `langgraph/agent.sh`, `strands/agent.sh` | CLI wrapper for start, test, deploy, invoke |
| `invoke_agent.py` | Call the deployed agent programmatically with boto3 |

## Prerequisites

- A deployed Neo4j MCP server with an AgentCore Gateway. See
  [../../neo4j-agentcore-mcp-server/](../../neo4j-agentcore-mcp-server/).
- `.mcp-credentials.json` with `gateway_url`, `client_id`, `client_secret`,
  and `token_url`.
- AWS credentials with Bedrock model access.

## Quick Start: Local

```bash
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
uv sync

# CLI mode, no server
uv run python langgraph/simple-agent.py "Who are the largest owners of NVIDIA?"

# Or run the AgentCore server locally on port 8080
langgraph/agent.sh start
langgraph/agent.sh test
```

Swap `langgraph` for `strands` to run the Strands variant.

## Quick Start: Cloud

```bash
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
uv sync

langgraph/agent.sh configure        # generates .bedrock_agentcore.yaml
langgraph/agent.sh deploy           # zips source, uploads, creates the runtime
langgraph/agent.sh invoke-cloud "What companies are in the database?"
```

`agentcore deploy` uses `direct_code_deploy`. It packages the source, uploads
it to S3, and creates or updates the AgentCore Runtime agent. No container
build runs. The two variants deploy under distinct agent names.

## Commands

`langgraph/agent.sh` and `strands/agent.sh` accept:

| Command | Description |
|---------|-------------|
| `start` | Run locally on port 8080 |
| `stop` | Stop the local agent |
| `test` | Send a sample query with curl |
| `configure` | Generate AWS deployment config |
| `deploy` | Deploy to AgentCore Runtime |
| `status` | Check deployment status |
| `invoke-cloud "prompt"` | Invoke the deployed agent |
| `destroy` | Remove from AgentCore |

## Environment Variables

| Variable | Required | Default |
|----------|----------|---------|
| `MODEL_ID` | No | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `AWS_REGION` | No | `us-west-2` |
| `NEO4J_URI`, `NEO4J_PASSWORD` | No | Unset. Enables Strands semantic memory when set |

## Refreshing Credentials

The token refreshes itself at runtime. If the Gateway URL or client
credentials change, regenerate and re-copy the file:

```bash
cd ../../neo4j-agentcore-mcp-server && ./deploy.sh credentials && cd -
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
```
