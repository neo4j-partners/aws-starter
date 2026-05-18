# Fleet Agent

A single ReAct agent that answers natural language questions about an
aviation fleet graph. It connects **directly to Neo4j** (no MCP server, no
AgentCore Gateway) and reasons with Claude on Bedrock using two
`neo4j-graphrag` retrievers. This agent is the reference for the framework
split: one shared core wired to both LangGraph and Strands.

## Architecture

```
User input (POST /invocations)
  -> BedrockAgentCoreApp (langgraph/runtime_app.py or strands/runtime_app.py)
     -> ReAct loop: Claude on Bedrock + two tools
        -> graph_query   (Text2Cypher, neo4j-graphrag)    -> Neo4j
        -> vector_search (VectorRetriever, neo4j-graphrag) -> Neo4j
```

The agent reads `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` from the
environment and opens a single Neo4j driver for the process. It uses AWS
credentials from the standard chain for Bedrock (the LLM, Text2Cypher, and
the Titan embedder).

## Populating the database

This agent expects the **Aircraft Digital Twin** graph (the entities listed in
`queries.txt`), including the chunk embeddings + `maintenanceChunkEmbeddings`
vector index that power `vector_search`. If the Neo4j instance is empty,
generate and load that dataset with [`sample-data/`](../../sample-data/):

```bash
cd ../../sample-data
cp .env.sample .env        # set Aura creds + embedding provider
./setup.sh
```

Point the agent's `.env` at the same `NEO4J_URI`. The schema is read from the
live database at runtime, so the agent picks up the data automatically. The
retriever embedder must match the one `sample-data` used to populate (default:
Bedrock Titan v2, 1024 dims — overridable via `EMBED_MODEL_ID` /
`EMBED_DIMENSIONS`).

## Unique Features

- **Direct GraphRAG, two tools.** `graph_query` is `neo4j-graphrag`'s
  Text2Cypher (the LLM writes read-only Cypher from the live schema) for exact
  and aggregate questions. `vector_search` is a `VectorRetriever` over
  maintenance document chunks for fuzzy, topical questions.
- **Live-schema caching.** `common/neo4j_tools.py` fetches the Neo4j schema
  once per process and injects it into the system prompt, so Claude routes
  tools without a schema round trip per request.
- **Two framework variants, one core.** `common/` is framework-agnostic and
  exposes plain `graph_query` / `vector_search` callables. `langgraph/` wraps
  them as LangChain tools; `strands/` wraps them as Strands tools. Same
  answers, different framework.

## Layout

| Path | Use |
|------|-----|
| `common/` | Neo4j driver + GraphRAG retrievers, model config, prompt |
| `langgraph/runtime_app.py`, `strands/runtime_app.py` | AgentCore Runtime entrypoint, port 8080 or cloud |
| `langgraph/local_cli.py`, `strands/local_cli.py` | Simplified local experimentation |
| `agent.sh` | Shared CLI wrapper for all operations; first arg picks the variant |
| `invoke_agent.py` | Invoke the deployed agent with boto3, supports load testing |
| `queries.txt` | 20 sample queries across discovery, fleet, maintenance, delays |

## Prerequisites

1. Python 3.10+ and the `uv` package manager.
2. AWS CLI configured, with Bedrock model access enabled (LLM + Titan
   embeddings).
3. A reachable Neo4j instance populated by [`sample-data/`](../../sample-data/).

## Quick Start: Local

```bash
uv sync
cat > .env <<'EOF'
NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
EOF

./agent.sh langgraph start        # serves http://localhost:8080
./agent.sh langgraph test         # sends a sample query
```

Swap `langgraph` for `strands` to run the Strands variant. `agent.sh start`
auto-loads the agent-root `.env`.

## Quick Start: Cloud

```bash
uv sync

./agent.sh langgraph configure        # generates .bedrock_agentcore.yaml
./agent.sh langgraph deploy           # packages, builds image, provisions runtime
./agent.sh langgraph invoke-cloud "How many aircraft are in the database?"
```

`agentcore deploy` packages the code, builds an ARM64 container image, pushes
it to ECR, provisions the AgentCore Runtime, and sets up IAM and CloudWatch.
Set `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` as Runtime environment
variables (the container has no `.env`). The deploy output includes the Agent
ARN and an observability dashboard URL.

## Local Docker Testing

From the parent `neo4j-agentcore-agents/` directory:

```bash
uv run local-test all fleet-agent                  # build, run, test
uv run local-test build fleet-agent --variant strands
```

The harness keys the image and container by agent name and ignores the
variant. The langgraph and strands variants cannot run as separate containers
at the same time. Run one variant at a time, and pass the Neo4j env vars
through to the container.

## Commands

`./agent.sh <langgraph|strands> <command>` accepts:

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
| `NEO4J_URI` | (required) |
| `NEO4J_USERNAME` | `neo4j` |
| `NEO4J_PASSWORD` | (required) |
| `NEO4J_DATABASE` | `neo4j` |
| `MODEL_ID` | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `AWS_REGION` | `us-west-2` |
| `VECTOR_INDEX_NAME` | `maintenanceChunkEmbeddings` |
| `EMBED_MODEL_ID` | `amazon.titan-embed-text-v2:0` |
| `EMBED_DIMENSIONS` | `1024` |

## Observability

The agent uses AWS Distro for OpenTelemetry. `agent.sh start` wraps the
process with `opentelemetry-instrument`, which traces the Neo4j driver, boto3
calls to Bedrock, and incoming requests. After deploying, enable Tracing on
the runtime in the CloudWatch console under Bedrock AgentCore. Traces then
appear in the Bedrock AgentCore Observability dashboard. Without that step no
traces are recorded.

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `NEO4J_URI is not set` | Set `NEO4J_URI` / `NEO4J_PASSWORD` in the agent-root `.env` (local) or as Runtime env vars (deployed). |
| `vector_search` returns noise or nothing | The retriever embedder must match what `sample-data` used. Align `EMBED_MODEL_ID` / `EMBED_DIMENSIONS`, and confirm the `maintenanceChunkEmbeddings` index exists. |
| `ServiceUnavailable` / auth error from Neo4j | Wrong `NEO4J_URI` scheme or credentials, or the instance is unreachable. |
| `NoCredentialsError` | AWS credentials are not configured. Run `aws configure` or set env credentials. |
| `AccessDeniedException` on the model | Enable Bedrock model access for the configured LLM and Titan embedding model in the AWS console. |
| 404 JSON with `timestamp` on port 8080 | Another service holds port 8080. `lsof -ti :8080 \| xargs kill`, then restart. |
