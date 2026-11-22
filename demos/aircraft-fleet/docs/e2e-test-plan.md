# Aircraft Fleet Demo: End-to-End Test Plan

## How to use this document

This is a working log, not just a reference. As you run the test:

1. **Record each step as you go.** Under each step there is a "Result" line.
   Fill it in with what actually happened: the command you ran, the key
   output, pass or fail, and anything you had to change. Do not wait until
   the end to write it all up.
2. **Capture real evidence.** Paste the relevant command output, counts,
   and error text. A bare "worked" is not a result. Leave out account IDs,
   ARNs, and passwords.
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
3. Run the agent locally against that graph (`graphrag-agent/`).
4. Deploy the agent to AWS AgentCore Runtime and drive it remotely.
5. Tear down cloud resources.
6. Run the supervisor agent over the same graph through the Neo4j MCP
   server (`supervisor-agent/`).

All paths below are relative to `demos/aircraft-fleet/`.

---

## Checklist

Tick each box only after the step's result is recorded below.

- [x] **0.** Prerequisites verified (uv, Python 3.12+, AWS creds, Bedrock
      model access, reachable Neo4j)
- [x] **1.** Shared `.env` created and filled in
- [x] **2.** Pipeline deps synced (`cd pipeline && uv sync`)
- [x] **3.** Pipeline run end to end (`./setup.sh`) completed
- [x] **4.** Pipeline strict verify passed
- [x] **5.** Showcase queries run (`./setup.sh samples`)
- [x] **6.** Agent deps synced (`cd graphrag-agent && uv sync`)
- [x] **7.** Local agent server started (`uv run fleet-server`)
- [x] **8.** Local single query answered (`uv run fleet-cli "..."`)
- [x] **9.** Local full showcase passed (`uv run fleet-demo`)
- [x] **10.** AgentCore CLI installed and deploy settings set in `.env`
- [x] **11.** Agent deployed (`./agent.sh deploy`)
- [x] **12.** Deployment reached READY (`./agent.sh status`)
- [x] **13.** Cloud single query answered (`./agent.sh invoke-cloud "..."`)
- [x] **14.** Cloud full showcase passed (`uv run fleet-demo --remote`)
- [x] **15.** Cloud resources destroyed (`./agent.sh destroy`)
- [x] **16.** Run Summary written
- [x] **17.** MCP server deployed with `--env fleet` against the same Neo4j
- [x] **18.** Supervisor credentials synced
- [x] **19.** Supervisor local server started (`./agent.sh start`)
- [x] **20.** Supervisor local routing verified (`./agent.sh test-maintenance`,
      `./agent.sh test-operations`)
- [x] **21.** Supervisor deployed and invoked in the cloud
      (`./agent.sh deploy`, `./agent.sh invoke-cloud "..."`)
- [x] **22.** Supervisor and MCP server cloud resources destroyed

---

## Step 0: Prerequisites

Confirm before starting:

- `uv --version` and Python 3.12+ available.
- AWS credentials configured (`aws sts get-caller-identity` succeeds). If
  using SSO: `aws sso login --sso-session <your-sso-session>`.
- Bedrock model access enabled in the target region for
  `global.anthropic.claude-sonnet-5-5` and Titan embeddings
  (`amazon.titan-embed-text-v2:0`). The pipeline's extraction, both agents,
  and memory extraction all default to Sonnet 5.5.
- A reachable Neo4j instance (Aura works well). Have the URI, username, and
  password ready.

Region is a single shared knob: `AWS_REGION` (defaults to `us-east-1` for
both the pipeline's Bedrock calls and the agent). Set it once in the shared
`.env` if you want a non-default region, and confirm the LLM and Titan models
are enabled there. Record the region used.

**Result:** PASS (2026-11-21)
- **Tools:** The run used `uv 0.13.6`, Python 3.13.18, Node v26.13.0, CDK
  2.1143.0, Docker 29.8.2, and cypher-shell 2026.04.0.
- **AWS identity:** The SSO role `<SSO_ROLE>` in account `<ACCOUNT_ID>` was
  signed in. No re-login was needed.
- **Region:** The region was `us-east-1`, from `AWS_REGION` in the shared
  `.env`.
- **Bedrock models:** The code now defaults to
  `global.anthropic.claude-sonnet-5-5` for extraction, the agents, and memory
  extraction. The step text above now names Sonnet 5.5.
  `list-inference-profiles` shows `global.anthropic.claude-sonnet-5-5`.
  `amazon.titan-embed-text-v2:0` is `ACTIVE`.
- **Neo4j targets:** The fleet graph is Aura
  `neo4j+s://<AURA_ID>.databases.neo4j.io` on Neo4j 5.27, and it held 0 nodes
  at the start. Agent memory is a second Aura instance,
  `neo4j+s://<MEM_AURA_ID>.databases.neo4j.io`.
- **Read-only user:** The run created `fleet_reader` on the fleet instance
  for both agents and the MCP server. Its roles are `reader`,
  `graphql_app_read_only_<AURA_ID>`, and `PUBLIC`. On Aura Professional the
  `reader` role cannot run procedures, so the GraphQL read-only role is needed
  for schema calls. A write probe as `fleet_reader` failed with `42NFF`
  access denied. The pipeline keeps the admin user.
- **Problem found: Python TLS on macOS.** Aura now serves a certificate that
  chains to `SSL.com TLS RSA Root CA 2022`. The macOS `/etc/ssl/cert.pem`
  does not hold that root, and uv's Python trusts that file by default. The
  Python driver failed with `SSLCertVerificationError`. cypher-shell
  connected, because Java uses the macOS keychain, which has the root.
  certifi 2026.10.23 also has the root. Every local Python step in this run
  set `SSL_CERT_FILE` to the certifi bundle from the graphrag-agent venv. No
  code changed.

---

## Step 1: Configure the shared `.env`

One `.env` at the `demos/aircraft-fleet/` root is read by both projects.

```bash
cd demos/aircraft-fleet
cp .env.sample .env
# Edit .env: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD.
# Leave LOAD_FULL_DATASET=false for a fast run.
# Keep the embedder aligned: default amazon.titan-embed-text-v2:0 at 1024
# dims on both pipeline and agent. If you change it, set EMBED_MODEL_ID and
# EMBED_DIMENSIONS to match on both sides.
```

**Result:** PASS (2026-11-21). The run copied the operator's `.env` into the
test checkout.
- **Settings:** The file sets `NEO4J_URI`, `NEO4J_USERNAME=neo4j`,
  `NEO4J_PASSWORD`, `NEO4J_DATABASE=neo4j`, the four `MEM_NEO4J_*` values,
  `LOAD_FULL_DATASET=false`, `LLM_PROVIDER=bedrock`, and
  `AWS_REGION=us-east-1`.
- **Fixes to the copy:** The copied `AWS_REGION` line ended in a stray `"`,
  and it was removed. The obsolete `BEDROCK_REGION` line was deleted.
- **Embedder:** The embedder stayed at the default,
  `amazon.titan-embed-text-v2:0` at 1024 dimensions, on both sides.
- **User split:** `NEO4J_USERNAME` in `.env` stays `neo4j`, so the pipeline
  writes as admin. The agent steps export `NEO4J_USERNAME=fleet_reader` in
  the shell, which wins over `.env`.

---

## Step 2: Sync pipeline dependencies

```bash
cd pipeline
uv sync
```

**Result:** PASS (2026-11-21). `uv sync` resolved 54 packages and checked 48
with no conflicts.

---

## Step 3: Run the ingestion pipeline

```bash
# from demos/aircraft-fleet/pipeline
./setup.sh
```

This runs all five stages: generate CSVs, clean, load operational graph,
enrich (chunk + Titan embeddings + Claude extraction over `manuals/`), index
+ fuse, strict verify. Stage 3 is the only stage that calls Bedrock.

If credentials or model access fail mid-run, record the failing stage. To
isolate stages: `./setup.sh generate`, `./setup.sh load-operational` (no LLM,
no key), `./setup.sh load`, `./setup.sh verify`.

**Result:** PASS (2026-11-21) on the second attempt. `./setup.sh` exited 0
and reported `Done in 9m 25s`.
- **First attempt:** The first attempt failed. Stage 1 generated the CSVs.
  The connection check then failed with `Unable to retrieve routing
  information`, caused by the TLS problem in Step 0. The rerun set
  `SSL_CERT_FILE` to the certifi bundle.
- **Stage 1 (generate):** The generator used 30 aircraft, 90 days, 40
  airports, and seed 42. It wrote 120 systems, 490 components, 360 sensors,
  777,600 readings, 227 maintenance events, 14,280 flights, 5,145 delays, and
  33 removals. The events split into 46 CRITICAL, 62 MAJOR, and 119 MINOR.
- **Stage 2 (clean):** The instance was already empty. `[OK] Database
  cleared (0 relationships, 0 nodes deleted)`.
- **Stage 3 (schema and load):** The run created 13 constraints, 5 range
  indexes, and 4 fulltext indexes. It loaded 798,325 operational nodes. The
  readings load reported `[OK] No readings skipped.`
- **Stage 3 (enrichment):** Five manuals produced 337 chunks with
  embeddings. Extraction created 449 MaintenanceProcedure, 329 Fault, 230
  ComponentReference, 148 OperatingLimit, 141 SystemReference, 5 Document,
  and 5 AircraftModel nodes. That is 1,644 enrichment nodes in all.
- **Relationships:** The graph holds 832,768 relationships.
- **Strict verify:** The verify that `setup.sh` runs passed. `[OK] Node
  counts match the CSVs` and `[OK] Verification passed.`

---

## Step 4: Strict verify

`./setup.sh` already runs `verify --strict`. Re-run it standalone to confirm
a clean read-only pass:

```bash
./setup.sh verify
```

Expect a pass report and exit code 0.

**Result:** PASS (2026-11-21). The standalone `./setup.sh verify` exited 0
with `[OK] Verification passed.`
- **Counts:** The totals were 798,325 operational nodes, 1,644 enrichment
  nodes, and 832,768 relationships. They match Step 3.
- **Embeddings:** All 337 chunks have embeddings. The only dimension found
  was `[1024]`, and 0 were the wrong dimension.
- **Indexes:** `maintenanceChunkEmbeddings` is VECTOR ONLINE and
  `maintenanceChunkText` is FULLTEXT ONLINE. All 19 required constraints
  are present.
- **Vector smoke test:** The smoke test returned 1 result with a best score of
  1.0000.
- **Cross-links:** The counts were Document to Aircraft 30, AircraftModel to
  Aircraft 30, SystemReference to System 1,355, and Sensor to OperatingLimit
  1,383.
- **Data quality:** Every orphan check returned 0.

---

## Step 5: Showcase queries against the graph

```bash
./setup.sh samples
```

Simulates an agent issuing Cypher and vector searches against the loaded
graph. Confirms the dual graph and the `maintenanceChunkEmbeddings` index are
queryable.

**Result:** PASS (2026-11-21). `./setup.sh samples` exited 0 and printed
`All samples complete.`
- **Sections:** All 14 sections returned real data. They run from the fleet
  overview and the system hierarchy through the extracted entities,
  cross-links, vector, fulltext, and adjacent-chunk searches.
- **Vector similarity:** The similar chunks scored from 0.8542 to 0.8898.
  They came from all five aircraft types.
- **Hybrid search:** The hybrid comparison returned 10 fulltext rows and 8
  vector rows, with 0 chunks in both sets. The fulltext fix from the
  2026-05-18 run holds.

---

## Step 6: Sync agent dependencies

```bash
cd ../graphrag-agent
uv sync
```

**Result:** PASS (2026-11-21). `uv sync` resolved 133 packages and checked
131 with no conflicts.

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

**Result:** PASS (2026-11-21). Port 7070 was free. The server started with
`NEO4J_USERNAME=fleet_reader` exported. `/ping` returned
`{"status":"Healthy"}`.
- **Secrets:** `.env` sets both secret ARNs, so the local server read both
  passwords from Secrets Manager. The log shows `Reading
  NEO4J_PASSWORD_SECRET_ARN from Secrets Manager` and the same line for
  `MEM_NEO4J_PASSWORD_SECRET_ARN`.
- **Model:** The startup line names `global.anthropic.claude-sonnet-5-5` on
  port 7070.

---

## Step 8: Local single query

```bash
# Terminal 2
uv run fleet-cli "How many aircraft are in the database?"
```

Expect a numeric answer consistent with the loaded dataset (default 30
aircraft).

**Result:** PASS (2026-11-21) on the second attempt.
- **First attempt:** The first query failed with `Could not open the memory
  database`. The server log shows `Memory open failed: Connecting the memory
  client took longer than 30.0s.` The memory open runs 44 serial schema
  checks against Aura: 25 `SHOW INDEXES` and 15 `SHOW CONSTRAINTS`. Each
  took about 340 ms from this machine. A timed open took 18 to 21 seconds,
  and the first cold open went past the 30-second default `request_timeout`
  in neo4j-agent-memory. A failed open is not cached, so the next request
  opens again.
- **Second attempt:** The query routed to `graph_query_tool` and answered
  **"The database has 30 aircraft."** That matches the dataset. The call
  took 28.7 seconds, most of it the memory open.

---

## Step 9: Local full showcase

```bash
uv run fleet-demo
```

Walks five sections: live schema, `graph_query` (Text2Cypher),
`vector_search` (semantic over manual chunks), the full ReAct agent, and
memory. The agent and memory sections call Claude for several turns and take
a few minutes. The 2026-05-18 result below predates the memory section.

**Result:** PASS (2026-11-21). `uv run fleet-demo` exited 0 after 79
seconds, and all five sections ran.
- **Section 1 (schema):** The agent printed the live schema it reasons over.
- **Section 2 (graph_query):** The count returned 30 aircraft. The grouped
  count matched the generator: A220-300 5, A320-200 5, A321neo 5,
  B737-800 5, and E190 10. The traversal returned five CRITICAL events with
  tail numbers and faults.
- **Section 3 (vector_search):** The hydraulic leak search returned the
  B737-800 manual, section 6.4.1 Leak Detection, with a score of 1.000.
- **Section 4 (agent):** The agent picked `graph_query_tool` for the
  operator question. It named RegionalCo, with 1,361 of 2,749 flights
  delayed, or 49.5%. It picked `vector_search_tool` for the reservoir
  question and used both tools for the question that needs both.
- **Section 5 (memory):** Turn 1 found no EGT maintenance events and listed
  the fault types. Turn 2 resolved "that fault" to EGT exceedance, filed as
  Overheat, and quoted the E190 manual. Memory carried the context.

---

## Step 10: Set up the AgentCore CLI deploy

Deployment uses the AgentCore CLI. Install it once:

```bash
npm install -g @aws/agentcore
```

The CDK dependencies are git-ignored. Install them once in a fresh clone, or
the deploy stops with "CDK dependencies are missing":

```bash
(cd graphrag-agent/agentcore/cdk && npm install)
```

The project lives in `graphrag-agent/agentcore/`. Set the deploy settings in
the shared `.env`:

- **Neo4j connection:** Set `NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_DATABASE`.
- **Memory connection:** Set `MEM_NEO4J_URI`, `MEM_NEO4J_USERNAME`, and `MEM_NEO4J_DATABASE`.
- **Passwords:** Set `NEO4J_PASSWORD_SECRET_ARN` and `MEM_NEO4J_PASSWORD_SECRET_ARN` to the complete ARNs of the Secrets Manager secrets that hold the passwords.

Record the AgentCore CLI version and the two secret names. Do not record the ARNs.

**Result:** PASS (2026-11-21).
- **CLI version:** The AgentCore CLI was version 1.1.0. Version 1.2.0 was
  available, and the run kept 1.1.0.
- **CDK dependencies:** `npm install` in `graphrag-agent/agentcore/cdk`
  finished.
- **Deploy settings:** `.env` sets the Neo4j and memory URIs, users, and
  databases. The deploy ran with `NEO4J_USERNAME=fleet_reader` exported,
  so the runtime connects as the read-only user.
- **Secret names:** The password secrets are `fleet/neo4j-reader` and
  `fleet/memory-neo4j`. Each holds a JSON `username` and `password`.

---

## Step 11: Deploy to AgentCore Runtime

```bash
# from demos/aircraft-fleet/graphrag-agent
./agent.sh deploy
```

The deploy builds a code zip and deploys the CDK stack. It builds no Docker
image. The first deploy creates the `default` target in
`agentcore/aws-targets.json`. Record how long the deploy takes.

**Result:** PASS (2026-11-21). `./agent.sh deploy` exited 0 after 5
minutes 20 seconds.
- **Target:** The deploy created the `default` target in
  `agentcore/aws-targets.json` for account `<ACCOUNT_ID>` in `us-east-1`.
- **Stack:** The CLI deployed `AgentCore-AircraftFleet-default` and printed
  `deployed project 'AircraftFleet' to target 'default'`.
- **Log note:** The CLI prints the full account ID in its `created default
  deployment target` and `verifying AWS account` lines.

---

## Step 12: Check the deployment

```bash
./agent.sh status
```

Expect the Runtime ARN and a deployed state. Record the state that `status`
reports.

**Result:** PASS (2026-11-21). `./agent.sh status` exited 0. It listed one
resource, the runtime `graphrag_agent`, with `deploymentState` set to
`deployed` and a Runtime ARN ending in `AircraftFleet_default_graphrag_agent-<ID>`.

---

## Step 13: Cloud single query

```bash
./agent.sh invoke-cloud "How many aircraft are in the database?"
```

Expect the same answer as the local run in Step 8.

**Result:** PASS (2026-11-21). The call returned HTTP 200 as an event
stream in 15 seconds. The agent called `graph_query_tool` and answered
**"The database has 30 aircraft."** That matches Step 8. The cold runtime
opened memory with no timeout.

---

## Step 14: Cloud full showcase

```bash
uv run fleet-demo --remote
```

This runs the same five sections as Step 9 against the deployed runtime over
boto3.

Optional extra checks:

```bash
uv run fleet-invoke "What does the manual say about hydraulic leak detection?"
uv run fleet-invoke load-test 5     # replay queries.txt every 5s; Ctrl+C to stop
```

Record whether the local and cloud answers match.

**Result:** PASS (2026-11-21). `uv run fleet-demo --remote` exited 0 after
112 seconds. The banner read `DEPLOYED: AgentCore runtime`. The optional
`fleet-invoke` checks were not run.
- **Section 1 (schema):** The runtime printed the same live schema as Step 9.
- **Section 2 (graph_query):** The figures matched Step 9. The count was 30,
  the per-model split was the same, and the traversal returned five
  CRITICAL events.
- **Section 3 (vector_search):** The top chunk was the same B737-800
  section 6.4.1 Leak Detection, with a score of 1.000.
- **Section 4 (agent):** The tool choices matched Step 9. The operator
  answer was the same, RegionalCo with 1,361 of 2,749 flights delayed.
  The question that needs both tools called the graph once and the
  manuals twice. It found 27 vibration exceedance events.
- **Section 5 (memory):** Turn 1 found no EGT events and offered Overheat
  as the nearest fault. Turn 2 took "that fault" as Overheat, which is EGT
  exceedance, and quoted the manuals under fault code ENG-OVH-006.
- **Local versus cloud:** The answers match. The facts are the same, and
  only the wording of the free-text answers differs.

---

## Step 15: Tear down

```bash
./agent.sh destroy
```

The command asks for confirmation. Pass `--yes` to skip the question. It
checks that the active AWS credentials belong to the target's account. When it
finishes, it asks CloudFormation whether the stack
`AgentCore-AircraftFleet-default` still exists. Record that answer.

Decide separately whether to clean the Neo4j graph, and record the decision.
On Aura, a single `MATCH (n) DETACH DELETE n` or an instance reset is faster
than `./setup.sh clean`.

**Result:** PASS (2026-11-21). `./agent.sh destroy --yes` exited 0 after
3 minutes 54 seconds.
- **Stack check:** The command printed `Cleanup complete. Stack
  AgentCore-AircraftFleet-default does not exist in us-east-1.` A separate
  `describe-stacks` call returned `Stack ... does not exist`.
- **Project files:** The tracked `agentcore/` files are unchanged in git.
- **Graph decision:** The run kept the graph, because Steps 17 to 22 query
  the same instance.

---

## Step 17: Deploy the MCP server for the fleet graph

The supervisor reaches Neo4j through the MCP Gateway, not a direct driver.
Point a `fleet` MCP deployment at the same `NEO4J_URI` the pipeline loaded.

```bash
cd ../../../neo4j-mcp-server
cp .env.sample .env.fleet   # skip if present. Set the same NEO4J_* values
./deploy.py --env fleet
./deploy.py --env fleet credentials   # writes .mcp-credentials.fleet.json
```

**Result:** PASS (2026-11-21). `./deploy.py --env fleet` exited 0 after 4
minutes 27 seconds.
- **Read-only user:** `.env.fleet` names `fleet_reader`, the same
  read-only user the GraphRAG agent uses. The finance deployment follows
  the same pattern.
- **Connection test:** The deploy's `cypher-shell` check printed `OK Neo4j
  connection successful`.
- **Stack:** The `neo4j-mcp-server-fleet` stack already existed from an
  earlier deploy. CloudFormation updated it to `UPDATE_COMPLETE`, and the
  runtime is `READY`.
- **Runtime user:** `get-agent-runtime` shows `NEO4J_USERNAME` set to
  `fleet_reader`, and the server runs with `NEO4J_READ_ONLY` set. The
  Gateway lists only `get_neo4j_schema` and `read_neo4j_cypher`.
- **Credentials:** `./deploy.py --env fleet credentials` exited 0 and wrote
  `.mcp-credentials.fleet.json`. The token is valid for 24 hours.
- **Gateway test:** `./cloud.sh --env fleet` passed all four tool tests.
  The node count was 799,970. That is the 798,325 operational nodes, the
  1,644 enrichment nodes, and the one `Dataset` stamp node.

## Step 18: Sync supervisor credentials

```bash
# from neo4j-mcp-server
../scripts/sync-credentials.sh
```

The script copies `.mcp-credentials.fleet.json` to `.mcp-credentials.json`
in `demos/aircraft-fleet/`.

**Result:** PASS (2026-11-21). The script copied
`.mcp-credentials.fleet.json` to `demos/aircraft-fleet/.mcp-credentials.json`,
and `cmp` found the two files identical. The script skipped the
quickstart and finance targets, because this run did not deploy them. It
reported `Credentials synced to 1 of 3 directories.` Git ignores both
credentials files.

## Step 19: Start the supervisor locally

```bash
cd ../demos/aircraft-fleet/supervisor-agent
uv sync
./agent.sh start                   # serves http://localhost:7071
```

**Result:** PASS (2026-11-21). `uv sync` resolved 125 packages and checked
123. Port 7071 was free. The server read `MEM_NEO4J_PASSWORD_SECRET_ARN`
from Secrets Manager and started with `global.anthropic.claude-sonnet-5-5`.
`/ping` returned `{"status":"Healthy"}`. The run set `SSL_CERT_FILE` as in
Step 0.

## Step 20: Verify local routing

```bash
./agent.sh test-maintenance        # routes to the Maintenance Agent
./agent.sh test-operations         # routes to the Operations Agent
```

**Result:** PASS (2026-11-21). Both tests exited 0 and routed to the right
agent. Each agent called `get_neo4j_schema` and `read_neo4j_cypher`
through the Gateway.
- **Maintenance:** The supervisor routed the faults question to the
  Maintenance Agent, which answered in 49.2 seconds. It counted 227 events
  across 8 faults, led by Sensor drift 52, Overheat 45, and Leak 43. The
  critical counts add up to 46, which matches the generator.
- **Operations:** The supervisor routed the delay question to the
  Operations Agent, which answered in 22.4 seconds. It counted 5,145
  delays: Weather 1,493, NAS 1,295, Maintenance 1,275, and Carrier 1,082.
  That matches the generator.

## Step 21: Deploy and invoke the supervisor in the cloud

```bash
./agent.sh configure
./agent.sh deploy
./agent.sh status
./agent.sh invoke-cloud "Which routes have the most delays?"
```

**Result:** PASS (2026-11-21).
- **Configure:** `./agent.sh configure` found the existing project in
  `agentcore/` and installed the CDK dependencies. `npm` reported 3
  vulnerabilities, 2 moderate and 1 high.
- **Deploy:** `./agent.sh deploy` exited 0 after 5 minutes 8 seconds. It
  added the `fleet-gateway` credential and created the credential provider
  `fleetsupervisor_default_fleet-gateway`. It deployed the stack
  `AgentCore-fleetsupervisor-default`.
- **Status:** The runtime `supervisor` showed `deploymentState` set to
  `deployed`.
- **Invoke:** The call returned HTTP 200 after 46 seconds. The supervisor
  routed to the Operations Agent. That agent called `get_neo4j_schema` once
  and `read_neo4j_cypher` twice through the Gateway. It ranked BOS to DFW
  first with 29 delayed flights, then SEA to ATL with 28. It used the
  correct totals of 14,280 flights and 5,145 delays, and listed the top
  causes for each route.

## Step 22: Tear down the supervisor and the MCP server

```bash
./agent.sh destroy
cd ../../../neo4j-mcp-server
./deploy.py --env fleet cleanup
```

**Result:** PASS (2026-11-21). Both commands exited 0, and the local
supervisor server is stopped.
- **Supervisor:** `./agent.sh destroy --yes` took 3 minutes 56 seconds.
  It removed `AgentCore-fleetsupervisor-default` and the credential
  provider `fleetsupervisor_default_fleet-gateway`. It reported `Cleanup
  complete. Nothing is deployed in target 'default'.` The tracked
  `agentcore.json` is unchanged, and `agentcore/.env.local` is empty.
- **MCP server:** `./deploy.py --env fleet cleanup` took 4 minutes 11
  seconds. It deleted the runtime, destroyed `neo4j-mcp-server-fleet`,
  and deleted the secret `neo4j-mcp-server-fleet/neo4j-password`.
- **ECR repository:** The run answered no when cleanup asked to delete the
  `neo4j-mcp-server` repository. The repository dates from 2026-11-20,
  every MCP deployment shares it, and it holds four images that this run
  did not push. This run added one image, tagged `latest` and the source
  commit.
- **Check:** CloudFormation lists no AgentCore, fleet, or MCP stacks.
  AgentCore lists no runtimes, gateways, OAuth2 or API key credential
  providers, or memories. IAM lists no fleet or MCP roles. Secrets Manager
  still holds only the two kept secrets.

---

## Run Summary

Fill this in at the end (or when stopping early).

This summary records the 2026-11-21 run. The 2026-05-18 summary is in git
history.

- **Date / operator:** The run took place on 2026-11-21. Claude Code ran it
  from the integration worktree on branch `fleet-refresh`.
- **Region(s) used:** The run used `us-east-1` for Bedrock, AgentCore,
  Titan, Secrets Manager, and Cognito.
- **Dataset size (LOAD_FULL_DATASET):** The flag was `false`. The sampled
  data has 30 aircraft, 90 days, 40 airports, seed 42, and 777,600
  readings.
- **Neo4j target:** The graph is Aura
  `neo4j+s://<AURA_ID>.databases.neo4j.io`, database `neo4j`. Memory is a
  second Aura instance. The pipeline wrote as admin. Both agents and the
  MCP server read as `fleet_reader`.
- **Overall status:** All of Steps 0 to 22 passed.
- **Steps passed:** Steps 0 to 22 passed. Steps 3 and 8 passed on a second
  attempt.
- **Steps failed or skipped (with reason):** No step was skipped. The
  optional `fleet-invoke` checks in Step 14 were not run.
- **Root causes and fixes:** The run changed no code.
  1. **Step 3 TLS failure:** The macOS CA file that uv's Python trusts
     lacks `SSL.com TLS RSA Root CA 2022`, which Aura's certificate now
     chains to. The workaround was `SSL_CERT_FILE` set to the certifi
     bundle for every local Python run.
  2. **Step 8 memory timeout:** The memory open runs 44 serial schema
     checks and took 18 to 21 seconds. The first cold open passed the
     30-second default timeout. The retry passed.
  3. **Copied `.env`:** The copied `.env` had a stray quote on
     `AWS_REGION` and an obsolete `BEDROCK_REGION` line. Both were fixed
     in the gitignored copy only.
- **Embedder alignment confirmed (pipeline vs agent):** Alignment is
  confirmed. Both sides use `amazon.titan-embed-text-v2:0` at 1024
  dimensions. Verify found 337 chunks with only `[1024]`, and the local
  and remote vector searches returned the same manual text.
- **Local vs cloud answers consistent:** The answers are consistent. Both
  answered 30 aircraft. The showcase figures, the top manual chunk, and the
  tool choices matched between Step 9 and Step 14.
- **Follow-up actions / issues to file:**
  1. Done: the pipeline and both agents now depend on `truststore`. Each
     package's `__init__.py` calls `truststore.inject_into_ssl()`, so
     Python verifies TLS against the macOS keychain. Local runs no longer
     need `SSL_CERT_FILE`. `populate-aircraft-db verify` and a `fleet-cli`
     query both passed against the fleet Aura with `SSL_CERT_FILE` unset.
  2. Pass a longer `request_timeout` to `SharedMemory.open` in the
     agents' `memory.py`, or speed up the open upstream in
     neo4j-agent-memory.
  3. Done: when a password secret has a `username` key, both agents now
     read the user name from the secret too. The shared `.env` keeps the
     admin user for the pipeline, and no shell export is needed.
  4. Done: the Step 0 text now names `global.anthropic.claude-sonnet-5-5`.
  5. The AgentCore CLI 1.2.0 is out. This run used 1.1.0.
  6. The AgentCore CLI and CDK print the full account ID in deploy logs.
  7. The MCP runtime carries the Neo4j password as a plain
     `NEO4J_PASSWORD` environment variable, resolved at deploy time.
  8. `npm` reports 3 vulnerabilities in the supervisor's CDK
     dependencies, 2 moderate and 1 high.
  9. AgentCore keeps the runtime log groups after a destroy, and they have
     no retention. This run left two of them. The deploys also turned on
     CloudWatch Transaction Search for the account.
- **Cloud resources confirmed destroyed:** All three stacks are gone, and
  so are the runtimes, the credential provider, the Gateway, the Cognito
  pool, the IAM roles, and the MCP password secret. List calls confirm it.
  The run kept the `fleet_reader` user, the secrets `fleet/neo4j-reader`
  and `fleet/memory-neo4j`, the shared ECR repository, the two runtime log
  groups, and the loaded graph.
