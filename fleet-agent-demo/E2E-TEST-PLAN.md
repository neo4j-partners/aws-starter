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
- [ ] **3.** Pipeline run end to end (`./setup.sh`) completed
- [ ] **4.** Pipeline strict verify passed
- [ ] **5.** Showcase queries run (`./setup.sh samples`)
- [ ] **6.** Agent deps synced (`cd agent && uv sync`)
- [ ] **7.** Local agent server started (`uv run fleet-server`)
- [ ] **8.** Local single query answered (`uv run fleet-cli "..."`)
- [ ] **9.** Local full showcase passed (`uv run fleet-demo`)
- [ ] **10.** Agent configured for AWS (`./agent.sh configure`)
- [ ] **11.** Agent deployed (`./agent.sh deploy`)
- [ ] **12.** Deployment reached READY (`./agent.sh status`)
- [ ] **13.** Cloud single query answered (`./agent.sh invoke-cloud "..."`)
- [ ] **14.** Cloud full showcase passed (`uv run fleet-demo --remote`)
- [ ] **15.** Cloud resources destroyed (`./agent.sh destroy`)
- [ ] **16.** Run Summary written

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
- Next: re-run from the load stage once the DB is empty (`./setup.sh load`
  to skip regenerating CSVs, or full `./setup.sh`).

---

## Step 4: Strict verify

`./setup.sh` already runs `verify --strict`. Re-run it standalone to confirm
a clean read-only pass:

```bash
./setup.sh verify
```

Expect a pass report and exit code 0.

**Result:**
<!-- verify report, exit code, any warnings -->

---

## Step 5: Showcase queries against the graph

```bash
./setup.sh samples
```

Simulates an agent issuing Cypher and vector searches against the loaded
graph. Confirms the dual graph and the `maintenanceChunkEmbeddings` index are
queryable.

**Result:**
<!-- sample outputs, vector search returned real chunks (not noise/empty) -->

---

## Step 6: Sync agent dependencies

```bash
cd ../agent
uv sync
```

**Result:**
<!-- uv sync output -->

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

**Result:**
<!-- server started, schema read at startup, port confirmed -->

---

## Step 8: Local single query

```bash
# Terminal 2
uv run fleet-cli "How many aircraft are in the database?"
```

Expect a numeric answer consistent with the loaded dataset (default ~20
aircraft).

**Result:**
<!-- query, answer, matches expected dataset size -->

---

## Step 9: Local full showcase

```bash
uv run fleet-demo
```

Walks four sections: live schema, `graph_query` (Text2Cypher),
`vector_search` (semantic over manual chunks), and the full ReAct agent.
Section 4 calls Claude for several turns and takes a few minutes.

**Result:**
<!-- each of the 4 sections pass/fail, notable answers, timing -->

---

## Step 10: Configure for AWS deployment

```bash
# from fleet-agent-demo/agent
./agent.sh configure
```

Writes `.bedrock_agentcore.yaml`, pins entrypoint `runtime_app.py`. Required
even if the yaml already exists.

**Result:**
<!-- configure output, account/region/role recorded -->

---

## Step 11: Deploy to AgentCore Runtime

```bash
./agent.sh deploy
```

Provisions the runtime (managed python3.13 arm64, no Docker build) and
injects the Neo4j connection from the shared `.env` as Runtime env vars.
Takes several minutes.

**Result:**
<!-- Agent ARN, dashboard URL, deploy duration, any errors -->

---

## Step 12: Wait for READY

```bash
./agent.sh status
```

Wait for `Endpoint: DEFAULT READY`.

**Result:**
<!-- status output, time to READY -->

---

## Step 13: Cloud single query

```bash
./agent.sh invoke-cloud "How many aircraft are in the database?"
```

Expect the same answer as the local run in Step 8.

**Result:**
<!-- query, answer, matches local result -->

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

**Result:**
<!-- 4 sections pass/fail remote, vector_search returned real manual text,
     load-test stability if run -->

---

## Step 15: Tear down

```bash
./agent.sh destroy
```

Removes the runtime. Decide separately whether to clean the Neo4j graph
(`cd ../pipeline && ./setup.sh clean`); record the decision.

**Result:**
<!-- destroy output, Neo4j cleanup decision and outcome -->

---

## Run Summary

Fill this in at the end (or when stopping early).

- **Date / operator:**
- **Region(s) used:**
- **Dataset size (LOAD_FULL_DATASET):**
- **Neo4j target:**
- **Overall status:** PASS / PARTIAL / FAIL
- **Steps passed:**
- **Steps failed or skipped (with reason):**
- **Root causes and fixes:**
- **Embedder alignment confirmed (pipeline vs agent):** yes / no
- **Local vs cloud answers consistent:** yes / no
- **Follow-up actions / issues to file:**
- **Cloud resources confirmed destroyed:** yes / no
