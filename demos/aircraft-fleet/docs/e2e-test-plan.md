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
(cd graphrag-agent/agentcore/cdk && npm ci)
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
     The 2026-11-22 cloud retest found that this change stops both agent
     Runtimes at startup. See that run below.
  2. Pass a longer `request_timeout` to `SharedMemory.open` in the
     agents' `memory.py`, or speed up the open upstream in
     neo4j-agent-memory.
  3. Done: when a password secret has a `username` key, both agents now
     read the user name from the secret too. The shared `.env` keeps the
     admin user for the pipeline, and no shell export is needed.
  4. Done: the Step 0 text now names `global.anthropic.claude-sonnet-5-5`.
  5. Done: both agents now pin `@aws/agentcore-cdk` 1.2.0 for the
     AgentCore CLI 1.2.0. That CLI syncs the pinned CDK dependencies on
     every build and deploy. It leaves the `aws-cdk-lib` and `aws-cdk`
     ranges from item 8 unchanged and prints a warning for each.
     `agentcore build` synthesized both stacks, and `agent.sh help` and
     `agent.sh status` work in both agents. The 2026-11-22 cloud retest
     ran both deploys with CLI 1.2.0. Both stacks synthesized and reached
     CloudFormation, and `package.json` and `package-lock.json` stayed
     unchanged.
  6. The AgentCore CLI and CDK print the full account ID in deploy logs.
  7. Done: the MCP runtime now gets only `NEO4J_PASSWORD_SECRET_ARN`. An
     image entrypoint reads the password at startup. The 2026-11-22 cloud
     retest passed it.
  8. Done: `npm audit` reports 0 vulnerabilities in both agents' CDK
     folders. It had reported 3, in the `minimatch` and `brace-expansion`
     copies that `aws-cdk-lib` bundles. The advisories are
     GHSA-g3hv-75wg-m249, GHSA-q2hr-2g5m-vwhr, GHSA-qhr7-859c-m2p7, and
     GHSA-6j4f-fj2g-mc7p.
     - **The fix:** `package.json` declares `aws-cdk-lib` as
       `>=2.278.0 <3` and `aws-cdk` as `>=2.1149.0 <3`, and
       `package-lock.json` locks 2.278.0 and 2.1149.0. `aws-cdk-lib`
       2.278.0 clears the advisories. Its cloud assembly needs CLI 2.1149.0
       or later to synthesize.
     - **Why a range:** The AgentCore CLI 1.2.0 rewrites a single pinned
       version to the one it vends, `~2.269.0`, and refuses a newer pin.
       It leaves a range unchanged and prints a warning. No global
       `disableDependencyManagement` setting is needed. The CLI still
       manages `@aws/agentcore-cdk`, `constructs`, and the TypeScript
       packages.
  9. AgentCore keeps the runtime log groups after a destroy, and they have
     no retention. This run left two of them. The deploys also turned on
     CloudWatch Transaction Search for the account.
- **Cloud resources confirmed destroyed:** All three stacks are gone, and
  so are the runtimes, the credential provider, the Gateway, the Cognito
  pool, the IAM roles, and the MCP password secret. List calls confirm it.
  The run kept the `fleet_reader` user, the secrets `fleet/neo4j-reader`
  and `fleet/memory-neo4j`, the shared ECR repository, the two runtime log
  groups, and the loaded graph.

---

## Cloud Retest: 2026-11-22

This run retested the cloud path at main `98064f6`. It covered the changes
made after the 2026-11-21 run: the MCP secret entrypoint, the non-root
image, the user name read from the secret, the AgentCore CLI 1.2.0, and the
`aws-cdk-lib` 2.278.0 and `aws-cdk` 2.1149.0 ranges. It followed the demo
README and the agent READMEs. The graph from the 2026-11-21 run was reused,
so the pipeline did not run again.

**Overall status:** FAIL. The MCP server passed. Both agent Runtimes failed
to start, so the agent cloud steps did not run.

- **Setup:** The run created `fleet_reader` with the `reader` and
  `graphql_app_read_only_<AURA_ID>` roles. It created the secrets
  `fleet/neo4j-reader` and `fleet/memory-neo4j` with the AWS managed key.
  Each holds a JSON `username` and `password`. `.env` got both secret ARNs,
  and `.env.fleet` named `fleet_reader`.
- **Local quick start:** PASS. `uv run fleet-server` started on port 7070
  with the secret ARNs unset. `uv run fleet-cli "How many aircraft are in
  the database?"` answered "The database has **30 aircraft**." in 19
  seconds with one `graph_query_tool` call.
- **MCP deploy:** PASS. `./deploy.py --env fleet` exited 0 after about 5
  minutes. It built image tag `f1b33d3`, created the ECR repository, and
  stored the password in `neo4j-mcp-server-fleet/neo4j-password`. The
  stack reached `CREATE_COMPLETE`.
- **MCP image:** PASS. The image runs as user `app`. Its command is
  `python /app/secret_entrypoint.py`.
- **MCP Runtime settings:** PASS. `get-agent-runtime` showed
  `NEO4J_PASSWORD_SECRET_ARN`, `NEO4J_USERNAME=fleet_reader`, and
  `NEO4J_READ_ONLY=true`. It showed no `NEO4J_PASSWORD`.
- **MCP startup log:** PASS. The container logged "Read NEO4J_PASSWORD
  from the secret in NEO4J_PASSWORD_SECRET_ARN." and then "Uvicorn running
  on http://0.0.0.0:8000".
- **MCP Gateway tests:** PASS. `./cloud.sh --env fleet` listed
  `get_neo4j_schema` and `read_neo4j_cypher`, and all four tool tests
  passed. The schema call worked as `fleet_reader`. `MATCH (a:Aircraft)
  RETURN count(a)` returned 30. A `CREATE` and a `SET` through
  `read_neo4j_cypher` were both refused with "Only MATCH queries are
  allowed for read-query". No probe property was written.
- **MCP log noise:** The Runtime log holds 428 `anyio.ClosedResourceError`
  tracebacks from `mcp.server.streamable_http` "Error in message router".
  Every request still returned 200. The tracebacks come from the upstream
  `mcp-neo4j-cypher` server that the deploy builds from `NEO4J_MCP_REPO`.
  This run records them as known log noise. They are not fixed here.
- **Supervisor local:** PASS. `./agent.sh start` read the memory password
  from `MEM_NEO4J_PASSWORD_SECRET_ARN`. `./agent.sh test-maintenance`
  routed to the Maintenance Agent and reported 227 maintenance events in
  39.4 seconds. `./agent.sh test-operations` routed to the Operations
  Agent and reported 5,145 delays in 23.4 seconds.
- **GraphRAG deploy:** FAIL. `./agent.sh deploy` exited 1 after 7 minutes
  40 seconds. CloudFormation reported "The runtime process exited
  unexpectedly." and the stack rolled back.
- **Supervisor deploy:** FAIL. `./agent.sh deploy` exited 1 after 7
  minutes 25 seconds with the same Runtime error and rollback.
- **CDK dependencies:** PASS. Both deploys printed the CLI warning that it
  leaves the `aws-cdk-lib` and `aws-cdk` ranges unchanged. Synth worked.
  After the deploys, `npm audit` reported 0 vulnerabilities in both CDK
  folders, and git showed no change to `package.json` or
  `package-lock.json`.
- **Not run:** The GraphRAG cloud queries, the supervisor cloud invokes,
  the load test, and the cloud check of the user name read from the
  secret did not run.

### Root cause

Both Runtimes stop at import with `RecursionError: maximum recursion depth
exceeded`. The stack trace ends in `ssl.py` at
`super(SSLContext, SSLContext).options.__set__`. It starts at the
`BedrockModel` client in `fleet_graphrag/server.py`, inside the botocore
credential resolver.

- **The trigger:** AgentCore Runtime starts the code zip under
  OpenTelemetry auto-instrumentation from `aws-opentelemetry-distro`. The
  distro imports botocore and urllib3 before `main.py` runs.
- **The conflict:** Each agent's `__init__.py` then calls
  `truststore.inject_into_ssl()`. Truststore must run before those
  libraries load. Injecting after them causes this recursion on the first
  boto3 client.
- **Local reproduction:** `uv run opentelemetry-instrument python -c
  "import fleet_graphrag.server"` fails with the same `RecursionError`.
  Plain `uv run python` imports it cleanly. The README's local tracing
  command, `uv run opentelemetry-instrument fleet-server`, is affected
  too.
- **Why the 2026-11-21 run passed:** That run deployed before follow-up 1
  added `truststore`.

### Follow-ups from this run

1. Fixed in commit 37c97c4. Each agent now skips the truststore injection
   when the HTTP stack is already imported, and logs one line. In the
   Runtime, TLS then uses the Linux system CA store.
   `tests/test_truststore.py` checks the start under
   `opentelemetry-instrument`. Rerun this retest to confirm it in the cloud.
   Cloud Retest 2 confirmed the fix in the cloud.
   **Note:** The sentence about the Linux system CA store is imprecise.
   `docs/architecture/deployment.md` has the corrected wording. TLS falls
   back to each library's default CA store.
2. The `ClosedResourceError` tracebacks come from the MCP Python SDK's
   stateless HTTP transport. They fill the MCP Runtime log.
3. `scripts/sync-credentials.sh` also copied the old
   `.mcp-credentials.finance.json` into `fraud-memory-agent/`. No finance
   stack is deployed.
4. `./deploy.py --env fleet cleanup` already deletes the stack's password
   secret with no recovery window. CloudTrail shows `force=True` on both
   deletes, so no change is needed.

**Cloud resources confirmed destroyed:** Both `agent.sh destroy --yes`
runs exited 0. `./deploy.py --env fleet cleanup` deleted the MCP Runtime,
the stack, the ECR repository, and the password secret. The run then
deleted `fleet/neo4j-reader`, `fleet/memory-neo4j`, the `fleet_reader`
user, and the three Runtime log groups it created. List calls match the
pre-run snapshot for stacks, Runtimes, credential providers, Gateways,
Cognito pools, IAM roles, log groups, ECR repositories, and secrets.
`.env` and `.env.fleet` are back to the admin user without the secret
ARNs. CloudWatch Transaction Search stays on.

## Cloud Retest 2: 2026-11-22

This run retested the cloud path at main `e16af89` to confirm the truststore
fix from commit 37c97c4. It reused the graph from the 2026-11-21 run. Account
IDs are masked.

**Overall status:** PARTIAL. The truststore fix works in both Runtimes. The
MCP server, the GraphRAG agent, and supervisor routing through
`./agent.sh invoke-cloud` passed. The supervisor load test failed on a
separate bug.

- **Setup:** The run created `fleet_reader` again with the `reader` and
  `graphql_app_read_only_709ad5c7` roles. It created the secrets
  `fleet/neo4j-reader` and `fleet/memory-neo4j`. `.env` got both secret
  ARNs, and `.env.fleet` named `fleet_reader`.
- **Local Runtime start:** PASS. The check under
  `opentelemetry-instrument` exited 0 in both agent folders. The injection
  was skipped in both. The local run printed no "Skipping truststore" line.
- **MCP deploy:** PASS. `./deploy.py --env fleet` exited 0 after 5 minutes
  18 seconds. It built image tag `f1b33d3`, and the stack reached
  `CREATE_COMPLETE`.
- **MCP Gateway tests:** PASS. All four `./cloud.sh --env fleet` tool tests
  passed. `MATCH (a:Aircraft) RETURN count(a)` returned 30. A `CREATE` and
  a `SET` were both refused with "Only MATCH queries are allowed for
  read-query". No probe node or property was written.
- **GraphRAG deploy:** PASS. `./agent.sh deploy` exited 0 after 5 minutes
  25 seconds.
- **GraphRAG cloud queries:** PASS. "How many aircraft are in the
  database?" returned HTTP 200 with "**30 aircraft**". The agent used
  `graph_query_tool`. A question about troubleshooting high EGT returned
  HTTP 200. The agent used `vector_search_tool`.
- **GraphRAG user name from the secret:** PASS. The Runtime environment
  has `NEO4J_USERNAME=neo4j`. Only the secret holds `fleet_reader` and its
  password. `login_from` prefers the secret's `username`, and the graph
  queries succeeded.
- **Supervisor deploy:** PASS. `./agent.sh deploy` exited 0 after 5 minutes
  22 seconds.
- **Supervisor routing:** PASS through `./agent.sh invoke-cloud`. "What are
  the most common maintenance faults?" went to the Maintenance Agent. "What
  are the most common delay causes?" went to the Operations Agent. Each
  request fetched a Gateway token from
  `fleetsupervisor_default_fleet-gateway`.
- **Supervisor invoke client:** FAIL. Two `fleet-supervisor-invoke` calls
  returned "The agent could not complete this request." after about 8
  seconds.
- **Load test:** FAIL. `./agent.sh load-test` ran for about 2 minutes. All
  19 requests failed with `RuntimeError: No workload access token for the
  Gateway token request`.
- **Runtime logs:** PASS for the truststore fix. Each agent's log has 4
  "Skipping truststore: botocore, httpx, requests, urllib3 already
  imported; using the default CA store." lines. Neither log has a
  `RecursionError` or `CERTIFICATE_VERIFY_FAILED`. The GraphRAG log has no
  traceback. The supervisor log has no traceback for the
  `invoke-cloud` requests.

### Root cause of the load test failure

The supervisor fetches its Gateway token from AgentCore Identity on the
request path. Identity needs the request's workload access token. The
Runtime issues that token only when the call carries a `runtimeUserId`.

- **The AgentCore CLI:** `agentcore invoke` always sends a user ID. Its
  default is `"default"`, so `./agent.sh invoke-cloud` works.
- **The invoke client:** `fleet_supervisor/client/transport.py` called
  `invoke_agent_runtime` without `runtimeUserId`. `fleet-supervisor-invoke`
  and `load-test` use that client, so every request failed.
- **Fix:** Commit 00222c9 sends `runtimeUserId` `"default"` from the
  client.

**Cloud resources:** Both `agent.sh destroy --yes` runs exited 0. The
secrets `fleet/neo4j-reader` and `fleet/memory-neo4j` were force-deleted.
The fleet MCP stack, `fleet_reader`, and the `.env` changes stayed in place
for Cloud Retest 3.

## Cloud Retest 3: 2026-11-22

This run retested the agents at main `00222c9`. The GraphRAG agent moved to
mcp 2.3.0. Both agent CDK apps moved to TypeScript 7.0.2 and `@types/node`
26.6.6. The supervisor client now sends `runtimeUserId`. The run reused the
fleet MCP stack, `fleet_reader`, and the `.env` changes from Cloud Retest 2.
Account IDs are masked.

**Overall status:** FAIL. Both agent deploys stopped at the AgentCore CLI's
dependency check, so no agent cloud step ran.

- **Setup:** The run created `fleet/neo4j-reader` and `fleet/memory-neo4j`
  again. `.env` got the new secret ARNs.
- **Local Runtime start:** PASS. The check under
  `opentelemetry-instrument` exited 0 in both agent folders. With logging
  on, each agent printed "Skipping truststore: botocore, httpx, requests,
  urllib3 already imported; using the default CA store." The GraphRAG
  agent ran mcp 2.3.0.
- **CDK dependencies:** PASS. `./agent.sh deploy` saw the newer
  `package-lock.json` and ran `npm ci`. npm reported 0 vulnerabilities.
  Both CDK folders then had TypeScript 7.0.2. `npm run build` exited 0 in
  both folders.
- **GraphRAG deploy:** FAIL. `./agent.sh deploy` exited 1 after 9 seconds.
- **Supervisor deploy:** FAIL. `./agent.sh deploy` exited 1 with the same
  error.
- **Not run:** The GraphRAG invokes, the supervisor routing checks, the two
  `fleet-supervisor-invoke` calls, the load test, and the Runtime log
  checks did not run. No agent Runtime was created.

Both deploys printed this error:

```
Error: agentcore/cdk/package.json pins @types/node ~26.6.6, newer than the
version this CLI vends (~24.13.3). agentcore/cdk/package.json pins
typescript ~7.0.2, newer than the version this CLI vends (~5.9.3). Run
'agentcore update', or run 'agentcore config disableDependencyManagement
true' to manage the CDK dependencies yourself.
```

### Follow-ups from this run

1. The AgentCore CLI 1.2.0 refuses CDK pins newer than the versions it
   vends. The TypeScript 7.0.2 and `@types/node` 26.6.6 pins need a newer
   CLI or `disableDependencyManagement`. The other option is to keep the
   pins at or below TypeScript 5.9.3 and `@types/node` 24.13.3.
   **Resolved:** Commits b59bf92 and 10f0d9e revert both CDK apps to
   TypeScript 5.9.3 and `@types/node` 24.13.3. CLI 1.2.0 is the newest
   release, so TypeScript 7 waits for a CLI that vends it.
2. `./agent.sh destroy --yes` exits 1 when nothing is deployed. The CLI
   reports that the project "declares no resources to deploy" and that no
   stack exists.
   **Resolved:** Commits ea56382 and 1a497f9 make both destroys check the
   stack first. With no stack they skip the deploy and run the final check,
   which exits 0 only when AWS shows nothing left.
3. The `runtimeUserId` fix in commit 00222c9 is still untested in the
   cloud.

**Cloud resources confirmed destroyed:** No agent stack existed. Both
`agent.sh destroy --yes` runs found nothing to remove.
`./deploy.py --env fleet cleanup` exited 0 after 23 minutes. It deleted the
MCP Runtime, the stack, the ECR repository, and the password secret. The
run then force-deleted `fleet/neo4j-reader` and `fleet/memory-neo4j`. It
dropped `fleet_reader` and deleted the three Runtime log groups from
Cloud Retest 2. List calls match the pre-run snapshot for stacks, Runtimes,
credential providers, Gateways, Cognito pools, IAM roles, log groups, ECR
repositories, and secrets. `.env` and `.env.fleet` match their pre-run
copies. The fleet credentials copies are removed. The fraud agent's
`.mcp-credentials.json` is unchanged. CloudWatch Transaction Search stays
on, and the fleet graph is unchanged.

## Cloud Retest 4: 2026-11-22

This run retested the cloud path at main `9674a00`. Both agent CDK apps are
back on TypeScript 5.9.3 and `@types/node` 24.13.3. The supervisor client
sends `runtimeUserId` from commit 00222c9. The run built the fleet MCP stack
from scratch and reused the graph from the 2026-11-21 run. Account IDs are
masked.

**Overall status:** PASS. The MCP server, both agent deploys, the GraphRAG
queries, supervisor routing, the invoke client, and the load test all
passed. The Runtime logs show no errors.

- **Setup:** The run created `fleet_reader` again with the `reader` and
  `graphql_app_read_only_709ad5c7` roles. It created the secrets
  `fleet/neo4j-reader` and `fleet/memory-neo4j`. `.env` got both secret
  ARNs, and `.env.fleet` named `fleet_reader`.
- **Local Runtime start:** PASS. The check under
  `opentelemetry-instrument` exited 0 in both agent folders. With logging
  on, each agent printed the "Skipping truststore" line. The injection was
  skipped in both.
- **MCP deploy:** PASS. `./deploy.py --env fleet` exited 0. It built image
  tag `f1b33d3`, and the stack reached `CREATE_COMPLETE`. CloudFormation
  created the stack in 4 minutes 33 seconds. The whole command took 45
  minutes because the Mac went into idle sleep during the CDK wait.
- **MCP Gateway tests:** PASS. All four `./cloud.sh --env fleet` tool tests
  passed. `MATCH (a:Aircraft) RETURN count(a)` returned 30. A `CREATE` and
  a `SET` were both refused with "Only MATCH queries are allowed for
  read-query". No probe node or property was written.
- **CDK build:** PASS. Both CDK folders ran TypeScript 5.9.3 with
  `@types/node` 24.13.6. `npm run build` exited 0 in both folders.
- **GraphRAG deploy:** PASS. `./agent.sh deploy` exited 0 after 5 minutes
  28 seconds.
- **GraphRAG cloud queries:** PASS. "How many aircraft are in the
  database?" returned HTTP 200 with "**30 aircraft**". The agent used
  `graph_query_tool`. A question about troubleshooting high EGT returned
  HTTP 200. The agent used `vector_search_tool` and cited the A220 and B737
  maintenance manuals.
- **Supervisor deploy:** PASS. `./agent.sh deploy` exited 0 after 5 minutes
  8 seconds.
- **Supervisor routing:** PASS through `./agent.sh invoke-cloud`. "What are
  the most common maintenance faults?" went to the Maintenance Agent. "What
  are the most common delay causes?" went to the Operations Agent. Both
  agents called the Gateway tools `get_neo4j_schema` and
  `read_neo4j_cypher`.
- **Supervisor invoke client:** PASS. "Which aircraft had the most
  maintenance events?" went to the Maintenance Agent in 18.1 seconds.
  "Which routes have the most flight delays?" went to the Operations Agent
  in 32.3 seconds. The `runtimeUserId` fix from commit 00222c9 works in the
  cloud.
- **Load test:** PASS. `./agent.sh load-test` ran for about 3 minutes and
  sent 6 requests. The first 5 finished in 31 to 44 seconds each. Each one
  went to the expected agent. The final totals showed 0 unexpected routes
  and 0 errors. The sixth request was still running when the test was
  stopped.
- **Runtime logs:** PASS. Each agent's log has 2 "Skipping truststore"
  lines. Neither log has a `RecursionError`, a `CERTIFICATE_VERIFY_FAILED`,
  a traceback, or "No workload access token". The supervisor log shows 10
  handled requests and 11 Gateway token fetches.

### Follow-ups from this run

1. A SIGINT to the `load-test` process did not stop it between requests.
   The loop kept sending requests until a SIGTERM stopped it.
   **Resolved:** This is not a load test bug. The run started the load
   test as a background job from a script. Bash then sets SIGINT to
   ignored, and Python keeps that setting. A recheck with job control on,
   as in a terminal, stopped the loop mid-request and printed the totals.
   Ctrl+C in a terminal works.
2. A long `./deploy.py` run stalls while the Mac sleeps. Running it under
   `caffeinate -i` keeps the CDK wait alive.
   **Resolved:** `neo4j-mcp-server/README.md` Step 3 now has this tip.

**Cloud resources confirmed destroyed:** Both `agent.sh destroy --yes` runs
exited 0. `./deploy.py --env fleet cleanup` exited 0 after 4 minutes 15
seconds. It deleted the MCP Runtime, the stack, the ECR repository, and the
password secret. The run then force-deleted `fleet/neo4j-reader` and
`fleet/memory-neo4j`. It dropped `fleet_reader` and deleted the three new
Runtime log groups. List calls match the pre-run snapshot for stacks,
Runtimes, credential providers, Gateways, Cognito pools, IAM roles, log
groups, ECR repositories, and secrets. `.env` and `.env.fleet` match their
pre-run copies. The fleet credentials copies are removed. The run also removed
`neo4j-mcp-server/.env.fleet.readonly`, which held the dropped
`fleet_reader` login. `create_reader.py` reads that file as input. The next
setup must write it again before it runs `create_reader.py`. The fraud agent's
`.mcp-credentials.json` is unchanged. CloudWatch Transaction Search stays
on, and the fleet graph is unchanged.

## Cloud Retest 5: 2026-11-22

This run retested the cloud path at main `85965ef`. It covered the fleet
demo and the fraud memory agent. The run built the fleet MCP stack and the
finance MCP stack from scratch. It reused the fleet graph from the
2026-11-21 run. Account IDs are masked.

**Overall status:** FAIL. Every fleet step passed. The fraud agent deployed
and was destroyed cleanly, but it could not answer a query. Its NAMS memory
workspace points at an external database that fails every request. The
fraud deploy check also ran before the new runtime was READY.

### Fleet

- **Setup:** The run created `fleet_reader` again with the `reader` and
  `graphql_app_read_only_709ad5c7` roles. It created the secrets
  `fleet/neo4j-reader` and `fleet/memory-neo4j`. `.env` got both secret
  ARNs, and `.env.fleet` named `fleet_reader`.
- **Local Runtime start:** PASS. The check under
  `opentelemetry-instrument` exited 0 in both agent folders. Each agent
  printed the "Skipping truststore" line, and the injection was skipped.
- **MCP deploy:** PASS. `./deploy.py --env fleet` exited 0 after 5
  minutes 20 seconds under `caffeinate -i`. It built image tag `f1b33d3`,
  and the stack reached `CREATE_COMPLETE`.
- **MCP Gateway tests:** PASS. All four `./cloud.sh --env fleet` tool tests
  passed. `MATCH (a:Aircraft) RETURN count(a)` returned 30. A `CREATE` and
  a `SET` were both refused with "Only MATCH queries are allowed for
  read-query". No probe node or property was written.
- **Agent deploys:** PASS. The two deploys ran in parallel. The GraphRAG
  `./agent.sh deploy` exited 0 after 5 minutes 33 seconds. The supervisor
  `./agent.sh configure` exited 0. Its `./agent.sh deploy` exited 0 after
  5 minutes 25 seconds.
- **GraphRAG cloud queries:** PASS. "How many aircraft are in the
  database?" returned HTTP 200 with "**30 aircraft**". The agent used
  `graph_query_tool`. A question about troubleshooting high EGT returned
  HTTP 200. The agent used `vector_search_tool` and cited the A220 and B737
  maintenance manuals.
- **Supervisor routing in the cloud:** PASS. "What are the most common
  maintenance faults?" went to the Maintenance Agent through
  `./agent.sh invoke-cloud`. "What are the most common delay causes?" went
  to the Operations Agent. Both agents called the Gateway tools
  `get_neo4j_schema` and `read_neo4j_cypher`.
- **Supervisor routing tests:** PASS. `./agent.sh test-maintenance` and
  `./agent.sh test-operations` both exited 0 against a local
  `./agent.sh start` server. The first went to the Maintenance Agent in
  36.6 seconds. The second went to the Operations Agent in 22.9 seconds.
- **Supervisor invoke client:** PASS. "Which aircraft had the most
  maintenance events?" went to the Maintenance Agent in 22.5 seconds.
  "Which routes have the most flight delays?" went to the Operations Agent
  in 29.5 seconds.
- **Load test:** PASS. `./agent.sh load-test` ran for 2 minutes 40
  seconds. Three requests finished in 19 to 53 seconds each. Two went to
  the Maintenance Agent and one went to the Operations Agent. Each went to
  the expected agent. The final totals showed 0 unexpected routes and 0
  errors. A fourth request was still running when a SIGTERM stopped the
  test.
- **Runtime logs:** PASS. Each agent's log has 4 "Skipping truststore"
  lines. Neither log has a `RecursionError`, a `CERTIFICATE_VERIFY_FAILED`,
  a traceback, or "No workload access token".

### Fraud

- **Finance MCP deploy:** PASS. `./deploy.py --env finance` exited 0
  after 5 minutes 17 seconds. The stack reached `CREATE_COMPLETE`. All four
  `./cloud.sh --env finance` tool tests passed. `.env.finance` points at
  the fleet Aura instance `709ad5c7`, so the finance tools read the fleet
  graph.
- **Configure:** PASS. `./agent.sh configure` ran through `expect`. It
  wrote `.bedrock_agentcore.yaml` for `us-east-1` with short-term memory
  and a direct code deploy. The memory prompt ignored an `s` to skip
  memory, so the run kept the default short-term memory.
- **Deploy:** FAIL. `./agent.sh deploy` uploaded the code package and
  created the runtime, memory, and execution role. It exited 1 after 4
  minutes 59 seconds. The smoke test reported "Runtime is not ready:
  status='CREATING'". `verify_agentcore_runtime.py` reads the status once
  and does not wait for READY.
- **Verify:** FAIL. `./agent.sh verify` found the runtime READY. The graph
  smoke call failed with "NAMS GET
  https://memory.neo4jlabs.com/v1/conversations → 424:
  external_database_error". A direct call to the NAMS API returned the
  same 424. Its message says the workspace's external database failed the
  request.
- **Cloud invoke:** FAIL. `./agent.sh invoke-cloud "Find circular transfer
  chains"` exited 0. The response was a single error event with the same
  NAMS 424.
- **Runtime logs:** The fraud log has 118 events. Its 4 traceback lines
  come from the two NAMS failures in `neo4j_agent_memory.connect`. The log
  has no `RecursionError`, no `CERTIFICATE_VERIFY_FAILED`, and no "No
  workload access token". `./agent.sh logs --errors` reported "No failed
  traces found in session".
- **Destroy:** PASS. `./agent.sh destroy` ran through `expect` to answer
  its confirmation. It exited 0 after 6 seconds. It removed 7 resources,
  including the runtime, the memory, and `.bedrock_agentcore.yaml`.

### Follow-ups from this run

1. `./agent.sh deploy` in `fraud-memory-agent` fails on a first deploy.
   `verify_agentcore_runtime.py` checks the runtime status once. A new
   runtime is still `CREATING` when `agentcore deploy` returns. A fix would
   poll `get_agent_runtime` until READY or a timeout. The fix needs
   approval first.
2. The fraud agent cannot answer any query until its NAMS workspace has a
   working database. The workspace's external database fails every
   request. The fraud graph Aura instances in `graph-loader/.env` and
   `.env.finance.admin` no longer resolve in DNS. `.env.finance` points at
   the fleet instance. This is environment setup, not a code bug.
   Decision 2026-11-22: left blocked. Unblocking needs a new Aura instance
   for the fraud graph and a NAMS workspace pointed at a working database.
3. `./agent.sh invoke-cloud` in the fraud agent exits 0 when the response
   is an error event. `./agent.sh logs --errors` also finds no failed
   traces after that error. A script that checks the exit code reads this
   as a pass.
4. `agentcore destroy` leaves three things behind. It keeps the empty
   `bedrock-agentcore-codebuild-sources-X-us-east-1` S3 bucket and the
   memory log group under `/aws/vendedlogs/bedrock-agentcore/memory/`. It
   also keeps the 52 MB `.bedrock_agentcore/` dependency cache in the
   agent folder. The run deleted all three by hand.
5. Retest 4 says `create_reader.py` writes
   `neo4j-mcp-server/.env.fleet.readonly` again at the next setup. That is
   wrong. `create_reader.py` reads that file as input, so the run
   recreated it before setup.
6. The AWS SSO token expired during the run. `agent.sh` and the AgentCore
   CLI then failed with "Token is expired". The AWS CLI still had cached
   role credentials, so the run exported them and repeated the calls. This
   is a test environment issue, not a code bug.

**Cloud resources confirmed destroyed:** Both fleet `agent.sh destroy
--yes` runs exited 0. `./deploy.py --env fleet cleanup` exited 0 after 4
minutes 11 seconds. It deleted the MCP Runtime, the stack, and the
password secret. It kept the shared `neo4j-mcp-server` ECR repository,
because the finance stack still used it. `./deploy.py --env finance
cleanup` exited 0 after 4 minutes 11 seconds. It deleted the finance
Runtime, the stack, the secret, and the ECR repository. The run then
force-deleted `fleet/neo4j-reader` and `fleet/memory-neo4j`. It dropped
`fleet_reader` and deleted the six new log groups. List calls in
`us-east-1` and `us-west-2` match the pre-run snapshot for stacks,
Runtimes, memories, workload identities, credential providers, Gateways,
Cognito pools, CodeBuild projects, IAM roles, S3 buckets, log groups, ECR
repositories, and secrets. `.env`, `.env.fleet`, the fraud agent's
`.mcp-credentials.json`, and `.mcp-credentials.finance.json` match their
pre-run copies. The fleet credentials copies, `.env.fleet.readonly`, and
the fraud agent's toolkit files are removed. The fleet graph is unchanged.
