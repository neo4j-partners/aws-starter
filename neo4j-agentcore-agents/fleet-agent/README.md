# Fleet Agent

A single ReAct agent that answers natural language questions about an
aviation fleet graph. It connects to a Neo4j MCP server through an AgentCore
Gateway and reasons with Claude on Bedrock. This agent is the reference for
the framework split: one shared core wired to both LangGraph and Strands.

## Architecture

```
User input (POST /invocations)
  -> BedrockAgentCoreApp (langgraph/runtime_app.py or strands/runtime_app.py)
     -> ReAct loop: Claude on Bedrock + MCP tools
        -> AgentCore Gateway (OAuth2 JWT) -> Neo4j MCP Server -> Neo4j
```

The agent loads `.mcp-credentials.json`, mints an OAuth2 Bearer token, and
connects to the Gateway. Before each request it refreshes the token in memory
when it is missing or close to expiring.

## Populating the database

This agent expects the **Aircraft Digital Twin** graph (the entities listed in
`queries.txt`). If the Neo4j instance is empty, generate and load that dataset
with [`sample-data/`](../../sample-data/):

```bash
cd ../../sample-data
cp .env.sample .env        # set Aura creds + OPENAI_API_KEY
./setup.sh
```

Point `neo4j-agentcore-mcp-server/.env` at the same `NEO4J_URI` and redeploy.
No agent change is needed — the schema is fetched at runtime via the MCP
`get-schema` tool, so the agent picks up the data automatically.

## Unique Features

- **Database-schema caching.** `common/schema.py` fetches the Neo4j schema
  once and caches it for the process, then injects it into the system prompt.
  Claude formulates Cypher without a `get-schema` round trip per request.
- **Automatic OAuth2 token refresh.** `common/credentials.py` checks token
  expiry and refreshes through the Cognito token endpoint. Long-running
  deployments keep working without re-syncing credentials.
- **Two framework variants, one core.** `common/` is framework-agnostic.
  `langgraph/` uses LangChain `create_react_agent`. `strands/` uses the
  Strands `Agent`. Same answers, same Gateway path, different framework.

## Layout

| Path | Use |
|------|-----|
| `common/` | Credentials, token refresh, schema cache, model config, prompt |
| `langgraph/runtime_app.py`, `strands/runtime_app.py` | AgentCore Runtime entrypoint, port 8080 or cloud |
| `langgraph/local_cli.py`, `strands/local_cli.py` | Simplified local experimentation |
| `langgraph/agent.sh`, `strands/agent.sh` | CLI wrapper for all operations |
| `invoke_agent.py` | Invoke the deployed agent with boto3, supports load testing |
| `queries.txt` | 20 sample queries across discovery, fleet, maintenance, delays |

## Prerequisites

1. Python 3.10+ and the `uv` package manager.
2. AWS CLI configured, with Bedrock model access enabled.
3. A deployed Neo4j MCP server with an AgentCore Gateway. See
   [../../neo4j-agentcore-mcp-server/](../../neo4j-agentcore-mcp-server/).

## Quick Start: Local

```bash
uv sync
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .

langgraph/agent.sh start          # serves http://localhost:8080
langgraph/agent.sh test           # sends a sample query
```

Swap `langgraph` for `strands` to run the Strands variant.

## Quick Start: Cloud

```bash
uv sync
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .

langgraph/agent.sh configure          # generates .bedrock_agentcore.yaml
langgraph/agent.sh deploy             # packages, builds image, provisions runtime
langgraph/agent.sh invoke-cloud "What is the database schema?"
```

`agentcore deploy` packages the code, builds an ARM64 container image, pushes
it to ECR, provisions the AgentCore Runtime, and sets up IAM and CloudWatch.
The deploy output includes the Agent ARN and an observability dashboard URL.

## Local Docker Testing

From the parent `neo4j-agentcore-agents/` directory:

```bash
uv run local-test sync-credentials
uv run local-test all fleet-agent                  # build, run, test
uv run local-test build fleet-agent --variant strands
```

The harness keys the image and container by agent name and ignores the
variant. The langgraph and strands variants cannot run as separate containers
at the same time. Run one variant at a time.

## Commands

`langgraph/agent.sh` and `strands/agent.sh` accept:

| Command | Description |
|---------|-------------|
| `start` / `stop` | Run or stop the local agent on port 8080 |
| `test` | Send a sample query with curl |
| `configure` | Generate AWS deployment config |
| `deploy` / `destroy` | Deploy to or remove from AgentCore Runtime |
| `status` | Check deployment status |
| `invoke-cloud "prompt"` | Invoke the deployed agent |
| `load-test [N]` | Continuous cloud test, N-second interval |

## Environment Variables

| Variable | Default |
|----------|---------|
| `MODEL_ID` | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `AWS_REGION` | `us-west-2` |

## Observability

The agent uses AWS Distro for OpenTelemetry. `agent.sh start` wraps the
process with `opentelemetry-instrument`, which traces HTTP calls to the
Gateway, boto3 calls to Bedrock, and incoming requests. After deploying,
enable Tracing on the runtime in the CloudWatch console under Bedrock
AgentCore. Traces then appear in the Bedrock AgentCore Observability
dashboard. Without that step no traces are recorded.

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `Token refresh failed: 401` | `client_id` or `client_secret` in `.mcp-credentials.json` is wrong. Re-sync credentials. |
| `NoCredentialsError` | AWS credentials are not configured. Run `aws configure` or set env credentials. |
| `AccessDeniedException` on the model | Enable Bedrock model access for the configured model in the AWS console. |
| 404 JSON with `timestamp` on port 8080 | Another service holds port 8080. `lsof -ti :8080 \| xargs kill`, then restart. |
