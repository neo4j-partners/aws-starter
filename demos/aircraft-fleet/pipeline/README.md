# Aircraft Fleet Pipeline

This pipeline builds a GraphRAG knowledge graph in Neo4j with Amazon Bedrock.
It loads structured fleet data, adds knowledge extracted from maintenance
manuals, and links the two into one graph.

## Overview

- **Dataset:** The pipeline uses the Aircraft Digital Twin fleet. It holds aircraft, systems, sensors, readings, flights, maintenance events, and maintenance manuals.
- **Five stages:** The pipeline generates data, loads it, enriches it from the manuals, builds indexes and cross-links, and verifies the result.
- **Bedrock:** Stage 3 uses Bedrock Titan for embeddings and Bedrock Claude for entity extraction. No other stage calls a model.
- **Consumers:** The output is the graph that the [GraphRAG agent](../graphrag-agent/) and the [Neo4j MCP server](../../../neo4j-mcp-server/) expect. They need no code changes.
- **Reuse:** You can swap in your own data and documents. The same five stages apply to any domain.

## Quick start

Run these commands from `demos/aircraft-fleet/pipeline/`:

```bash
cp ../.env.sample ../.env   # set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
./setup.sh                  # install dependencies and run all five stages
```

- **Shared `.env`:** The file lives in `demos/aircraft-fleet/`. The pipeline and the GraphRAG agent both read it.
- **AWS credentials:** `LLM_PROVIDER=bedrock` is the default. Enrichment uses your AWS credentials from the environment or `~/.aws`. You need no API key.
- **Dataset size:** Leave `LOAD_FULL_DATASET=false` for a small, fast run.

## Commands

Run these from `demos/aircraft-fleet/pipeline/`:

| Command | What it runs |
|---------|--------------|
| `./setup.sh` | Full pipeline: install dependencies, generate, clean, load, enrich, fuse, and verify |
| `./setup.sh generate` | Stage 1 only: generate CSVs into `generated/` |
| `./setup.sh load` | Clean, then stages 2 to 5. This needs Bedrock or LLM access. |
| `./setup.sh load-operational` | Clean, then stage 2 and relinking only. This needs no LLM and no API key. |
| `./setup.sh verify` | Stage 5 only. This is read-only and runs with `--strict`. |
| `./setup.sh clean` | Delete all nodes and relationships |
| `./setup.sh samples` | Run showcase queries against the loaded graph |

The `uv run populate-aircraft-db` CLI has more commands:

- **`enrich`:** This command runs stages 3 and 4 on a graph that is already loaded.
- **`clean-enrichment`:** This command drops only the knowledge graph. It keeps the operational data.
- **`debug-extract`:** This command runs the extractor on selected chunks. It does not write to Neo4j.
- **`agent-samples`:** This command simulates an agent that sends Cypher and vector searches.

## What this pipeline shows

GraphRAG on Bedrock needs three things beyond storing chunk embeddings. This
pipeline does all three:

1. **Structured output from Bedrock:** Entity extraction needs JSON that matches a schema. `StructuredBedrockLLM` sends extraction through Bedrock Converse tool use with a forced `toolChoice`. Claude then returns JSON that matches the schema. See [Structured output on Bedrock](#structured-output-on-bedrock).
2. **Document context in every chunk:** `ContextPrependingSplitter` adds a document header to every chunk. The extractor then labels each entity with the right airframe model, even deep in engine sections. See [Keep document context in every chunk](#keep-document-context-in-every-chunk).
3. **Extracted knowledge linked to structured data:** A fusion step writes typed relationships between the extracted graph and the operational graph. An agent can then move from a live sensor to the manual's operating limit and repair procedure. See [The dual graph](#the-dual-graph).

## Pipeline stages

```
               ┌─ 1. GENERATE ───────────────────────┐
 data spec ─▶  │ synthetic dataset → CSV files        │
               │ src/generator/                       │
               └──────────────────┬───────────────────┘
                                  ▼
               ┌─ 2. LOAD ────────────────────────────┐
               │ CSV → operational graph              │
               │ loader.py · schema.py                │
               └──────────────────┬───────────────────┘
                                  ▼
               ┌─ 3. ENRICH ──────────────────────────┐      ╔════════════════╗
 manuals/ ─▶   │ chunk → embed → extract entities     │ ───▶ ║ AMAZON BEDROCK ║
               │ pipeline.py (SimpleKGPipeline)       │ ◀─── ║ Titan v2 embed ║
               └──────────────────┬───────────────────┘      ║ Claude extract ║
                                  ▼                           ╚════════════════╝
               ┌─ 4. INDEX + FUSE ────────────────────┐
               │ vector index + cross-link graphs     │
               │ link_to_existing_graph()             │
               └──────────────────┬───────────────────┘
                                  ▼
               ┌─ 5. VERIFY ──────────────────────────┐
               │ strict checks · CI exit code         │
               └──────────────────────────────────────┘
```

`./setup.sh` runs all five stages in order against your Neo4j database. Stage 3
is the only stage that calls a model. It uses Bedrock Titan v2 for embeddings
and Claude for extraction. The default Claude model is
`global.anthropic.claude-sonnet-4-6`. Every other stage uses only Neo4j and
local compute.

| Stage | Code | Output |
|-------|------|--------|
| 1. Generate | `src/generator/` | CSVs in `generated/`. The folder is git-ignored. The full readings file is about 114 MB. |
| 2. Load | `loader.py`, `schema.py` | The operational graph: `Aircraft`, `System`, `Component`, `Sensor`, `Reading`, `Flight`, `Airport`, `Delay`, `MaintenanceEvent`, and `Removal`. It also creates uniqueness constraints, property indexes, and fulltext indexes. |
| 3. Enrich | `pipeline.py` | `Document` and `Chunk` nodes with embeddings. It also extracts `AircraftModel`, `SystemReference`, `ComponentReference`, `Fault`, `MaintenanceProcedure`, and `OperatingLimit` entities. |
| 4. Index and fuse | `schema.py`, `pipeline.py` | The `maintenanceChunkEmbeddings` vector index, the `maintenanceChunkText` fulltext index, and typed links into the operational graph |
| 5. Verify | `loader.py`, `pipeline.py` | A pass or fail report. `--strict` exits with a nonzero code on warnings. |

## The dual graph

Stage 4 turns plain vector RAG into GraphRAG. After it runs, one database holds
two subgraphs:

- **Operational graph:** This graph comes from the CSVs. It holds each aircraft by tail number, with its systems, components, sensors, and readings.
- **Knowledge graph:** The LLM extracts this graph from the manuals. It holds model-level systems, components, faults, procedures, and operating limits.

`link_to_existing_graph()` writes these relationships between them:

| Relationship | Meaning |
|--------------|---------|
| `Document -[:APPLIES_TO]-> Aircraft` | A manual covers every aircraft of its model. |
| `AircraftModel -[:DESCRIBES_MODEL]-> Aircraft` | A model entity from the manual links to each aircraft of that model. |
| `SystemReference -[:DESCRIBES_SYSTEM]-> System` | A system in the manual links to the real system. |
| `ComponentReference -[:DESCRIBES_COMPONENT]-> Component` | A component in the manual links to the installed component. |
| `Sensor -[:HAS_LIMIT]-> OperatingLimit` | A live sensor links to the limit that the manual defines. |

An agent can start from a sensor reading on one aircraft. It can then move to
the operating limit for that sensor and aircraft model. Finally, it can pull
the repair procedure text with vector search over the linked chunks.

Extraction stays scoped to each aircraft model. Entity names include the
aircraft type. Entity resolution therefore stays inside one model, and each
model keeps its own limits.

## Structured output on Bedrock

`src/populate_aircraft_db/bedrock_structured.py` is the most reusable part of
this pipeline.

- **The need:** The `neo4j-graphrag` entity extractor asks its LLM for JSON that matches a schema through `response_format`.
- **The class:** `StructuredBedrockLLM` is a small subclass of `BedrockLLM`. It answers that request through Bedrock Converse tool use.
- **How it works:** It declares the target schema as a tool and forces `toolChoice`. It then returns the tool input as the structured result.
- **The result:** Claude returns JSON that matches the schema, so extraction stays fast and reliable.
- **The change:** It reuses the stock `BedrockLLM` Converse helpers. It adds only the forced `toolChoice`.
- **Reuse:** You can copy this subclass into any Bedrock and `neo4j-graphrag` pipeline.

## Keep document context in every chunk

- **The class:** `ContextPrependingSplitter` in `pipeline.py` wraps `FixedSizeSplitter`.
- **What it adds:** It adds a `[DOCUMENT CONTEXT]` header to every chunk before extraction. The header holds the aircraft type and title.
- **Why it is needed:** `SimpleKGPipeline` passes document metadata only to the lexical graph builder. The header is the only place where the extractor sees the airframe model.
- **Where it matters:** It matters most in 800-character chunks deep in engine sections. Those chunks often name only the engine.
- **The prompt:** The custom `EXTRACTION_PROMPT` tells the model to read the header. It also tells the model to keep the airframe model separate from the engine model.
- **The result:** The `OperatingLimit.aircraftType == Aircraft.model` links in stage 4 stay accurate.

## Configuration

The pipeline reads the shared `.env` in `demos/aircraft-fleet/`. Copy it from
`demos/aircraft-fleet/.env.sample`.

### Provider

`LLM_PROVIDER` picks the backend for both embeddings and entity extraction:

- **`bedrock`:** This default uses Bedrock Titan Text Embeddings V2 and Bedrock Claude. It needs no API keys. It uses the standard AWS credential chain.
- **`openai`:** This option uses OpenAI for embeddings and extraction.
- **`anthropic`:** This option uses OpenAI embeddings and Anthropic extraction. `./setup.sh` installs the `anthropic` extra for you. If you run `uv` yourself, run `uv sync --extra anthropic` first.

Run `./setup.sh load-operational` to build only the structured graph. It makes
no LLM calls and needs no keys.

### Bedrock settings

- **Models:** Extraction uses `global.anthropic.claude-sonnet-4-6`. Embeddings use `amazon.titan-embed-text-v2:0` with 1024 dimensions. You can override both in `.env`.
- **Embedding dimensions:** Each `clean` and `setup` creates the vector index at the configured dimension. If you change the embedding model, set a matching `BEDROCK_EMBEDDING_DIMENSIONS` and run the pipeline again.
- **Region:** The pipeline and the agent share one `AWS_REGION` setting. It defaults to `us-east-1`. If you change it, enable the models in that region.
- **Chunking:** `CHUNK_SIZE` defaults to 800 and `CHUNK_OVERLAP` defaults to 100. Set `ENRICH_SAMPLE_SIZE` to limit chunks per document for fast test runs.

### Dataset size

`LOAD_FULL_DATASET` sets the dataset size:

- **`false`:** This default loads about 20 aircraft over 90 days. That is about 23 MB of readings and about 111 maintenance events. It loads in minutes and fits free or small Aura tiers.
- **`true`:** This option loads about 100 aircraft over 90 days. That is about 114 MB of readings. It is slow to load and needs a larger Aura tier.

The 90-day window matters. Maintenance events start only after sensor wear
crosses model thresholds. That takes about 45 days or more. A shorter window
creates no events, so the maintenance queries return nothing.

You can set `GEN_AIRCRAFT`, `GEN_DAYS`, `GEN_AIRPORTS`, and `GEN_SEED` to
override single values.

## Adapt this pipeline to your domain

1. **Replace stage 1:** Use your own structured data source, such as any CSV loader or an existing graph. Update the constraints and indexes in `schema.py`.
2. **Replace `manuals/`:** Add your own documents. Update the `DOCUMENTS` list and the `[DOCUMENT CONTEXT]` header in `pipeline.py`.
3. **Redefine the extraction schema:** Edit `build_extraction_schema` in `schema.py` and the domain rules in `EXTRACTION_PROMPT`.
4. **Rewrite the fusion Cypher:** Edit `link_to_existing_graph()` so it joins your structured and extracted graphs on their shared keys.

`StructuredBedrockLLM` and `ContextPrependingSplitter` work unchanged.

## Code map

| Path | Purpose |
|------|---------|
| `src/generator/` | Stage 1: the synthetic dataset generator |
| `src/populate_aircraft_db/loader.py` | Stages 2 and 5: CSV bulk load and verification |
| `src/populate_aircraft_db/schema.py` | Constraints, indexes, and the extraction `GraphSchema` |
| `src/populate_aircraft_db/pipeline.py` | Stages 3 and 4: `SimpleKGPipeline`, the splitter, and the fusion Cypher |
| `src/populate_aircraft_db/bedrock_structured.py` | `StructuredBedrockLLM`, which gets structured output through Converse tool use |
| `src/populate_aircraft_db/config.py` | Settings, including the provider and Bedrock models |
| `src/populate_aircraft_db/main.py` | The CLI: credential lookup and command wiring |
| `src/populate_aircraft_db/agent_samples.py` | Chat and embedding calls for the `agent-samples` command |
| `manuals/` | The maintenance manuals used for enrichment. They are committed. |
| `generated/` | The CSV output. It is git-ignored. Recreate it with `./setup.sh generate`. |
| `setup.sh` | One command that drives all five stages |

## Connect the MCP server and the GraphRAG agent

The MCP server and the GraphRAG agent need only configuration changes.

1. **Point the MCP server at this database:** In `neo4j-mcp-server/.env.fleet`, set `NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD` to the values used here. Then run these commands from the repo root:

   ```bash
   cd neo4j-mcp-server
   ./deploy.py --env fleet                  # apply the new Neo4j settings
   ./deploy.py --env fleet credentials      # refresh .mcp-credentials.fleet.json
   ```

   Use the full deploy here. `./deploy.py redeploy` updates only the container image. It does not apply new Neo4j settings.

2. **The GraphRAG agent adapts on its own:** The agent connects to Neo4j directly with a driver. It reads the live schema when it starts, so it sees the new graph with no changes. Its embedder must match the one this pipeline used. The default is Bedrock Titan v2 with 1024 dimensions. Try the queries in [`demos/aircraft-fleet/graphrag-agent/queries.txt`](../graphrag-agent/queries.txt).
