# sample-data

An easy way to populate a Neo4j Aura instance with the **Aircraft Digital Twin**
dataset that the [fleet-agent](../neo4j-agentcore-agents/fleet-agent/) and the
[Neo4j MCP server](../neo4j-agentcore-mcp-server/) are built around.

The fleet-agent's `queries.txt` and dynamic schema fetch already target this
exact graph (Aircraft, Systems, Components, Sensors, Readings, Flights,
Airports, Delays, Maintenance, Removals). It just needs data. This folder
generates that data locally and loads it into Aura in one command.

## What's here

| Path | Purpose |
|------|---------|
| `src/generator/` | Synthetic dataset generator (vendored). Produces CSVs. |
| `src/populate_aircraft_db/` | Aura loader + GraphRAG enrichment (vendored). |
| `manuals/` | Maintenance manuals — GraphRAG enrichment source (committed). |
| `generated/` | CSV output. **Git-ignored** — recreate with `./setup.sh generate`. |
| `setup.sh` | One-command pipeline. |

CSVs are generated locally rather than committed (the full readings file is
~114 MB). The vendored code is a clean copy from
`databricks-neo4j-lab/lab_setup` and is not modified.

## Quick start

```bash
cd sample-data

cp .env.sample .env
# Edit .env: set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD for your Aura
# instance, and OPENAI_API_KEY (enrichment). Leave LOAD_FULL_DATASET=false.

./setup.sh
```

`./setup.sh` (full pipeline) installs deps, generates the dataset, clears the
database, loads CSV data, runs GraphRAG enrichment (chunking, OpenAI
embeddings, LLM entity extraction over `manuals/`), and verifies the result.

### Commands

| Command | Action |
|---------|--------|
| `./setup.sh` | Full: sync, generate, clean, setup (load + enrich), verify |
| `./setup.sh generate` | Only (re)generate CSVs into `generated/` |
| `./setup.sh load` | Clean + load + GraphRAG enrich (needs an LLM key) |
| `./setup.sh load-operational` | Clean + CSV load only — **no LLM, no API key** |
| `./setup.sh verify` | Read-only graph verification (`--strict`) |
| `./setup.sh clean` | Delete all nodes and relationships |
| `./setup.sh samples` | Run showcase queries against the loaded graph |

## Dataset size

Controlled by `LOAD_FULL_DATASET` in `.env`:

- **`false` (default)** — ~20 aircraft × 7 days. Readings stay a few MB, loads
  in minutes, fits free/small Aura tiers. Answers every query in
  `fleet-agent/queries.txt`.
- **`true`** — ~100 aircraft × 90 days (~114 MB of readings). Realistic but slow
  to load; needs a larger Aura tier.

Set `false`/`true` so the heavy readings file is never even generated in
sampled mode. Override per-knob with `GEN_AIRCRAFT` / `GEN_DAYS` if needed.

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

## Re-syncing the vendored code

The generator and loader are a copy from
`databricks-neo4j-lab/lab_setup/{generator,populate_aircraft_db}`. To pull
upstream changes, re-copy those `src/` packages and the `manuals/*.md` files;
do not hand-edit the vendored code so the copy stays clean.
