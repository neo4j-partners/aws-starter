# Fleet Agent

A Strands ReAct agent that answers natural language questions about an
aviation fleet graph. It connects **directly to Neo4j** (no MCP server, no
AgentCore Gateway) and reasons with Claude on Bedrock using two
`neo4j-graphrag` retrievers, with a shared `common/` core that holds the
Neo4j driver, retrievers, and prompt.

## Architecture

```
User input (POST /invocations)
  -> BedrockAgentCoreApp (runtime_app.py)
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
- **Shared core, thin Strands wrappers.** `common/` exposes plain
  `graph_query` / `vector_search` callables; `tools.py` wraps them as Strands
  tools that `runtime_app.py` and `local_cli.py` bind to the agent.

## Layout

| Path | Use |
|------|-----|
| `common/` | Neo4j driver + GraphRAG retrievers, model config, prompt |
| `tools.py` | Strands tool wrappers over the `common` callables |
| `runtime_app.py` | AgentCore Runtime entrypoint, port 8080 or cloud |
| `local_cli.py` | Simplified local experimentation |
| `demo.py` | Console showcase of the full agent surface, section by section |
| `agent.sh` | CLI wrapper for all operations |
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

./agent.sh start        # serves http://localhost:8080
./agent.sh test         # sends a sample query
```

`agent.sh start` auto-loads the agent-root `.env`.

## Quick Start: Demo (no server)

`demo.py` walks the full agent surface in the console, one `====` section at
a time, each with a plain-English description of what it shows:

1. the live Neo4j schema the agent reasons over,
2. the `graph_query` retriever alone (Text2Cypher),
3. the `vector_search` retriever alone (semantic search over manual chunks),
4. the full Strands ReAct agent choosing tools by itself.

No server is required. `demo.py` builds its own in-process Strands agent and
connects straight to Neo4j, so you do not run `./agent.sh start` first. It
needs only the three things in [Prerequisites](#prerequisites): `uv sync`, a
`.env` with the Neo4j connection, and AWS credentials for Bedrock.

```bash
uv sync
uv run python demo.py
```

Section 4 invokes Claude on Bedrock for several turns, so a full run takes a
few minutes and incurs Bedrock usage. The data-only sections 1 to 3 return
immediately.

## Quick Start: Cloud

```bash
uv sync

./agent.sh configure        # generates .bedrock_agentcore.yaml
./agent.sh deploy           # packages the code, provisions the runtime
./agent.sh invoke-cloud "How many aircraft are in the database?"
```

`agentcore deploy` runs in `direct_code_deploy` mode: it uploads the code
package to S3, provisions the AgentCore Runtime on a managed python3.13 arm64
environment, and sets up IAM and CloudWatch. There is no Docker build and no
ECR image for this agent. `./agent.sh deploy` passes the Neo4j connection from
`.env` as Runtime environment variables; the container itself has no `.env`.
The deploy output includes the Agent ARN and an observability dashboard URL.

## Remote Quick Start

A self-contained path from nothing to a deployed agent answering questions over
boto3. These are the exact steps used to validate the live runtime.

```bash
uv sync

# 1. Point .env at a Neo4j instance populated by sample-data
cp .env.sample .env          # set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD

# 2. Authenticate to AWS. With SSO, log in to your session first:
aws sso login --sso-session <your-sso-session>

# 3. Configure and deploy the runtime
./agent.sh configure         # writes .bedrock_agentcore.yaml, entrypoint runtime_app.py
./agent.sh deploy            # provisions the runtime, injects the Neo4j env vars
./agent.sh status            # wait for Endpoint: DEFAULT READY

# 4. Run the demo client against the remote runtime
./agent.sh invoke-cloud "How many aircraft are in the database?"
uv run python invoke_agent.py "What does the manual say about hydraulic leak detection?"
```

`invoke_agent.py` is the remote demo client. It reads the Agent ARN from
`.bedrock_agentcore.yaml`, calls `bedrock-agentcore` with boto3, and streams the
answer to the terminal token by token. `uv run python invoke_agent.py load-test
[seconds]` replays `queries.txt` on an interval against the deployed runtime.

`./agent.sh deploy` passes the Neo4j connection from `.env` as Runtime
environment variables. The container itself has no `.env`. Run
`./agent.sh destroy` to remove the runtime when you are finished.

A first `configure` is required even if `.bedrock_agentcore.yaml` is already
present, because it pins the entrypoint to `runtime_app.py` and records the
account, region, and execution role for this environment.

## Local Docker Testing

From the parent `neo4j-agentcore-agents/` directory:

```bash
uv run local-test all fleet-agent                  # build, run, test
uv run local-test build fleet-agent
```

The harness builds from the agent-root `Dockerfile` and keys the image and
container by agent name. Pass the Neo4j env vars through to the container.

## Commands

`./agent.sh <command>` accepts:

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
