# Aircraft Fleet Demo

This demo builds an aircraft fleet graph in Neo4j and answers questions about
it with AI agents on Amazon Bedrock.

## Overview

- **Pipeline:** The [`demos/aircraft-fleet/pipeline/`](./pipeline/) project builds the Aircraft Digital Twin graph. It loads synthetic fleet data, then chunks the maintenance manuals, embeds them with Bedrock Titan, and extracts entities with Bedrock Claude.
- **GraphRAG agent:** The [`demos/aircraft-fleet/graphrag-agent/`](./graphrag-agent/) project is a Strands agent that answers questions over the graph. It connects to Neo4j directly with a driver. It uses Text2Cypher for exact questions and vector search for manual text.
- **Supervisor agent:** The [`demos/aircraft-fleet/supervisor-agent/`](./supervisor-agent/) project is a Strands supervisor agent. It has two specialist agents, Maintenance and Operations. It calls each one as a tool. The supervisor model picks one or both specialists for each question. It then writes the final answer from their results. The specialists query the graph through the Neo4j MCP server and AgentCore Gateway.
- **Shared graph:** The pipeline creates the schema and vector index that the agents expect. Point all three projects at the same Neo4j database and they work with no code changes.

## Quick start

Run these commands from `demos/aircraft-fleet/`:

```bash
cp .env.sample .env          # set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, MEM_NEO4J_URI, MEM_NEO4J_PASSWORD

cd pipeline
uv sync
./setup.sh                   # build the graph

cd ../graphrag-agent
uv sync
uv run fleet-server          # terminal 1: start the agent on port 7070
uv run fleet-cli "How many aircraft are in the database?"   # terminal 2
```

## Prerequisites

- **Neo4j:** You need a Neo4j database that you can reach. Neo4j Aura works well.
- **AWS:** You need AWS credentials with Bedrock model access. Enable an LLM and the Titan embedding model.
- **Tools:** You need the [`uv`](https://docs.astral.sh/uv/) package manager and Python 3.12 or later.

## Configure

The pipeline, the GraphRAG agent, and the supervisor agent all read one `.env`
file in `demos/aircraft-fleet/`. Create it once:

```bash
cp .env.sample .env          # set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, MEM_NEO4J_URI, MEM_NEO4J_PASSWORD
```

- **Agent servers:** Both agent servers load this file at startup. Set `FLEET_ENV_FILE` to load a different file. A value already set in the environment wins.
- **Supervisor graph access:** The supervisor agent reaches the fleet graph through MCP credentials, not the `NEO4J_*` settings. See Step 4.
- **Memory settings:** Both agents keep memory in a separate Neo4j database, not the fleet graph. Set `MEM_NEO4J_URI` and `MEM_NEO4J_PASSWORD` in `.env`. Set `MEM_NEO4J_USERNAME` and `MEM_NEO4J_DATABASE` too if they are not `neo4j`. An agent server stops at startup if the URI or the password is missing.

## Step 1: Build the graph

Run these commands from `demos/aircraft-fleet/pipeline/`:

```bash
uv sync
./setup.sh                   # runs all five stages: generate, load, enrich, fuse, verify
```

- **Sampled data:** `./setup.sh` uses a small sampled dataset by default, so it runs fast.
- **Full data:** Set `LOAD_FULL_DATASET=true` in `.env` to load the full dataset.

See [`demos/aircraft-fleet/pipeline/README.md`](./pipeline/README.md) for each
stage, the Bedrock structured output method, and dataset sizes.

## Step 2: Run the GraphRAG agent locally

The agent reads the same `.env`, so it needs no extra setup. Run these
commands from `demos/aircraft-fleet/graphrag-agent/`:

```bash
uv sync

# Terminal 1: start the agent server. Press Ctrl+C to stop it.
uv run fleet-server

# Terminal 2: ask questions
uv run fleet-cli "How many aircraft are in the database?"
uv run fleet-demo
```

The agent reads the live graph schema when it starts. It picks up the new
graph with no changes. See
[`demos/aircraft-fleet/graphrag-agent/README.md`](./graphrag-agent/README.md)
for the client commands, tracing, and troubleshooting.

## Step 3: Deploy the GraphRAG agent to AgentCore Runtime (optional)

Run these commands from `demos/aircraft-fleet/graphrag-agent/`:

```bash
./agent.sh deploy
./agent.sh invoke-cloud "How many aircraft are in the database?"
```

The deploy uses the AgentCore CLI and reads its settings from `.env`. It
passes the connection settings to the runtime, but never the passwords. The
runtime reads each password from a Secrets Manager secret named by
`NEO4J_PASSWORD_SECRET_ARN` and `MEM_NEO4J_PASSWORD_SECRET_ARN`. See
[Deploy](graphrag-agent/README.md#deploy) in the graphrag-agent README for
the one-time setup.

## Step 4: Run the supervisor agent over the MCP Gateway (optional)

The supervisor reaches Neo4j through a Neo4j MCP server. Deploy one that points
at the same `NEO4J_URI`. Run these commands from the repo root:

```bash
cd neo4j-mcp-server
cp .env.sample .env.fleet    # set the same NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
./deploy.py --env fleet
./deploy.py --env fleet credentials
../scripts/sync-credentials.sh
```

`sync-credentials.sh` copies `.mcp-credentials.fleet.json` to
`demos/aircraft-fleet/.mcp-credentials.json`.

Then run these commands from `demos/aircraft-fleet/supervisor-agent/`:

```bash
uv sync
./agent.sh start             # serves http://localhost:7071
./agent.sh test-maintenance
./agent.sh test-operations
```

See
[`demos/aircraft-fleet/supervisor-agent/README.md`](./supervisor-agent/README.md)
for routing, cloud deployment, and load testing.

## Keep the embedder the same

`vector_search` works only when the agent and the pipeline use the same
embedding model and dimensions.

- **Default:** Both sides use `amazon.titan-embed-text-v2:0` with 1024 dimensions.
- **Changes:** If you change the pipeline embedder, set `EMBED_MODEL_ID` and `EMBED_DIMENSIONS` in `.env` to match.
- **Index:** Confirm that the `maintenanceChunkEmbeddings` index exists.
- **Mismatch:** A mismatch makes vector search return poor results or nothing.

## More detail

- **Pipeline:** [`demos/aircraft-fleet/pipeline/README.md`](./pipeline/README.md) covers the ingest design, commands, and dataset sizes.
- **GraphRAG agent:** [`demos/aircraft-fleet/graphrag-agent/README.md`](./graphrag-agent/README.md) covers the agent design, local and cloud runs, and troubleshooting.
- **Supervisor agent:** [`demos/aircraft-fleet/supervisor-agent/README.md`](./supervisor-agent/README.md) covers routing, cloud deployment, and load testing.
- **Test plan:** [`demos/aircraft-fleet/docs/e2e-test-plan.md`](./docs/e2e-test-plan.md) holds the end-to-end test plan and its last recorded run.
