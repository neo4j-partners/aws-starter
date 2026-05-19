# Fleet Agent

An aviation fleet carries two kinds of knowledge that rarely sit together.
One is structured: which aircraft exist, what parts they carry, which flights
they flew, where delays piled up. The other is unstructured: maintenance
manuals written in prose. Real fleet questions cross both. "How many aircraft
are overdue for inspection?" is a graph traversal; "what does the manual say
about hydraulic leak detection?" is a search over text.

This agent handles both. It is a Strands ReAct agent that reasons with an LLM
on Bedrock and reaches Neo4j through two `neo4j-graphrag` retrievers: a
Text2Cypher retriever for exact and aggregate questions, and a vector
retriever over maintenance-manual chunks for topical ones. A packaged
`agent/` core holds the Neo4j driver, both retrievers, and the prompt.

- **Direct Neo4j driver:** the agent opens a single Neo4j driver per process
  straight to Aura. There is no MCP server and no AgentCore Gateway between
  the agent and the graph; the agent owns the driver itself.
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
- **Deploys to AgentCore Runtime:** the agent serves on a managed Amazon
  Bedrock AgentCore Runtime, with the Neo4j connection injected as Runtime
  environment variables. How the code is packaged and uploaded is an
  implementation detail; from the caller's side it is one command.

## Architecture

```
  +-------------------------------------------+
  |  Client                                   |
  |  agent.sh invoke-cloud / fleet-invoke /    |
  |  fleet-demo --remote  (boto3)             |
  +-------------------------------------------+
                      |
                      |  POST /invocations  (SSE stream)
                      v
  +-------------------------------------------+        +---------------------------+
  |  AgentCore Runtime                        |        |  Amazon Bedrock           |
  |  Fleet Agent (runtime_app.py)             | -----> |  Claude (LLM, Text2Cypher)|
  |  Strands ReAct                            | <----- |  Titan (embeddings)       |
  +-------------------------------------------+        +---------------------------+
            |                          |
            |  graph_query             |  vector_search
            |  Text2Cypher -> Cypher   |  query embedding -> ANN
            v                          v
  +-------------------------------------------+
  |  Neo4j Aura  (one neo4j+s:// driver)      |
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
[`../pipeline/`](../pipeline/):

```bash
cd ../pipeline
cp ../.env.sample ../.env   # shared fleet-agent-demo-root .env; set Aura creds + provider
./setup.sh
```

- The shared `.env` already points the agent at the same `NEO4J_URI`; the
  schema is read live, so the agent picks up the data automatically.
- The retriever embedder must match the one `bedrock-graphrag-pipeline` used.
  The default is Bedrock Titan v2 at 1024 dims; override with `EMBED_MODEL_ID`
  and `EMBED_DIMENSIONS`.

## Prerequisites

1. Python 3.10+ and the `uv` package manager.
2. AWS CLI configured, with Bedrock model access enabled (LLM + Titan
   embeddings).
3. A reachable Neo4j instance populated by [`../pipeline/`](../pipeline/).

## Quick Start: Local

### Setup

```bash
cp ../.env.sample ../.env   # shared fleet-agent-demo-root .env (skip if already created)
uv sync
```

### Server

```bash
# terminal 1: leave this running, Ctrl+C to stop
uv run fleet-server                                 # serves http://localhost:7070
uv run opentelemetry-instrument fleet-server        # same, with OTEL tracing
```

- Auto-loads the shared fleet-agent-demo-root `.env`, which the `agent` package loads on import,
  and runs `runtime_app.py` on port 7070. The deployed runtime serves 8080;
  local defaults to 7070 to avoid a clash, and `AGENT_PORT` still overrides.
- Runs in the foreground of its own terminal; Ctrl+C stops it. Nothing
  backgrounds it, so there is no PID or port to manage.
- The clients below are thin clients that talk to it over HTTP in a second
  terminal and hold no Neo4j credentials of their own.

```bash
# terminal 2
uv run fleet-cli "How many aircraft are in the fleet?"
```

### Demo

```bash
uv run fleet-demo
```

Walks the agent's full surface against the running server, one `====` section
at a time:

1. the live Neo4j schema the agent reasons over,
2. the `graph_query` retriever alone (Text2Cypher),
3. the `vector_search` retriever alone (semantic search over manual chunks),
4. the full Strands ReAct agent choosing tools by itself.

Each section is served through a `mode` field on `/invocations`, so
`uv run fleet-server` must be up first. Section 4 calls Claude for several
turns and takes a few minutes of Bedrock usage; sections 1 to 3 return
quickly.

## Quick Start: Cloud

From nothing to a deployed agent answering questions over boto3.

### Setup

```bash
uv sync
cp ../.env.sample ../.env    # shared root .env: NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD
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
- `configure` is required first even if `.bedrock_agentcore.yaml` already
  exists: it pins the entrypoint and records account, region, and execution
  role.
- `configure` and `destroy` forward any extra args to the underlying
  `agentcore` command, so non-interactive runs work, e.g.
  `./agent.sh configure -ni -dt direct_code_deploy -rt PYTHON_3_13` and
  `./agent.sh destroy --force`.

### Drive the deployed runtime

```bash
./agent.sh invoke-cloud "How many aircraft are in the database?"
uv run fleet-demo --remote                              # full showcase, deployed
uv run fleet-invoke "What does the manual say about hydraulic leak detection?"
uv run fleet-invoke load-test 5                          # replay queries.txt every 5s
```

Same four `/invocations` surfaces as local, where a `mode` field selects them
and no `mode` runs the full agent. Only the transport differs:

- `./agent.sh invoke-cloud "..."`: one prompt via boto3.
- `uv run fleet-demo --remote`: all four sections, deployed.
- `uv run fleet-invoke "..."`: one prompt; add `load-test [seconds]` to
  replay `queries.txt` on an interval. Streams the answer token by token.
- `./agent.sh destroy`: remove the runtime when finished.

## Layout

| Path | Use |
|------|-----|
| `agent/` | Packaged core (installed into the venv): `config.py` (model id, region, embedder/index, system prompt), `retrieval.py` (direct-to-Neo4j driver + GraphRAG `graph_query` / `vector_search` / `get_graph_schema`), `tools.py` (Strands tool wrappers) |
| `client/` | Thin clients (`fleet-cli`/`fleet-demo`/`fleet-invoke` console scripts): `transport.py` (the only network layer: local HTTP port 7070 + boto3 deployed), `cli.py` (terminal client), `demo.py` (functionality showcase), `invoke.py` (deployed single call + load test) |
| `runtime_app.py` | AgentCore Runtime entrypoint; `main()` is `fleet-server` (7070 local), the cloud container uses `__main__` (fixed 8080); `mode`-dispatched surfaces |
| `agent.sh` | Deployment helper only: `configure`, `deploy`, `status`, `invoke-cloud`, `destroy` |
| `queries.txt` | Sample queries across discovery, fleet, maintenance, delays |

## Commands

The server and clients run as `uv` console scripts (no wrapper script).
Run the server in its own terminal; Ctrl+C stops it:

| Command | Description |
|---------|-------------|
| `uv run fleet-server` | Run the agent server locally on port 7070 (Ctrl+C to stop; prefix `opentelemetry-instrument` for tracing) |
| `uv run fleet-cli "prompt"` | Ask the running local server (`--remote` for the deployed agent) |
| `uv run fleet-demo` | Run the functionality showcase against the local server (`--remote` for deployed) |
| `uv run fleet-invoke "prompt"` | One prompt against the deployed agent; `load-test [N]` replays `queries.txt` every N seconds |

`./agent.sh` is the deployment helper (it injects the Neo4j connection into
the runtime env on `deploy`):

| Command | Description |
|---------|-------------|
| `configure` | Generate AWS deployment config |
| `deploy` / `destroy` | Deploy to or remove from AgentCore Runtime |
| `status` | Check deployment status |
| `invoke-cloud "prompt"` | Invoke the deployed agent via boto3 |

## Environment Variables

| Variable | Default |
|----------|---------|
| `NEO4J_URI` | (required) |
| `NEO4J_USERNAME` | `neo4j` |
| `NEO4J_PASSWORD` | (required) |
| `NEO4J_DATABASE` | `neo4j` |
| `MODEL_ID` | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `AWS_REGION` | `us-east-1` |
| `VECTOR_INDEX_NAME` | `maintenanceChunkEmbeddings` |
| `EMBED_MODEL_ID` | `amazon.titan-embed-text-v2:0` |
| `EMBED_DIMENSIONS` | `1024` |

## Observability

The agent uses AWS Distro for OpenTelemetry. Run the server as
`uv run opentelemetry-instrument fleet-server` to wrap the process with
`opentelemetry-instrument`, which traces the Neo4j driver, boto3
calls to Bedrock, and incoming requests. After deploying, enable Tracing on
the runtime in the CloudWatch console under Bedrock AgentCore. Traces then
appear in the Bedrock AgentCore Observability dashboard. Without that step no
traces are recorded.

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `NEO4J_URI is not set` | Set `NEO4J_URI` / `NEO4J_PASSWORD` in the shared fleet-agent-demo-root `.env` (local) or as Runtime env vars (deployed). |
| `vector_search` returns noise or nothing | The retriever embedder must match what `bedrock-graphrag-pipeline` used. Align `EMBED_MODEL_ID` / `EMBED_DIMENSIONS`, and confirm the `maintenanceChunkEmbeddings` index exists. |
| `ServiceUnavailable` / auth error from Neo4j | Wrong `NEO4J_URI` scheme or credentials, or the instance is unreachable. |
| `NoCredentialsError` | AWS credentials are not configured. Run `aws configure` or set env credentials. |
| `AccessDeniedException` on the model | Enable Bedrock model access for the configured LLM and Titan embedding model in the AWS console. |
| 404 JSON with `timestamp` on port 7070 | Another service holds port 7070. `lsof -ti :7070 \| xargs kill`, then restart. |
