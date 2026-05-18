# bedrock-graphrag-pipeline

A worked, runnable example of building a **GraphRAG ingestion pipeline on
Amazon Bedrock**. It builds a structured operational graph from data, enriches
it from unstructured documents using Bedrock Titan embeddings and Bedrock
Claude entity extraction, and fuses both into a single Neo4j knowledge graph
that an agent can query with vector search and Text2Cypher.

The pipeline is the reusable artifact. The **Aircraft Digital Twin** fleet
(aircraft, systems, sensors, readings, flights, maintenance events, plus
maintenance manuals) is the concrete dataset used to make every stage real
and verifiable. Swap the dataset and documents and the same five stages apply
to any domain.

The output is exactly the graph the
[fleet-agent](../agent/) and the
[Neo4j MCP server](../../neo4j-agentcore-mcp-server/) expect, so the same Aura
instance backs the pipeline, the MCP server, and the agent with no code
changes on their side.

## Quick start

```bash
cd fleet-agent-demo/pipeline

cp ../.env.sample ../.env   # shared fleet-agent-demo-root .env (pipeline + agent)
# Edit ../.env: set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD for your Aura
# instance. LLM_PROVIDER=bedrock by default, so enrichment uses Amazon Bedrock
# with your standard AWS credentials from env or ~/.aws. No API key needed.
# Leave LOAD_FULL_DATASET=false for a small, fast run.

./setup.sh
```

`./setup.sh` installs dependencies, then runs all five stages: generate,
load, enrich (chunk, Titan embeddings, Claude extraction over `manuals/`),
index + fuse, and strict verify.

### Commands

| Command | Stages run |
|---------|-----------|
| `./setup.sh` | Full pipeline: sync, generate, clean, load + enrich + fuse, verify |
| `./setup.sh generate` | Stage 1 only: (re)generate CSVs into `generated/` |
| `./setup.sh load` | Clean, then stages 2–5 (needs Bedrock/LLM access) |
| `./setup.sh load-operational` | Clean, then stage 2 + relink only. **No LLM, no API key.** |
| `./setup.sh verify` | Stage 5 only, read-only (`--strict`) |
| `./setup.sh clean` | Delete all nodes and relationships |
| `./setup.sh samples` | Run showcase queries against the loaded graph |

The underlying CLI (`uv run populate-aircraft-db ...`) exposes finer steps:
`enrich` (stages 3–4 against an already-loaded graph), `clean-enrichment`
(drop only the knowledge graph, preserve operational data), `debug-extract`
(run the extractor on selected chunks without writing to Neo4j), and
`agent-samples` (simulate an agent issuing Cypher and vector searches).

## What this example demonstrates

Production GraphRAG on Bedrock needs three capabilities beyond embedding
chunks and storing vectors. This example implements all three end to end:

1. **Schema-shaped structured output from Bedrock.** Entity extraction needs
   JSON that matches a target schema. `StructuredBedrockLLM` routes
   extraction through Bedrock **Converse tool use** with a forced
   `toolChoice`, the AWS-recommended path, so Claude returns
   schema-conformant JSON directly. See
   [Structured output on Bedrock](#structured-output-on-bedrock).
2. **Document context preserved through chunking.** `ContextPrependingSplitter`
   prepends a document-level header to every chunk, so the extractor labels
   each entity with the correct airframe model even deep in engine-specific
   sections. See
   [Keeping document context in every chunk](#keeping-document-context-in-every-chunk).
3. **Extracted knowledge fused with structured data.** A fusion step writes
   typed relationships between the LLM-extracted graph and the operational
   graph, so an agent can traverse from a live sensor to the manual's
   operating limit and corrective procedure. See
   [The dual graph](#the-dual-graph).

## Pipeline architecture

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

`./setup.sh` runs all five stages in order against your Neo4j Aura instance.
Stage 3 is the only stage that calls a model: Amazon Bedrock for Titan v2
embeddings and Claude entity extraction (`global.anthropic.claude-sonnet-4-6`
by default). Every other stage is pure Neo4j and local compute.

### Stage detail

| Stage | Code | What it produces |
|-------|------|------------------|
| 1. Generate | `src/generator/` | CSVs in `generated/` (git-ignored; the full readings file is ~114 MB) |
| 2. Load | `loader.py`, `schema.py` | Operational graph: `Aircraft`, `System`, `Component`, `Sensor`, `Reading`, `Flight`, `Airport`, `Delay`, `MaintenanceEvent`, `Removal` plus uniqueness constraints, property indexes, fulltext indexes |
| 3. Enrich | `pipeline.py` | `Document` + `Chunk` nodes with embeddings, and extracted entities: `AircraftModel`, `SystemReference`, `ComponentReference`, `Fault`, `MaintenanceProcedure`, `OperatingLimit` |
| 4. Index + fuse | `schema.py`, `pipeline.py` | `maintenanceChunkEmbeddings` vector index, `maintenanceChunkText` fulltext index, and typed cross-links into the operational graph |
| 5. Verify | `loader.py`, `pipeline.py` | Pass/fail report; `--strict` exits nonzero on warnings |

## The dual graph

Stage 4 is what makes this GraphRAG rather than plain vector RAG. The pipeline
ends with two subgraphs sharing one database:

- **Operational graph** (from CSV): tail-numbered aircraft, their systems,
  components, sensors, and time-series readings.
- **Knowledge graph** (extracted from manuals by the LLM): model-level
  systems, components, faults, procedures, and operating limits.

`link_to_existing_graph()` writes typed relationships between them:

| Relationship | Meaning |
|--------------|---------|
| `Document -[:APPLIES_TO]-> Aircraft` | a manual covers every aircraft of its model |
| `AircraftModel -[:DESCRIBES_MODEL]-> Aircraft` | model-level manual entity to fleet tails |
| `SystemReference -[:DESCRIBES_SYSTEM]-> System` | manual system to operational system |
| `ComponentReference -[:DESCRIBES_COMPONENT]-> Component` | manual component to installed component |
| `Sensor -[:HAS_LIMIT]-> OperatingLimit` | a live sensor to the limit the manual defines |

The payoff: an agent can start from a sensor reading on one tail number, hop
to the operating limit the manual defines for that parameter and aircraft
model, and pull the corrective procedure text by vector search over the
linked chunks. Extraction is kept model-scoped: entity names are qualified
with the aircraft type, so entity resolution stays within a single aircraft
model and keeps each model's limits distinct.

## Structured output on Bedrock

`src/populate_aircraft_db/bedrock_structured.py` is the most reusable piece of
this example outside the aircraft domain.

- `neo4j-graphrag`'s entity extractor asks its LLM for schema-shaped JSON via
  `response_format`.
- `StructuredBedrockLLM` is a thin `BedrockLLM` subclass that serves that
  request through Bedrock **Converse tool use**.
- It declares the target schema as a tool and sets a forced `toolChoice`,
  then returns the tool input as the structured result.
- Claude returns schema-conformant JSON directly, the AWS-recommended path,
  so extraction stays fast and reliable.
- It reuses the stock `BedrockLLM` Converse helpers; only the `toolChoice`
  forcing is added.
- Copy this subclass for any Bedrock + `neo4j-graphrag` pipeline.

## Keeping document context in every chunk

- `ContextPrependingSplitter` in `pipeline.py` wraps `FixedSizeSplitter`.
- It prepends a `[DOCUMENT CONTEXT]` header carrying the aircraft type and
  title to every chunk before extraction.
- `SimpleKGPipeline` passes document metadata only to the lexical graph
  builder, so this header is the only place the extractor sees the
  document-level airframe model.
- It matters most in ~800-character chunks deep in engine-specific sections
  where only the engine designation appears.
- The custom `EXTRACTION_PROMPT` tells the model to read the header and keep
  the airframe model distinct from the engine model.
- Result: the `OperatingLimit.aircraftType == Aircraft.model` cross-links in
  stage 4 stay accurate.

## Configuration

All configuration is via the shared `../.env` at the fleet-agent-demo root,
read by both the pipeline and the agent (copy from `../.env.sample`).

### Provider

`LLM_PROVIDER` selects the backend for **both** embeddings and entity
extraction:

- **`bedrock`** (default): Bedrock Titan Text Embeddings V2 + Bedrock Claude.
  No API keys; uses the standard AWS credential chain.
- **`openai`**: OpenAI embeddings + OpenAI extraction.
- **`anthropic`**: OpenAI embeddings + Anthropic extraction. Run
  `uv sync --extra anthropic` first.

Use `./setup.sh load-operational` if you want the structured graph only, with
no LLM calls and no keys.

### Bedrock notes

- **Models** (override in `.env`): extraction
  `global.anthropic.claude-sonnet-4-6`, embeddings
  `amazon.titan-embed-text-v2:0` (Titan V2, 1024-dim). The vector index is
  created at that dimension on each `clean`+`setup`, so changing the model
  needs a matching `BEDROCK_EMBEDDING_DIMENSIONS` and a re-run.
- **Region** is pinned to `us-east-1` (this repo's AgentCore region);
  override only via the explicit `BEDROCK_REGION` env var. Ensure the chosen
  models are enabled there.
- **Chunking**: `CHUNK_SIZE=800`, `CHUNK_OVERLAP=100` by default. Set
  `ENRICH_SAMPLE_SIZE` to cap chunks per document for fast test runs.

### Dataset size

Controlled by `LOAD_FULL_DATASET`:

- **`false` (default)**: ~20 aircraft × 90 days (~23 MB of readings, ~111
  maintenance events). Loads in minutes, fits free/small Aura tiers. The
  90-day window is deliberate: maintenance events fire only after sensor
  degradation crosses model thresholds (~45+ days), so a shorter window
  yields none and the maintenance queries return empty.
- **`true`**: ~100 aircraft × 90 days (~114 MB of readings). Realistic but
  slow to load; needs a larger Aura tier.

Override per-knob with `GEN_AIRCRAFT` / `GEN_DAYS` / `GEN_AIRPORTS` /
`GEN_SEED` if needed. In sampled mode the heavy readings file is never even
generated.

## Adapting this pipeline to your own domain

The pipeline generalizes. To reuse it:

1. **Replace stage 1** with your own structured data source (any CSV loader
   or existing operational graph). Update constraints and indexes in
   `schema.py`.
2. **Replace `manuals/`** with your unstructured documents and update the
   `DOCUMENTS` registry and the `[DOCUMENT CONTEXT]` header in `pipeline.py`.
3. **Redefine the extraction schema** in `schema.py`
   (`build_extraction_schema`) and the domain rules in `EXTRACTION_PROMPT`.
4. **Rewrite the fusion Cypher** in `link_to_existing_graph()` to match your
   structured and extracted graphs on the keys that join them.

`StructuredBedrockLLM` and `ContextPrependingSplitter` carry over unchanged.

## Code map

| Path | Purpose |
|------|---------|
| `src/generator/` | Stage 1: synthetic operational dataset generator |
| `src/populate_aircraft_db/loader.py` | Stages 2 and 5: CSV bulk load and verification |
| `src/populate_aircraft_db/schema.py` | Constraints, indexes, and the extraction `GraphSchema` |
| `src/populate_aircraft_db/pipeline.py` | Stages 3–4: SimpleKGPipeline, splitter, fusion Cypher |
| `src/populate_aircraft_db/bedrock_structured.py` | `StructuredBedrockLLM` (Converse tool-use structured output) |
| `src/populate_aircraft_db/main.py` | CLI: credential resolution, command wiring |
| `src/populate_aircraft_db/agent_samples.py` | Bedrock chat/embed for the `agent-samples` demo |
| `manuals/` | Maintenance manuals: the enrichment source (committed) |
| `generated/` | CSV output. **Git-ignored**; recreate with `./setup.sh generate` |
| `setup.sh` | One-command driver for all five stages |

## Appendix: wiring to the MCP server and agent

The MCP server and fleet-agent need **no code changes**, only config:

1. **Point the MCP server at this Aura instance.** In
   `neo4j-agentcore-mcp-server/.env`, set `NEO4J_URI`, `NEO4J_USERNAME`,
   `NEO4J_PASSWORD` to the same values used here, then redeploy:

   ```bash
   cd ../../neo4j-agentcore-mcp-server
   ./deploy.sh redeploy
   ./deploy.sh credentials      # refresh .mcp-credentials.json
   ```

2. **The fleet-agent adapts automatically.** It connects directly to Neo4j
   with no MCP server and no Gateway, reading the live schema from the database
   at startup, so once data exists it sees the new graph with no changes. Its
   retriever embedder must match the one this pipeline used (default: Bedrock
   Titan v2, 1024 dims). Try the queries in `../agent/queries.txt`.

## Provenance

The generator and loader originated from
`databricks-neo4j-lab/lab_setup/{generator,populate_aircraft_db}`. This copy
adds **Amazon Bedrock** as the default provider (Titan embeddings via
`BedrockEmbeddings`, Claude extraction via `StructuredBedrockLLM`). If you
pull upstream changes, re-apply the Bedrock support, which lives in:

- `src/populate_aircraft_db/config.py`: `bedrock` provider + settings
- `src/populate_aircraft_db/main.py`: credential resolution + dimension wiring
- `src/populate_aircraft_db/pipeline.py`: `StructuredBedrockLLM` / `BedrockEmbeddings` wiring
- `src/populate_aircraft_db/bedrock_structured.py`: tool-use structured-output subclass
- `src/populate_aircraft_db/agent_samples.py`: Bedrock chat/embed for `samples`
