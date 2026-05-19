# Fleet Agent Demo: End-to-End Test Plan

## How to use this document

This is a working log, not just a reference. As you run the test:

1. **Record each step as you go.** Under each step there is a "Result" line.
   Fill it in with what actually happened: the command you ran, the key
   output, pass or fail, and anything you had to change. Do not wait until
   the end to write it all up.
2. **Capture real evidence.** Paste the relevant command output, counts,
   ARNs, and error text. A bare "worked" is not a result.
3. **Write the final summary.** When you finish (or stop early), complete the
   "Run Summary" section at the bottom: overall status, what passed, what
   failed, root causes, and follow-ups.
4. **Keep the checklist current.** Tick each box in the "Checklist" section
   the moment that step is verified, so progress is visible at a glance.

Edit this file in place. One file is the plan, the log, and the report.

---

## Test scope

Validate the full demo path:

1. Configure the shared `.env`.
2. Ingest data with the pipeline into Neo4j (`pipeline/`).
3. Run the agent locally against that graph (`agent/`).
4. Deploy the agent to AWS AgentCore Runtime and drive it remotely.
5. Tear down cloud resources.

All paths below are relative to `fleet-agent-demo/`.

---

## Checklist

Tick each box only after the step's result is recorded below.

- [x] **0.** Prerequisites verified (uv, Python 3.10+, AWS creds, Bedrock
      model access, reachable Neo4j)
- [x] **1.** Shared `.env` created and filled in
- [x] **2.** Pipeline deps synced (`cd pipeline && uv sync`)
- [x] **3.** Pipeline run end to end (`./setup.sh`) completed
- [x] **4.** Pipeline strict verify passed
- [x] **5.** Showcase queries run (`./setup.sh samples`)
- [x] **6.** Agent deps synced (`cd agent && uv sync`)
- [x] **7.** Local agent server started (`uv run fleet-server`)
- [x] **8.** Local single query answered (`uv run fleet-cli "..."`)
- [x] **9.** Local full showcase passed (`uv run fleet-demo`)
- [x] **10.** Agent configured for AWS (`./agent.sh configure`)
- [x] **11.** Agent deployed (`./agent.sh deploy`)
- [x] **12.** Deployment reached READY (`./agent.sh status`)
- [x] **13.** Cloud single query answered (`./agent.sh invoke-cloud "..."`)
- [x] **14.** Cloud full showcase passed (`uv run fleet-demo --remote`)
- [x] **15.** Cloud resources destroyed (`./agent.sh destroy`)
- [x] **16.** Run Summary written

---

## Step 0: Prerequisites

Confirm before starting:

- `uv --version` and Python 3.10+ available.
- AWS credentials configured (`aws sts get-caller-identity` succeeds). If
  using SSO: `aws sso login --sso-session <your-sso-session>`.
- Bedrock model access enabled in the target region for the extraction LLM
  (`global.anthropic.claude-sonnet-4-6`), the agent LLM
  (`global.anthropic.claude-sonnet-4-5-20250929-v1:0`), and Titan embeddings
  (`amazon.titan-embed-text-v2:0`).
- A reachable Neo4j instance (Aura works well). Have the URI, username, and
  password ready.

Region is a single shared knob: `AWS_REGION` (defaults to `us-east-1` for
both the pipeline's Bedrock calls and the agent). Set it once in the shared
`.env` if you want a non-default region, and confirm the LLM and Titan models
are enabled there. Record the region used.

**Result:** PASS (2026-05-18)
- `uv 0.11.12` (Homebrew, aarch64-apple-darwin); system Python 3.14.4 (uv
  manages project venvs at 3.10+).
- AWS identity: account `159878781974`, role
  `AWSReservedSSO_AdministratorAccess` as `ryan.knight@neo4j.com`. No SSO
  re-login needed (`aws sts get-caller-identity` succeeded).
- Region: `us-east-1` (from shared `.env`: `AWS_REGION=us-east-1`,
  `BEDROCK_REGION=us-east-1`). Bedrock `list-foundation-models` in us-east-1
  shows `amazon.titan-embed-text-v2:0`,
  `anthropic.claude-sonnet-4-5-20250929-v1:0`, and
  `anthropic.claude-sonnet-4-6` available.
- Neo4j target: Aura `neo4j+s://e8e7cca9.databases.neo4j.io`, db `neo4j`.
  `verify_connectivity()` OK; current node count = 360,758 (instance
  already holds data from a prior run — pipeline `setup.sh` will reload).

---

## Step 1: Configure the shared `.env`

One `.env` at the `fleet-agent-demo/` root is read by both projects.

```bash
cd fleet-agent-demo
cp .env.sample .env
# Edit .env: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD.
# Leave LOAD_FULL_DATASET=false for a fast run.
# Keep the embedder aligned: default amazon.titan-embed-text-v2:0 at 1024
# dims on both pipeline and agent. If you change it, set EMBED_MODEL_ID and
# EMBED_DIMENSIONS to match on both sides.
```

**Result:** PASS — `.env` already present at `fleet-agent-demo/` root.
Set: `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE=neo4j`,
`LOAD_FULL_DATASET=false` (fast/sampled run), `LLM_PROVIDER=bedrock`,
`AWS_REGION=us-east-1`, `BEDROCK_REGION=us-east-1`. Embedder left at default
`amazon.titan-embed-text-v2:0` @ 1024 dims on both sides (no overrides set).

---

## Step 2: Sync pipeline dependencies

```bash
cd pipeline
uv sync
```

**Result:** PASS — `cd pipeline && uv sync` resolved and installed the
environment cleanly (no resolution conflicts).

---

## Step 3: Run the ingestion pipeline

```bash
# from fleet-agent-demo/pipeline
./setup.sh
```

This runs all five stages: generate CSVs, clean, load operational graph,
enrich (chunk + Titan embeddings + Claude extraction over `manuals/`), index
+ fuse, strict verify. Stage 3 is the only stage that calls Bedrock.

If credentials or model access fail mid-run, record the failing stage. To
isolate stages: `./setup.sh generate`, `./setup.sh load-operational` (no LLM,
no key), `./setup.sh load`, `./setup.sh verify`.

**Result:** IN PROGRESS — first `./setup.sh` attempt aborted partway.
- Stage 1 (generate): PASS. 20 aircraft, 80 systems, 340 components, 160
  sensors, 345,600 sensor readings, 110 maintenance events, 40 airports,
  8,116 flights, 3,124 delays, 25 component removals (seed 42, full=false).
- Stage 2 (clean): aborted by operator. The Aura instance held ~360,758
  nodes from a prior run; `populate-aircraft-db clean` deletes in 500-node
  batches and was too slow (had reached ~126k deleted). Operator is
  clearing the database directly (single `MATCH (n) DETACH DELETE n` /
  instance reset) before re-running the load.
- Re-run: operator cleared the DB directly (verified node count = 0).
  Restarted via `./setup.sh load` (skips CSV regen; Stage 1 already passed).
- Stage 2 (clean): PASS, instant — `[OK] Database cleared (0 nodes
  deleted)` on the now-empty instance.
- Stage 3a (schema): PASS — 11 uniqueness constraints, 5 range indexes,
  4 fulltext indexes (`maintenance_search`, `delay_search`,
  `component_search`, `document_search`) created.
- Stage 3b (node load): PASS — 20 Aircraft, 80 System, 340 Component,
  160 Sensor, 345,600 Reading, 40 Airport, 8,116 Flight, 3,124 Delay,
  110 MaintenanceEvent, 25 Removal.
- Stage 3c (relationships): PASS — HAS_SYSTEM 80, HAS_COMPONENT 340,
  HAS_SENSOR 160, HAS_EVENT 110, HAS_READING 345,600, OPERATES_FLIGHT
  8,116, DEPARTS_FROM 8,116, ARRIVES_AT 8,116, HAS_DELAY 3,124,
  AFFECTS_SYSTEM 110, AFFECTS_AIRCRAFT 110, HAS_REMOVAL 25,
  REMOVED_COMPONENT 25.
- Stage 3d (GraphRAG enrichment): PASS — 5 manuals processed
  (AMM-A320/A321neo/B737/E190/A220-2024-001) via Bedrock (Titan
  embeddings + Claude extraction). Created 6 extraction constraints,
  vector index `maintenanceChunkEmbeddings` and fulltext
  `maintenanceChunkText` (both ONLINE). Cross-links: 20 Document→Aircraft,
  20 AircraftModel→Aircraft, 965 SystemReference→System, 148
  ComponentReference→Component, 1,440 Sensor→OperatingLimit. 290 Chunk
  nodes, all with embeddings.
- Stage 3e (verify --strict, run by `load`): PASS — `[OK] Verification
  passed.` Vector search smoke test returned 1 result, best score 1.0000.
  Data-quality checks all zero (no orphan readings/flights/components/
  sensors/documents).
- **Overall: PASS.** Background command exit code 0; total wall time
  **15m 35s** for the `load` re-run.

---

## Step 4: Strict verify

`./setup.sh` already runs `verify --strict`. Re-run it standalone to confirm
a clean read-only pass:

```bash
./setup.sh verify
```

Expect a pass report and exit code 0.

**Result:** PASS — standalone `./setup.sh verify` exit code 0,
`[OK] Verification passed.`
- Embeddings: 290 chunks, 0 missing, dimensions found `[1024]`, 0
  wrong-dimension.
- Indexes: `maintenanceChunkEmbeddings` VECTOR ONLINE,
  `maintenanceChunkText` FULLTEXT ONLINE. All 17 constraints present.
- Vector search smoke test: 1 result, best score 1.0000.
- Cross-links: Document→Aircraft 20, AircraftModel→Aircraft 20,
  SystemReference→System 965, Sensor→OperatingLimit 2,133.
- Data quality: 0 orphan readings / flights / components / sensors /
  documents. No warnings.

---

## Step 5: Showcase queries against the graph

```bash
./setup.sh samples
```

Simulates an agent issuing Cypher and vector searches against the loaded
graph. Confirms the dual graph and the `maintenanceChunkEmbeddings` index are
queryable.

**Result:** PASS (with one minor cosmetic note) — `./setup.sh samples`
exit code 0, "All samples complete."
- All sections returned real data: Fleet Overview (20 aircraft with
  model/manufacturer/system+component counts), system→component
  hierarchy, maintenance events with severity/fault/system, sensor
  inventory, Document/Chunk inventory (20 docs, chunks embedded), chunk
  sequence chains, and extracted-entity cross-links
  (Document→Aircraft, OperatingLimit→Chunk→Document→Aircraft provenance).
- Vector similarity: real manual chunks, scores 0.85–0.90 (not
  noise/empty), correct aircraft-type grouping.
- **Minor note (since FIXED):** the hybrid demo's *fulltext* sub-query
  printed "(fulltext index not available — run 'setup' first)" even
  though `verify` confirms `maintenanceChunkText` FULLTEXT ONLINE. Root
  cause was NOT a param mismatch — the fulltext keyword string was built
  from raw chunk text starting with `[DOCUMENT CONTEXT]`; the `[` is a
  Lucene range operator, so `db.index.fulltext.queryNodes` threw a
  `ParseException` that the broad `except` masked with the misleading
  message. Fixed in `samples.py`: extended the punctuation `reduce` to
  also strip Lucene special chars, and changed the `except` to surface
  the real error. Re-ran `./setup.sh samples` (exit 0): the hybrid
  `[B] Fulltext` block now returns real rows. Never affected data
  integrity or the agent (agent uses the vector index).

---

## Step 6: Sync agent dependencies

```bash
cd ../agent
uv sync
```

**Result:** PASS — `cd agent && uv sync` resolved and installed cleanly
(no conflicts).

---

## Step 7: Start the local agent server

Run in its own terminal; Ctrl+C stops it. Serves `http://localhost:7070`.

```bash
# Terminal 1
uv run fleet-server
# or with tracing:
uv run opentelemetry-instrument fleet-server
```

If port 7070 is held: `lsof -ti :7070 | xargs kill`, then restart.

**Result:** PASS (resolved). Originally blocked; operator started the
server manually in-session. Now listening on port 7070 (pid 40141),
health endpoint returns `{"status":"Healthy"}`. History:
- Port 7070 was held by an unrelated long-running fleet-agent server
  (PID 16869, 2h34m elapsed) from `neo4j-agentcore-agents/fleet-agent/`
  (a different project). Operator approved "kill it and start ours";
  `lsof -ti :7070 | xargs kill` ran and port 7070 was freed.
- Starting `uv run fleet-server` was then denied by the Claude Code
  auto-mode permission classifier (stale rationale — it did not register
  the operator's approval). Server not started; Steps 8–9 not yet run.
- Resolution options surfaced to operator: (a) run `uv run fleet-server`
  manually in-session, (b) add a Bash permission rule and retry, or
  (c) skip local Steps 7–9 and proceed to the AWS deploy path
  (Steps 10–15), which does not need the local server.

---

## Step 8: Local single query

```bash
# Terminal 2
uv run fleet-cli "How many aircraft are in the database?"
```

Expect a numeric answer consistent with the loaded dataset (default ~20
aircraft).

**Result:** PASS — operator started `uv run fleet-server` manually
(in-session); confirmed listening on 7070 (pid 40141), `/ping` returned
`{"status":"Healthy"}`. `uv run fleet-cli "How many aircraft are in the
database?"` → routed to `graph_query_tool` → **"There are 20 aircraft in
the database."** Matches the loaded dataset (20 aircraft, full=false).
Step 7 (server) thereby also satisfied.

---

## Step 9: Local full showcase

```bash
uv run fleet-demo
```

Walks four sections: live schema, `graph_query` (Text2Cypher),
`vector_search` (semantic over manual chunks), and the full ReAct agent.
Section 4 calls Claude for several turns and takes a few minutes.

**Result:** PASS — `uv run fleet-demo` exit code 0, all 4 sections.
- **Section 1 (live schema):** PASS — agent loaded the live Neo4j schema
  (node labels / rels / properties) at startup.
- **Section 2 (graph_query / Text2Cypher):** PASS — count = 20 aircraft;
  grouped aggregation matched generation (Airbus A220-300 ×2, A320-200
  ×5, A321neo ×4, Boeing B737-800 ×7, Embraer E190 ×2); relationship
  traversal returned CRITICAL maintenance events with tail numbers and
  faults.
- **Section 3 (vector_search):** PASS — semantic query "procedure for
  detecting a hydraulic system leak" returned real manual text (E190
  Maintenance Manual §6.4.1 Leak Detection), not noise.
- **Section 4 (full ReAct agent):** PASS — agent self-selected tools
  correctly: `graph_query_tool` for the operator/delays structured
  question (RegionalCo, 1,054 delays), `vector_search_tool` for the
  hydraulic reservoir low-level manual question (detailed procedure),
  and combined both tools for the "needs both" engine-vibration question
  (40 vibration-exceedance events + per-type manual troubleshooting).
- Multi-turn Claude section completed within the run; no errors.

---

## Step 10: Configure for AWS deployment

```bash
# from fleet-agent-demo/agent
./agent.sh configure
```

Writes `.bedrock_agentcore.yaml`, pins entrypoint `runtime_app.py`. Required
even if the yaml already exists.

**Result:** PASS (with a documented deviation). No TTY in the automation
shell, so `./agent.sh configure` (which runs `agentcore configure`
interactively) crashed with `OSError: [Errno 22]` attaching to stdin.
Ran the equivalent non-interactively instead:
`uv run agentcore configure -e runtime_app.py -n fleet_agent -ni
-r us-east-1 -dt direct_code_deploy -rt PYTHON_3_13` (exit 0).
- Agent name: `fleet_agent`; entrypoint pinned `runtime_app.py`.
- Deployment: `direct_code_deploy`, runtime python3.13 (managed, no
  Docker), Network mode PUBLIC.
- Region: `us-east-1`; Account: `159878781974`.
- Execution role: auto-create; S3 bucket: auto-create; Authorization:
  IAM (default); Memory: STM_ONLY (30-day retention).
- Config written to `agent/.bedrock_agentcore.yaml` (none existed
  before). `fleet_agent` set as default agent.

---

## Step 11: Deploy to AgentCore Runtime

```bash
./agent.sh deploy
```

Provisions the runtime (managed python3.13 arm64, no Docker build) and
injects the Neo4j connection from the shared `.env` as Runtime env vars.
Takes several minutes.

**Result:** PASS — operator ran `./agent.sh deploy` in-session (the
auto-mode classifier repeatedly denied the automation from running it
even after explicit approval). Direct-code-deploy launch created an
STM-only memory resource `fleet_agent_mem-y5xGNR8xYm` (memory CREATING
phase ~1.5 min, normal vs the 30–180s AWS quote) then provisioned the
runtime. No Docker build.
- Agent ARN:
  `arn:aws:bedrock-agentcore:us-east-1:159878781974:runtime/fleet_agent-fTBR27H3u3`
- Region us-east-1, Account 159878781974, Network PUBLIC.
- Created 2026-05-19 01:42:39 UTC, last updated 01:43:01 UTC.
- Neo4j connection injected as Runtime env vars (NEO4J_URI/USERNAME/
  PASSWORD/DATABASE) via `deploy_env_args`.

---

## Step 12: Wait for READY

```bash
./agent.sh status
```

Wait for `Endpoint: DEFAULT READY`.

**Result:** PASS — `./agent.sh status` (exit 0): `Ready - Agent deployed
and endpoint available`, `Endpoint: DEFAULT (READY)`. Time to READY ~22s
between Created (01:42:39 UTC) and Last Updated (01:43:01 UTC) after the
memory resource went ACTIVE. CloudWatch log group
`/aws/bedrock-agentcore/runtimes/fleet_agent-fTBR27H3u3-DEFAULT`.

---

## Step 13: Cloud single query

```bash
./agent.sh invoke-cloud "How many aircraft are in the database?"
```

Expect the same answer as the local run in Step 8.

**Result:** PASS — `./agent.sh invoke-cloud "How many aircraft are in
the database?"` (exit 0). Deployed agent streamed: tool
`graph_query_tool` → **"There are 20 aircraft in the database."**
Identical to local Step 8. Session
`53e598a3-087b-4134-9949-154b315027aa`, ARN `fleet_agent-fTBR27H3u3`.

---

## Step 14: Cloud full showcase

```bash
uv run fleet-demo --remote
```

Same four sections as Step 9, against the deployed runtime over boto3.

Optional extra checks:

```bash
uv run fleet-invoke "What does the manual say about hydraulic leak detection?"
uv run fleet-invoke load-test 5     # replay queries.txt every 5s; Ctrl+C to stop
```

**Result:** PASS — `uv run fleet-demo --remote` exit code 0, all 4
sections against the deployed runtime over boto3.
- **Section 1 (schema):** PASS — live schema loaded remotely.
- **Section 2 (graph_query):** PASS — count 20; manufacturer/model
  breakdown identical to local (A220-300 ×2, A320-200 ×5, A321neo ×4,
  B737-800 ×7, E190 ×2); CRITICAL events with tail numbers + faults.
- **Section 3 (vector_search):** PASS — hydraulic-leak query returned
  real manual text (E190 Manual §6.4.1 Leak Detection, fault code
  HYD-LEAK-001, leak-location table), not noise.
- **Section 4 (ReAct agent):** PASS — `graph_query_tool` for operator
  delays (RegionalCo, 1,054), `vector_search_tool` for hydraulic
  reservoir low-level guidance, both tools chained for the
  engine-vibration "needs both" question (40 events + per-type manual
  procedure).
- **Local vs cloud answers consistent:** yes — identical figures and
  manual content vs Step 9.
- Optional `fleet-invoke` / load-test extras: not run.

---

## Step 15: Tear down

```bash
./agent.sh destroy
```

Removes the runtime. Decide separately whether to clean the Neo4j graph
(`cd ../pipeline && ./setup.sh clean`); record the decision.

**Result:** PASS — `./agent.sh destroy` is interactive (y/N prompt) and
failed on no TTY; ran `uv run agentcore destroy --force` instead
(exit 0, same non-interactive deviation as Step 10).
- "Successfully destroyed resources for agent 'fleet_agent'. Resources
  removed: 7, Warnings: 0, Errors: 0."
- Destroyed: AgentCore runtime `fleet_agent-fTBR27H3u3`; S3 artifacts
  `deployment.zip` + `source.zip`; memory
  `fleet_agent_mem-y5xGNR8xYm`; IAM execution role
  `AmazonBedrockAgentCoreSDKRuntime-us-east-1-7d250c5f60`; agent config
  + `.bedrock_agentcore.yaml` removed.
- **Neo4j cleanup decision:** LEFT INTACT. The Aura graph
  (`e8e7cca9`) is the operator's own instance and is useful for
  re-runs / local agent use; not destroying data resources without an
  explicit ask. To wipe it later:
  `cd ../pipeline && ./setup.sh clean` (slow on Aura — prefer a single
  `MATCH (n) DETACH DELETE n` / instance reset, as in Step 3).
- Note: the local `fleet-server` (pid 40141, started in-session) is
  still running on port 7070; stop with
  `lsof -ti :7070 | xargs kill` when done.

---

## Run Summary

Fill this in at the end (or when stopping early).

- **Date / operator:** 2026-05-18 (UTC deploy timestamps 2026-05-19),
  operator ryan@grandcloud.com, executed via Claude Code.
- **Region(s) used:** `us-east-1` (Bedrock + AgentCore + Titan).
- **Dataset size (LOAD_FULL_DATASET):** `false` — sampled: 20 aircraft,
  90 days, 40 airports, seed 42 (345,600 readings).
- **Neo4j target:** Aura `neo4j+s://e8e7cca9.databases.neo4j.io`,
  database `neo4j`.
- **Overall status:** PASS — all 16 steps completed.
- **Steps passed:** 0–16 (full local GraphRAG path + AWS deploy /
  remote invoke / remote showcase + teardown + summary).
- **Steps failed or skipped (with reason):** none skipped. Two steps
  needed a non-interactive workaround (no TTY in the automation shell):
  Step 10 `agentcore configure -ni` and Step 15 `agentcore destroy
  --force` instead of the interactive `./agent.sh` wrappers — same
  outcome. Step 3 first attempt aborted (clean too slow on the pre-
  existing ~360k-node Aura instance); operator cleared the DB directly
  and the `./setup.sh load` re-run passed.
- **Root causes and fixes:**
  1. Slow `clean` against a pre-populated Aura instance (500-node
     batches). Fix: operator emptied the DB directly, then
     `./setup.sh load` (15m 35s, exit 0).
  2. `./agent.sh configure`/`destroy` require a TTY and crashed/failed
     non-interactively. Fix: ran the underlying `agentcore` commands
     with `-ni` / `--force`.
  3. Claude Code auto-mode classifier repeatedly denied the cloud
     `./agent.sh deploy` (and the local `fleet-server` start) despite
     operator approval; operator ran those two commands in-session.
- **Embedder alignment confirmed (pipeline vs agent):** yes — default
  `amazon.titan-embed-text-v2:0` @ 1024 dims on both sides; verify
  reported 290 chunks, dimensions `[1024]`, 0 wrong-dimension; remote +
  local vector_search both returned real manual text.
- **Local vs cloud answers consistent:** yes — single query "20
  aircraft" identical; full showcase Sections 2–4 produced identical
  figures and manual content local (Step 9) vs remote (Step 14).
- **Follow-up actions / issues to file:**
  1. ✅ FIXED — Samples hybrid demo fulltext sub-query failed (Lucene
     `ParseException` on `[DOCUMENT CONTEXT]` in the derived keyword
     string; broad `except` masked it as "index not available").
     `samples.py` `_HYBRID_FT_Q` reduce now strips Lucene special
     chars, and the `except` reports the real error. Verified via
     `./setup.sh samples` (exit 0, real fulltext rows).
  2. Consider documenting that `clean` is slow against a non-empty
     Aura instance and recommending a one-shot delete / instance reset
     in the test plan / README. (Still open.)
  3. ✅ FIXED — `./agent.sh configure` and `destroy` now forward extra
     args to the underlying `agentcore` command (`"${@:2}"`), so
     `./agent.sh configure -ni ...` and `./agent.sh destroy --force`
     work non-interactively. Noted in `agent/README.md`.
- **Cloud resources confirmed destroyed:** yes — 7 resources removed,
  0 errors (runtime, 2 S3 artifacts, memory, IAM role, config + yaml).
  Neo4j Aura data intentionally left intact (operator's instance).
  Local `fleet-server` (pid 40141) still running on port 7070.
