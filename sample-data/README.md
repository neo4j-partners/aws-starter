# sample-data

An easy way to populate a Neo4j Aura instance with the **Aircraft Digital Twin**
dataset that the [fleet-agent](../neo4j-agentcore-agents/fleet-agent/) and the
[Neo4j MCP server](../neo4j-agentcore-mcp-server/) are built around.

The fleet-agent's `queries.txt` and dynamic schema fetch already target this
exact graph (Aircraft, Systems, Components, Sensors, Readings, Flights,
Airports, Delays, Maintenance, Removals). It just needs data. This folder
generates that data locally and loads it into Aura in one command.

## Overview

In one command, `./setup.sh`:

1. **Generates** a synthetic Aircraft Digital Twin dataset locally as CSVs
   (aircraft, sensors, readings, flights, delays, maintenance events).
2. **Loads** those CSVs into your Neo4j Aura instance as a graph.
3. **Enriches** the graph with GraphRAG over the maintenance manuals in
   `manuals/` — chunking, Bedrock Titan embeddings, and Bedrock Claude entity
   extraction — then builds the vector index and verifies the result.

The output is exactly the graph the
[fleet-agent](../neo4j-agentcore-agents/fleet-agent/) and
[Neo4j MCP server](../neo4j-agentcore-mcp-server/) expect — no code changes on
their side, only pointing them at the same Aura instance.

## What's here

| Path | Purpose |
|------|---------|
| `src/generator/` | Synthetic dataset generator (vendored). Produces CSVs. |
| `src/populate_aircraft_db/` | Aura loader + GraphRAG enrichment (vendored). |
| `manuals/` | Maintenance manuals — GraphRAG enrichment source (committed). |
| `generated/` | CSV output. **Git-ignored** — recreate with `./setup.sh generate`. |
| `setup.sh` | One-command pipeline. |

CSVs are generated locally rather than committed (the full readings file is
~114 MB). The vendored code originates from `databricks-neo4j-lab/lab_setup`
and has been modified here to support **Amazon Bedrock** (Titan embeddings +
Claude extraction) as the default enrichment backend.

## Quick start

```bash
cd sample-data

cp .env.sample .env
# Edit .env: set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD for your Aura
# instance. LLM_PROVIDER=bedrock by default, so enrichment uses Amazon Bedrock
# with your standard AWS credentials (env / ~/.aws) — no API key needed.
# Leave LOAD_FULL_DATASET=false.

./setup.sh
```

`./setup.sh` (full pipeline) installs deps, generates the dataset, clears the
database, loads CSV data, runs GraphRAG enrichment (chunking, Bedrock Titan
embeddings, Bedrock Claude entity extraction over `manuals/`), and verifies
the result.

### Commands

| Command | Action |
|---------|--------|
| `./setup.sh` | Full: sync, generate, clean, setup (load + enrich), verify |
| `./setup.sh generate` | Only (re)generate CSVs into `generated/` |
| `./setup.sh load` | Clean + load + GraphRAG enrich (needs Bedrock/LLM access) |
| `./setup.sh load-operational` | Clean + CSV load only — **no LLM, no API key** |
| `./setup.sh verify` | Read-only graph verification (`--strict`) |
| `./setup.sh clean` | Delete all nodes and relationships |
| `./setup.sh samples` | Run showcase queries against the loaded graph |

## Dataset size

Controlled by `LOAD_FULL_DATASET` in `.env`:

- **`false` (default)** — ~20 aircraft × 90 days (~23 MB of readings, ~111
  maintenance events). Loads in minutes, fits free/small Aura tiers. The 90-day
  window is deliberate: maintenance events only fire after sensor degradation
  crosses model thresholds (~45+ days), so a shorter window yields none and the
  `fleet-agent/queries.txt` maintenance queries return empty.
- **`true`** — ~100 aircraft × 90 days (~114 MB of readings). Realistic but slow
  to load; needs a larger Aura tier.

Set `false`/`true` so the heavy readings file is never even generated in
sampled mode. Override per-knob with `GEN_AIRCRAFT` / `GEN_DAYS` if needed.

## Bedrock notes

- **Models** (override in `.env`): extraction `global.anthropic.claude-sonnet-4-6`,
  embeddings `amazon.titan-embed-text-v2:0`
  (Titan V2, 1024-dim). The vector index is created at that dimension on each
  `clean`+`setup`, so changing the model just needs a matching
  `BEDROCK_EMBEDDING_DIMENSIONS` and a re-run.
- **Region** is pinned to `us-east-1` (this repo's AgentCore region); override
  only via the explicit `BEDROCK_REGION` env var. Ensure the chosen models are
  enabled there.
- **Structured output:** `neo4j-graphrag` 1.16.0's stock `BedrockLLM` rejects
  `response_format`, so the library would fall back to prompt-based JSON +
  repair. This repo adds a thin `StructuredBedrockLLM` subclass
  (`src/populate_aircraft_db/bedrock_structured.py`) that routes the
  extractor's `response_format` through Bedrock Converse **tool use** with a
  forced `toolChoice`, so Claude returns schema-shaped JSON directly — the
  AWS-recommended path for structured output. It reuses the stock
  `BedrockLLM`'s Converse helpers; only `toolChoice` forcing is added. Switch
  `LLM_PROVIDER=openai` only if you specifically want the OpenAI extractor.

## Wiring it to the MCP server and agent

The MCP server and fleet-agent need **no code changes** — only config:

1. **Point the MCP server at this Aura instance.** In
   `neo4j-agentcore-mcp-server/.env`, set `NEO4J_URI`, `NEO4J_USERNAME`,
   `NEO4J_PASSWORD` to the **same** values used here, then redeploy:

   ```bash
   cd ../neo4j-agentcore-mcp-server
   ./deploy.sh redeploy
   ./deploy.sh credentials      # refresh .mcp-credentials.json
   ```

2. **The fleet-agent adapts automatically.** It fetches the schema at runtime
   via the MCP `get-schema` tool, so once data exists it sees the new graph
   with no changes. Try the queries in
   `../neo4j-agentcore-agents/fleet-agent/queries.txt`.

## Relationship to the upstream lab_setup

The generator and loader originated from
`databricks-neo4j-lab/lab_setup/{generator,populate_aircraft_db}`. This copy
has been modified to add **Amazon Bedrock** as a provider (Titan embeddings via
`BedrockEmbeddings`, Claude extraction via `BedrockLLM`) and to make it the
default. Edit it freely. If you pull changes from upstream, re-apply the
Bedrock support, which lives in:

- `src/populate_aircraft_db/config.py` — `bedrock` provider + settings
- `src/populate_aircraft_db/main.py` — credential resolution + dimension wiring
- `src/populate_aircraft_db/pipeline.py` — `StructuredBedrockLLM` / `BedrockEmbeddings`
- `src/populate_aircraft_db/bedrock_structured.py` — tool-use structured-output subclass
- `src/populate_aircraft_db/agent_samples.py` — Bedrock chat/embed for `samples`
