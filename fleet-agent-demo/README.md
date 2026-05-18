# Fleet Agent Demo

An end-to-end GraphRAG demo on AWS Bedrock and Neo4j. Two projects make up one
story:

- **[`pipeline/`](./pipeline/)** builds and enriches an Aircraft Digital Twin
  graph in Neo4j: synthetic fleet data plus maintenance manuals chunked,
  embedded with Bedrock Titan, and extracted into entities with Bedrock Claude.
- **[`agent/`](./agent/)** is a Strands ReAct agent that answers natural
  language questions over that graph. It connects directly to Neo4j (no MCP
  server, no Gateway) and combines Text2Cypher with vector search over the
  maintenance chunks.

The pipeline produces exactly the schema and vector index the agent expects.
Point both at the same Neo4j instance with the same embedder and they work with
no code changes.

## Prerequisites

- A reachable Neo4j instance (Neo4j Aura works well).
- AWS credentials configured with Bedrock model access enabled (an LLM plus
  Titan embeddings).
- The [`uv`](https://docs.astral.sh/uv/) package manager and Python 3.10+.

## Configure

One shared `.env` at this directory's root is read by both projects. Create it
once:

```bash
cp .env.sample .env        # set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD
```

## Step 1: Populate the graph

```bash
cd pipeline
uv sync
./setup.sh                 # all five stages: generate, load, enrich, fuse, verify
```

`./setup.sh` defaults to a sampled dataset for a fast run. Set
`LOAD_FULL_DATASET=true` in `.env` for the full dataset. See
[`pipeline/README.md`](./pipeline/README.md) for the stage-by-stage breakdown,
the Bedrock structured-output technique, and dataset sizing.

## Step 2: Run the agent locally

The agent reads the same shared `.env`, so there is nothing more to configure.

```bash
cd ../agent
uv sync
```

```bash
# Terminal 1: the agent server (Ctrl+C to stop)
uv run fleet-server

# Terminal 2: ask questions
uv run fleet-cli "How many aircraft are in the database?"
uv run fleet-demo
```

The agent reads the live schema at startup, so once the graph is populated it
adapts with no changes. See [`agent/README.md`](./agent/README.md) for the
client commands, tracing, and troubleshooting.

## Step 3: Deploy to AgentCore Runtime (optional)

```bash
cd agent
./agent.sh configure
./agent.sh deploy
./agent.sh invoke-cloud "How many aircraft are in the database?"
```

`./agent.sh deploy` loads the Neo4j connection from the shared `.env` and
injects it as Runtime environment variables.

## Critical: keep the embedder aligned

`vector_search` only works when the agent embeds queries with the same model
and dimensions the pipeline used to embed the maintenance chunks. The default
is `amazon.titan-embed-text-v2:0` at 1024 dimensions on both sides. If you
change the pipeline embedder, set `EMBED_MODEL_ID` and `EMBED_DIMENSIONS` in
the shared `.env` to match, and confirm the `maintenanceChunkEmbeddings` index
exists. A mismatch returns noise or nothing.

## Details

- [`pipeline/README.md`](./pipeline/README.md): GraphRAG ingest architecture,
  commands, dataset sizing.
- [`agent/README.md`](./agent/README.md): agent design, local and cloud
  workflows, troubleshooting.
