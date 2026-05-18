# Fleet Agent

A Strands ReAct agent that answers natural language questions about an
aviation fleet graph. It connects **directly to Neo4j** (no MCP server, no
AgentCore Gateway) and reasons with Claude on Bedrock using two
`neo4j-graphrag` retrievers, with a packaged `agent/` core that holds the
Neo4j driver, retrievers, and prompt.

- **Direct Neo4j driver:** the agent opens a single Neo4j driver per process
  straight to Aura, with no MCP server or AgentCore Gateway between the agent
  and the graph.
- **Neo4j GraphRAG Text2Cypher:** `graph_query` uses `neo4j-graphrag`'s
  Text2Cypher retriever so Claude writes read-only Cypher from the live schema
  for exact and aggregate questions.
- **Neo4j GraphRAG vector search:** `vector_search` uses a `neo4j-graphrag`
  `VectorRetriever` over the `maintenanceChunkEmbeddings` index for fuzzy,
  topical questions on maintenance document chunks.
- **Claude on Bedrock:** the ReAct loop and Text2Cypher both call Claude
  through Amazon Bedrock using credentials from the standard AWS chain.
- **Bedrock Titan embeddings:** query embeddings for `vector_search` come from
  Amazon Titan on Bedrock, matched to the embedder `bedrock-graphrag-pipeline`
  used to populate the graph.
- **AgentCore Runtime deployment:** the agent serves on a managed AgentCore
  Runtime, with the Neo4j connection injected as Runtime environment variables.

## Architecture

```
  +-------------------------------------------+
  |  Client                                   |
  |  agent.sh invoke-cloud / client.invoke /  |
  |  client.demo --remote  (boto3)            |
  +-------------------------------------------+
                      |
                      |  POST /invocations  (SSE stream)
                      v
  +-------------------------------------------+        +---------------------------+
  |  AgentCore Runtime                        |        |  Amazon Bedrock           |
  |  Fleet Agent (runtime_app.py)             | -----> |  Claude (LLM, Text2Cypher)|
  |  Strands ReAct: graph_query,              |        |  Titan (embeddings)       |
  |  vector_search                            | <----- |                           |
  +-------------------------------------------+        +---------------------------+
                      |
                      |  Neo4j driver  (neo4j+s://)
                      v
  +-------------------------------------------+
  |  Neo4j Aura                               |
  |  Aircraft Digital Twin graph              |
  |  + maintenanceChunkEmbeddings index       |
  +-------------------------------------------+
```

- Reads `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD`; opens one Neo4j
  driver per process.
- Uses the standard AWS credential chain for Bedrock (LLM, Text2Cypher,
  Titan embedder).

## Populating the database

This agent expects the **Aircraft Digital Twin** graph (the entities listed in
`queries.txt`), including the chunk embeddings + `maintenanceChunkEmbeddings`
vector index that power `vector_search`. If the Neo4j instance is empty,
generate and load that dataset with
[`bedrock-graphrag-pipeline/`](../../bedrock-graphrag-pipeline/):

```bash
cd ../../bedrock-graphrag-pipeline
cp .env.sample .env        # set Aura creds + embedding provider
./setup.sh
```

- Point the agent's `.env` at the same `NEO4J_URI`; the schema is read live, so
  the agent picks up the data automatically.
- The retriever embedder must match the one `bedrock-graphrag-pipeline` used
  (default: Bedrock Titan v2, 1024 dims; override with `EMBED_MODEL_ID` /
  `EMBED_DIMENSIONS`).

## Prerequisites

1. Python 3.10+ and the `uv` package manager.
2. AWS CLI configured, with Bedrock model access enabled (LLM + Titan
   embeddings).
3. A reachable Neo4j instance populated by [`bedrock-graphrag-pipeline/`](../../bedrock-graphrag-pipeline/).

## Quick Start: Local

### Setup

```bash
cp .env.sample .env 
uv sync
```

### Server

```bash
./agent.sh start                                    # serves http://localhost:7070
```

- Auto-loads the agent-root `.env` and runs `runtime_app.py` on port 7070
  (deployed serves 8080; local overrides to avoid a clash).
- Keep this running in one terminal. The clients below are thin clients that
  talk to it over HTTP and hold no Neo4j credentials of their own.

```bash
./agent.sh test                                     # sample query via the thin client
./agent.sh cli "How many aircraft are in the fleet?"
```

### Demo

```bash
./agent.sh demo                                     # or: uv run python -m client.demo
```

Walks the agent's full surface against the running server, one `====` section
at a time:

1. the live Neo4j schema the agent reasons over,
2. the `graph_query` retriever alone (Text2Cypher),
3. the `vector_search` retriever alone (semantic search over manual chunks),
4. the full Strands ReAct agent choosing tools by itself.

Each section is served through a `mode` field on `/invocations`, so
`./agent.sh start` must be up first. Section 4 calls Claude for several turns
(a few minutes, Bedrock usage); sections 1 to 3 return quickly.

## Quick Start: Cloud

From nothing to a deployed agent answering questions over boto3.

### Setup

```bash
uv sync
cp .env.sample .env          # set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD
aws sso login --sso-session <your-sso-session>     # if using AWS SSO
```

### Deploy

```bash
./agent.sh configure         # writes .bedrock_agentcore.yaml, entrypoint runtime_app.py
./agent.sh deploy            # provisions the runtime, injects the Neo4j env vars
./agent.sh status            # wait for Endpoint: DEFAULT READY
```

- `agentcore deploy` runs `direct_code_deploy`: code package to S3, Runtime on
  managed python3.13 arm64, IAM + CloudWatch. No Docker build, no ECR image.
- `./agent.sh deploy` injects the Neo4j connection as Runtime env vars; the
  container has no `.env`. Output includes the Agent ARN and dashboard URL.
- `configure` is required first (even if `.bedrock_agentcore.yaml` exists): it
  pins the entrypoint and records account, region, and execution role.

### Drive the deployed runtime

```bash
./agent.sh invoke-cloud "How many aircraft are in the database?"
uv run python -m client.demo --remote                  # full showcase, deployed
uv run python -m client.invoke "What does the manual say about hydraulic leak detection?"
./agent.sh load-test 5                                 # replay queries.txt every 5s
```

Same four `/invocations` surfaces as local (a `mode` field selects them; no
`mode` runs the full agent), only the transport differs:

- `./agent.sh invoke-cloud "..."` — one prompt via boto3.
- `uv run python -m client.demo --remote` — all four sections, deployed.
- `uv run python -m client.invoke "..."` — one prompt; add `load-test
  [seconds]` (or `./agent.sh load-test [seconds]`) to replay `queries.txt` on
  an interval. Streams the answer token by token.
- `./agent.sh destroy` — remove the runtime when finished.

## Layout

| Path | Use |
|------|-----|
| `agent/` | Packaged core (installed into the venv): `config.py` (model id, region, embedder/index, system prompt), `retrieval.py` (direct-to-Neo4j driver + GraphRAG `graph_query` / `vector_search` / `get_graph_schema`), `tools.py` (Strands tool wrappers) |
| `client/` | Dev-only thin clients, run via `python -m client.<mod>`: `transport.py` (the only network layer — local HTTP port 7070 + boto3 deployed), `cli.py` (terminal client), `demo.py` (functionality showcase), `invoke.py` (deployed single call + load test) |
| `runtime_app.py` | AgentCore Runtime entrypoint; `mode`-dispatched surfaces, port 8080 deployed / 7070 local |
| `agent.sh` | CLI wrapper for the local run, the clients, and the deploy lifecycle |
| `queries.txt` | Sample queries across discovery, fleet, maintenance, delays |

## Commands

`agent.sh` wraps the local run, the thin clients, and the deploy lifecycle.
The same clients can also be run directly with `uv run python -m client.<mod>`.

| Command | Description |
|---------|-------------|
| `start` | Run the local agent on port 7070 (foreground; Ctrl+C to stop) |
| `test` | Send a sample query through the thin client (`client.cli`) |
| `cli "prompt"` | Ask the running agent one question (thin client) |
| `demo` | Run the functionality showcase against the local server |
| `configure` | Generate AWS deployment config |
| `deploy` / `destroy` | Deploy to or remove from AgentCore Runtime |
| `status` | Check deployment status |
| `invoke-cloud "prompt"` | Invoke the deployed agent via boto3 |
| `load-test [N]` | Replay `queries.txt` against the deployed agent every N seconds |

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
| `vector_search` returns noise or nothing | The retriever embedder must match what `bedrock-graphrag-pipeline` used. Align `EMBED_MODEL_ID` / `EMBED_DIMENSIONS`, and confirm the `maintenanceChunkEmbeddings` index exists. |
| `ServiceUnavailable` / auth error from Neo4j | Wrong `NEO4J_URI` scheme or credentials, or the instance is unreachable. |
| `NoCredentialsError` | AWS credentials are not configured. Run `aws configure` or set env credentials. |
| `AccessDeniedException` on the model | Enable Bedrock model access for the configured LLM and Titan embedding model in the AWS console. |
| 404 JSON with `timestamp` on port 7070 | Another service holds port 7070. `lsof -ti :7070 \| xargs kill`, then restart. |
