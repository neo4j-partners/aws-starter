# Aircraft Fleet GraphRAG Agent

This Strands agent answers questions about an aircraft fleet. It reads both the
fleet graph and the maintenance manuals stored in Neo4j.

## Overview

- **Two kinds of questions:** Some fleet questions need exact graph answers, such as "How many aircraft are overdue for inspection?" Others need manual text, such as "What does the manual say about hydraulic leak detection?" This agent handles both.
- **Direct Neo4j driver:** The agent opens one Neo4j driver per process and connects straight to Aura. It uses no MCP server and no AgentCore Gateway.
- **`graph_query` tool:** This tool uses the `neo4j-graphrag` Text2Cypher retriever. Claude writes read-only Cypher from the live schema for exact and aggregate questions.
- **`vector_search` tool:** This tool uses a `neo4j-graphrag` `VectorRetriever` over the `maintenanceChunkEmbeddings` index. It answers topical questions from the manual chunks.
- **Claude on Bedrock:** The agent loop and Text2Cypher both call Claude through Amazon Bedrock. They use credentials from the standard AWS chain.
- **Titan embeddings:** Bedrock Titan embeds the questions for `vector_search`. The model matches the one the pipeline used to build the graph.
- **AgentCore Runtime:** The agent can run on Amazon Bedrock AgentCore Runtime. The deploy command passes the Neo4j connection as runtime environment variables.

## Quick start

Run these commands from `demos/aircraft-fleet/graphrag-agent/`:

```bash
cp ../.env.sample ../.env    # skip if it already exists; set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
uv sync

uv run fleet-server          # terminal 1: serves http://localhost:7070
uv run fleet-cli "How many aircraft are in the fleet?"   # terminal 2
uv run fleet-demo            # terminal 2: full showcase

./agent.sh deploy            # deploy to AgentCore Runtime
./agent.sh invoke-cloud "How many aircraft are in the database?"
```

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
  |  GraphRAG Agent (fleet_graphrag.server)   | -----> |  Claude (LLM, Text2Cypher)|
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

- **Neo4j:** The agent reads `NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD`. It opens one driver per process.
- **Bedrock:** The agent uses the standard AWS credential chain for Claude, Text2Cypher, and Titan.

## Prerequisites

1. **Python:** You need Python 3.10 or later and the `uv` package manager.
2. **AWS:** You need the AWS CLI configured, with Bedrock access to the LLM and the Titan embedding model.
3. **Neo4j:** You need a Neo4j database built by [`demos/aircraft-fleet/pipeline/`](../pipeline/).

## Build the graph

The agent expects the Aircraft Digital Twin graph. The graph must include the
chunk embeddings and the `maintenanceChunkEmbeddings` vector index. If your
database is empty, run these commands from `demos/aircraft-fleet/pipeline/`:

```bash
cp ../.env.sample ../.env    # set the Neo4j values and the provider
./setup.sh
```

- **Same database:** The shared `.env` points the agent at the same `NEO4J_URI`. The agent reads the schema live, so it picks up the data on its own.
- **Same embedder:** The agent's embedder must match the pipeline's embedder. The default is Bedrock Titan v2 with 1024 dimensions. Override it with `EMBED_MODEL_ID` and `EMBED_DIMENSIONS`.

## Run locally

### Set up

Run these commands from `demos/aircraft-fleet/graphrag-agent/`:

```bash
cp ../.env.sample ../.env    # skip if it already exists
uv sync
```

### Start the server

```bash
# Terminal 1: leave this running. Press Ctrl+C to stop it.
uv run fleet-server                                 # serves http://localhost:7070
./agent.sh start                                    # the same server, through the wrapper
uv run opentelemetry-instrument fleet-server        # the same server, with OTEL tracing
```

- **Config:** The server loads the shared `.env` in `demos/aircraft-fleet/`. The `agent` package loads it on import.
- **Port:** `fleet-server` runs `fleet_graphrag.server` on port 7070. The deployed runtime uses port 8080. Local runs use 7070 to avoid a clash. Set `AGENT_PORT` to use another port.
- **Stopping:** The server runs in the foreground. Press Ctrl+C or run `./agent.sh stop` to stop it.
- **Testing:** `./agent.sh test` sends one question to the server.
- **Clients:** The clients below talk to the server over HTTP from a second terminal. They hold no Neo4j credentials.

```bash
# Terminal 2
uv run fleet-cli "How many aircraft are in the fleet?"
```

### Run the demo

```bash
uv run fleet-demo
```

The demo shows each part of the agent in its own `====` section:

1. **Schema:** It prints the live Neo4j schema that the agent reasons over.
2. **Text2Cypher:** It runs the `graph_query` retriever alone.
3. **Vector search:** It runs the `vector_search` retriever alone over the manual chunks.
4. **Full agent:** It runs the Strands agent, which picks its own tools.

Each section uses a `mode` field on `/invocations`, so `uv run fleet-server`
must be running first. Sections 1 to 3 return quickly. Section 4 calls Claude
for several turns and takes a few minutes of Bedrock usage.

## Deploy to AgentCore Runtime

### Set up

Run these commands from `demos/aircraft-fleet/graphrag-agent/`:

```bash
uv sync
cp ../.env.sample ../.env    # set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
aws sso login --sso-session <your-sso-session>     # only if you use AWS SSO
```

### Deploy

Deployment uses the AgentCore CLI. Install it with
`npm install -g @aws/agentcore`. The project lives in `agentcore/`, and
`agentcore/agentcore.json` declares the `graphrag_agent` Runtime.

Before the first deploy, edit the `envVars` in `agentcore/agentcore.json`:

- **Neo4j connection:** Set `NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_DATABASE` for the fleet graph.
- **Memory connection:** Set the `MEM_NEO4J_*` values for the agent memory database.
- **Passwords:** Set `NEO4J_PASSWORD_SECRET_ARN` and `MEM_NEO4J_PASSWORD_SECRET_ARN` to the Secrets Manager secrets that hold the passwords. Never put a password in `agentcore.json`.

```bash
./agent.sh deploy            # builds the code zip and deploys the CDK stack
./agent.sh status            # shows the Runtime ARN and deployment state
./agent.sh logs --tail       # follows the Runtime logs
```

- **Deploy type:** The Runtime uses a `CodeZip` build. `agentcore deploy` zips this directory, uploads it, and runs it on a managed Python 3.12 arm64 runtime. It builds no Docker image.
- **Packaged files:** The zip holds every file here except `agentcore/`, `.venv`, `.git`, and caches. `./agent.sh deploy` refuses to run while a `.env*` or `.mcp-credentials*.json` file is present, because the zip would include it. Local runs read the shared `../.env` instead.
- **Placeholders:** `./agent.sh deploy` also refuses to run while `agentcore.json` still has `REPLACE_ME` values.
- **Deployment target:** The first deploy creates the `default` target in `agentcore/aws-targets.json` from your current AWS account and region. That file and `agentcore/.cli/` hold account-specific values, so git ignores them.

### Call the deployed agent

```bash
./agent.sh invoke-cloud "How many aircraft are in the database?"
uv run fleet-demo --remote                              # full showcase, deployed
uv run fleet-invoke "What does the manual say about hydraulic leak detection?"
uv run fleet-invoke load-test 5                          # a random query from queries.txt every 5s
```

The deployed agent has the same four `/invocations` modes as the local server.
A `mode` field picks one. With no `mode`, the full agent runs. Only the
connection differs:

- **`./agent.sh invoke-cloud "..."`:** This command sends one prompt through `agentcore invoke`.
- **`uv run fleet-demo --remote`:** This command runs all four demo sections against the deployed agent.
- **`uv run fleet-invoke "..."`:** This command sends one prompt and streams the answer as it arrives.
- **`uv run fleet-invoke load-test [seconds]`:** This command sends a random query from `queries.txt` on an interval. The default interval is 5 seconds.
- **`./agent.sh destroy`:** This command removes the runtime when you finish.

## Layout

| Path | Use |
|------|-----|
| `main.py` | The AgentCore Runtime entrypoint. It calls `fleet_graphrag.server.main` on port 8080. AgentCore runs a file, not a module, and CodeZip installs the dependencies but not the project. The package imports because its folder sits next to `main.py`. |
| `fleet_graphrag/` | The one package, installed into the venv in editable mode. It holds `server.py`, `agent/`, and `client/`. |
| `fleet_graphrag/server.py` | The `BedrockAgentCoreApp` and its entrypoint. It handles the `mode` field. `main()` is the only way to start the server. `fleet-server` calls it on port 7070. |
| `fleet_graphrag/agent/` | The agent core. `config.py` holds the model ID, region, embedder, index, and system prompt. `retrieval.py` holds the Neo4j driver and the `graph_query`, `vector_search`, and `get_graph_schema` functions. `tools.py` holds the Strands tool wrappers. |
| `fleet_graphrag/client/` | The clients behind `fleet-cli`, `fleet-demo`, and `fleet-invoke`. `transport.py` is the only network layer. It covers local HTTP on port 7070 and the deployed agent through boto3. `cli.py` is the terminal client, `demo.py` is the showcase, and `invoke.py` is the deployed single call and load test. |
| `agent.sh` | The wrapper for local `start`, `stop`, and `test`, and for `deploy`, `status`, `invoke-cloud`, `logs`, and `destroy` |
| `agentcore/` | The AgentCore CLI project. `agentcore.json` declares the Runtime and its env vars. `cdk/` is the CDK app the CLI deploys. |
| `queries.txt` | Sample queries for discovery, fleet, maintenance, and delays |

## Commands

The server and clients are `uv` console scripts. Run the server in its own
terminal. Press Ctrl+C to stop it.

| Command | Description |
|---------|-------------|
| `uv run fleet-server` | Run the agent server locally on port 7070. Add the `opentelemetry-instrument` prefix for tracing. |
| `uv run fleet-cli "prompt"` | Ask the local server. Add `--remote` to ask the deployed agent. |
| `uv run fleet-demo` | Run the showcase against the local server. Add `--remote` to use the deployed agent. |
| `uv run fleet-invoke "prompt"` | Send one prompt to the deployed agent. `load-test [N]` sends a random query from `queries.txt` every N seconds. |

`./agent.sh` wraps the local server and the AgentCore CLI.

| Command | Description |
|---------|-------------|
| `start` / `stop` | Start or stop the local server on port 7070 |
| `test` | Ask the local server one question |
| `deploy` / `destroy` | Deploy to or remove from AgentCore Runtime |
| `status` | Show the deployment status |
| `invoke-cloud "prompt"` | Call the deployed agent through `agentcore invoke` |
| `logs [args]` | Search the Runtime logs. Add `--tail` to follow them. |

## Environment variables

| Variable | Default |
|----------|---------|
| `NEO4J_URI` | Required |
| `NEO4J_USERNAME` | `neo4j` |
| `NEO4J_PASSWORD` | Required |
| `NEO4J_DATABASE` | `neo4j` |
| `MODEL_ID` | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `AWS_REGION` | `us-east-1` |
| `VECTOR_INDEX_NAME` | `maintenanceChunkEmbeddings` |
| `EMBED_MODEL_ID` | `amazon.titan-embed-text-v2:0` |
| `EMBED_DIMENSIONS` | `1024` |
| `AGENT_PORT` | `7070` for `fleet-server`, `8080` in the container |

## Observability

The agent uses AWS Distro for OpenTelemetry auto-instrumentation. It does not use `StrandsTelemetry`.

ADOT traces the Neo4j driver, the boto3 calls to Bedrock, and incoming requests. Strands writes its agent, model, and tool spans through the global OpenTelemetry tracer, so ADOT exports those spans too. `StrandsTelemetry` would install a second tracer provider that only covers the Strands spans. The AgentCore CLI also turns on OpenTelemetry for each runtime by default through `instrumentation.enableOtel`.

- **Local tracing:** Run `uv run opentelemetry-instrument fleet-server`. This traces the Neo4j driver, the boto3 calls to Bedrock, and incoming requests.
- **Deployed tracing:** Enable Tracing on the runtime in the CloudWatch console under Bedrock AgentCore. Traces then appear in the Bedrock AgentCore Observability dashboard. Without this step, AgentCore records no traces.

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `NEO4J_URI is not set` | Set `NEO4J_URI` and `NEO4J_PASSWORD` in the shared `.env` in `demos/aircraft-fleet/` for local runs. For deployed runs, set them as runtime environment variables. |
| `vector_search` returns poor results or nothing | The agent's embedder must match the pipeline's embedder. Align `EMBED_MODEL_ID` and `EMBED_DIMENSIONS`, and confirm that the `maintenanceChunkEmbeddings` index exists. |
| `ServiceUnavailable` or an auth error from Neo4j | The `NEO4J_URI` scheme or the credentials are wrong, or the database is unreachable. |
| `NoCredentialsError` | AWS credentials are missing. Run `aws configure` or set credentials in the environment. |
| `AccessDeniedException` on the model | Enable Bedrock model access for the LLM and the Titan embedding model in the AWS console. |
| A 404 JSON response with `timestamp` on port 7070 | Another service is using port 7070. Run `lsof -ti :7070 \| xargs kill`, then restart. |
