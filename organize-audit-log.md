# Reorganization Audit Log

A running log of every change made while implementing [organize.md](./organize.md). The newest entries are at the bottom. Each entry records what changed, why, and how it was checked.

## 2026-09-28

### Setup

- Confirmed the working tree was clean apart from the untracked `organize.md`.
- Asked the user four questions and recorded the answers in `organize.md` under Implementation Status.
- Installed `lychee` 0.24.2 with `brew install lychee`.
- Created this audit log.

### Phase 1: Fix documentation drift and add the drift guard

**Drift table rows fixed:**

- `README.md`: Rewrote the `finance-agent` bullet. It now describes a Strands fraud agent with `core/`, `finance_graph/`, `client/`, and `server/`, using the Neo4j Agent Memory Service.
- `neo4j-agentcore-agents/README.md`: Rewrote the `finance-agent` table row. Removed the `langgraph/` and `strands/` variant paragraph. Replaced the `langgraph/agent.sh` quick start with `./agent.sh configure`, `./agent.sh deploy`, `./agent.sh invoke-cloud`, and the `uv run finance-server` / `finance-cli` local run. Removed the CloudFormation section, because `cfn/` does not exist. Checked the commands against `agent.sh` and `pyproject.toml`.
- `neo4j-agentcore-agents/sync-credentials.sh`: The error hint now says `./deploy.py && ./deploy.py credentials`.
- `neo4j-agentcore-agents/orchestrator-agent/core/credentials.py`: The hint now says `cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .` and no longer mentions a sibling agent.
- `infra-samples/aura-agents/README.md`: The screenshot link now points at `../../images/auraagentsapikey.png`.
- `CLAUDE.md`: Replaced the two nonexistent `infra_samples/` samples with `simple-oauth-gateway` and `aura-agents` commands taken from their READMEs. Changed `databrick_samples/` to `infra-samples/databrick-samples/` in the commands and the components table.
- **`deploy.sh` references:** Changed `deploy.sh` to `deploy.py` in `infra-samples/databrick-samples/` (`README.md`, `MANUAL-SETUP.md`, `neo4j-mcp-http-connection.ipynb`, and `setup_databricks_secrets.sh`), `langgraph-mcp-agent/README.md`, `docs/ARCHITECTURE.md`, and `fleet-agent-demo/pipeline/README.md`. Confirmed that `deploy.py` supports `redeploy`, `stack`, `status`, `credentials`, and `cleanup`. The notebook still parses as JSON.
- `setup_databricks_secrets.sh` lines 8 and 158: Fixed `cd ../neo4j-agentcore-mcp-server` to `cd ../../neo4j-agentcore-mcp-server`.

**Found while fixing:**

- **Gateway pattern `deploy.sh`:** `infra-samples/simple-oauth-gateway/deploy.sh` is a real script, so its `./deploy.sh` references were left alone. The drift guard now retires `deploy.sh` everywhere except `patterns/gateway-rbac-interceptor/`.
- **Databricks credentials path:** `setup_databricks_secrets.sh` line 57 reads `$PROJECT_ROOT/neo4j-agentcore-mcp-server/.mcp-credentials.json`, and `PROJECT_ROOT` is `infra-samples/`, so the script cannot find credentials today. Phase 2 already updates this script's path, so the fix happens there.
- **Five broken links:** `lychee` found five broken links that were not in the drift table.
  - Removed a link to `AWS_DATABRICKS.md` from `databrick-samples/README.md`. The file was deleted in an earlier cleanup commit.
  - Fixed the MCP server link in `databrick-samples/README.md` to `../../neo4j-agentcore-mcp-server/`.
  - Removed the link to `docs/IAM.md` from `langgraph-mcp-agent/README.md`. The file was deleted in an earlier cleanup commit.
  - Fixed `orchestrator-agent/README.md`, which linked `../fleet-agent/`, to point at `../../fleet-agent-demo/agent/`.
  - Removed the "See also FIX.md" line from `neo4j-agentcore-mcp-server/ARCHITECTURE.md`. The file was deleted in an earlier cleanup commit.

**Drift guard:**

- Added `scripts/check-docs.sh`, which has `links`, `names`, and `all` modes. The link check runs `lychee --offline` over tracked and untracked, non-ignored `*.md` and `*.ipynb` files. The name check runs `git grep -P` for each retired name. Both skip the excluded paths and `uv.lock`. The retired-name list is empty until the end of Phase 2.
- Added `organize-audit-log.md` and `scripts/check-docs.sh` to the excluded paths. Both name old folders on purpose.
- Added `.github/workflows/check-docs.yml`, which runs on pull requests and on manual dispatch. It installs `lychee` 0.24.2 from the GitHub release tarball. The extract command was tested against the real tarball.
- **Result:** `scripts/check-docs.sh` passes locally. It checked 311 links in 54 files and found 0 errors.
- **Limitation:** `lychee` reads notebooks as plain text, so it checks only full URLs in `.ipynb` files, not relative links.

**Decisions from the user:**

- **Stale memory docs:** The user chose to delete them. Ran `git rm` on `neo4j-agentcore-agents/docs/memory-fixes.md` and `future-improvements.md`. They described code that no longer exists. Git history keeps them. No other file linked to them. `agent-memory-strands.md` has no stale paths and still moves to `fraud-memory-agent/docs/` in Phase 2.
- **Slide source comment:** The user chose to fix source paths only. Line 630 of `docs/slides/current/aws-neo4j-grounded-enterprise-ai.md` now cites `finance-agent/README.md` and `finance-agent/server/runtime_app.py`. The slide text was not changed. Line 621 gets its new folder path in Phase 2.
- Updated the drift table, the agent memory docs bullet, and the status table in `organize.md`.

**Phase 1 result:** Complete.

### Phase 2: Move folders

**Folder moves:** Every move used `git mv`, so history follows each file.

- `neo4j-agentcore-mcp-server/` moved to `neo4j-mcp-server/`.
- `neo4j-agentcore-agents/langgraph-mcp-agent/` moved to `quickstart/`.
- `fleet-agent-demo/` moved to `demos/aircraft-fleet/`. Its `agent/` folder became `graphrag-agent/`.
- `neo4j-agentcore-agents/orchestrator-agent/` moved to `demos/aircraft-fleet/supervisor-agent/`.
- `sec-filings-graphrag-demo/` moved to `demos/sec-filings-graphrag/`.
- `neo4j-agentcore-agents/finance-agent/` moved to `demos/fraud-amazon-quick/fraud-memory-agent/`. Its `finance_graph/` folder stays inside it until Phase 3.
- `data-agent/` moved to `demos/fraud-amazon-quick/fraud-iceberg/`.
- `infra-samples/databrick-samples/` moved to `integrations/databricks/`.
- `infra-samples/aura-agents/` moved to `integrations/neo4j-aura-agents/`.
- `infra-samples/simple-oauth-gateway/` moved to `patterns/gateway-rbac-interceptor/`.

**Smaller moves:**

- `sync-credentials.sh` and `test-s3-access.sh` moved to `scripts/`.
- `fintech-demo.md` moved to `docs/proposals/sec-filings-graphrag.md`.
- `images/auraagentsapikey.png` moved to `integrations/neo4j-aura-agents/images/`.
- `databricks-mcp-setup.md` moved from the MCP server to `integrations/databricks/`.
- `agent-memory-strands.md` moved to `fraud-memory-agent/docs/`.
- `FIX_32.md` moved to `patterns/gateway-rbac-interceptor/docs/troubleshooting.md`.
- `E2E-TEST-PLAN.md` moved to `demos/aircraft-fleet/docs/e2e-test-plan.md`.

**Deletions:**

- Ran `git rm` on `images/Sagemaker Domains.png` and `images/sagemakeruibuild.png`, per decision 8.
- Ran `git rm -f` on `neo4j-agentcore-agents/README.md`. The `-f` was needed because Phase 1 had edited the file. The root README sample matrix replaces it.
- Removed the empty `infra-samples/` and `neo4j-agentcore-agents/docs/` folders.

**Local state:** `git mv` on a directory also moved the ignored and untracked files inside it. This was tested in the scratchpad first. The `.env`, `.mcp-credentials*.json`, and `.bedrock_agentcore/` files moved with their folders, so no hand moves were needed. The plan says the opposite, so its note on untracked state is wrong.

**Credential sync:** `scripts/sync-credentials.sh` now uses the per-target mapping from the plan. A missing source prints a warning with the matching `./deploy.py --env NAME` hint. The script exits 1 when nothing was synced. It was tested against a scratchpad copy, not the real credential files.

**Code and script path updates:**

- `supervisor-agent/core/credentials.py` and `fraud-memory-agent/core/credentials.py` now print `cp ../../../neo4j-mcp-server/.mcp-credentials.fleet.json` and `.mcp-credentials.finance.json` hints.
- `fraud-memory-agent/.env.example` now points at `../../../neo4j-mcp-server/.env.finance`.
- `quickstart/agent.sh` and `quickstart/neo4j_mcp_agent/core.py` now use `../neo4j-mcp-server/`.
- `pipeline/setup.sh` now tells the user to point `neo4j-mcp-server/.env.fleet` at the new `NEO4J_URI`.
- The fleet root comments now say `aircraft-fleet` and `graphrag-agent/` in `.env.sample`, `pipeline/src/populate_aircraft_db/config.py`, `graphrag-agent/agent.sh`, `agent/config.py`, and `agent/retrieval.py`.
- `neo4j-mcp-server/client/mcp_local_client.py` and `mcp_operations.py` comments now name the new folders.
- `.gitignore` line 194 now ignores `demos/fraud-amazon-quick/fraud-iceberg/.public-urls.txt`. Confirmed with `git check-ignore`.
- `integrations/databricks/setup_databricks_secrets.sh` now sets `PROJECT_ROOT` two levels up and reads `neo4j-mcp-server/.mcp-credentials.json`. This fixes the Phase 1 finding.
- `integrations/databricks/neo4j-mcp-http-connection.ipynb` now names `neo4j-mcp-server` and `integrations/databricks`. The notebook still parses as JSON.
- `fraud-memory-agent/agent.sh`, `client/transport.py`, and `server/runtime_app.py` now name `fraud-memory-agent/` where they meant the folder. Package names, Docker tags, and the `source` metadata value still say `finance-agent`.

**Documentation updates:**

- The root `README.md` now has the sample matrix, a note on `--env`, the suggested learning path, and sections for the MCP server, the quickstart, the demos, and the integrations and patterns.
- `CLAUDE.md` now uses the new folders in every command block and in the components table.
- `docs/ARCHITECTURE.md` now names `neo4j-mcp-server/`, `quickstart/`, `demos/`, `graphrag-agent`, and `supervisor-agent`.
- The slide at lines 621 and 630 now names `demos/fraud-amazon-quick/fraud-memory-agent`.
- The sample READMEs now use the new relative paths: MCP server, quickstart, pipeline, graphrag-agent, supervisor-agent, fraud-memory-agent, `finance_graph`, Aura agents, and Databricks.
- `demos/aircraft-fleet/README.md` now covers three projects and has a Step 4 for the supervisor.
- `demos/aircraft-fleet/docs/e2e-test-plan.md` now covers the supervisor in Steps 17 to 22. Each new step reads "Not run."

**Drift guard:**

- The retired-name check is on. It retires `neo4j-agentcore-agents`, `neo4j-agentcore-mcp-server/`, `infra-samples`, `databrick-samples`, `fleet-agent-demo`, `data-agent`, and `langgraph-mcp-agent`. The underscore spellings are retired too.
- `data-agent` uses the pattern `data-agent(?!-)`, so the real S3 bucket names `data-agent-neo4j-euw1` and `data-agent-finance-tables` still pass.
- `deploy.sh` is retired outside `patterns/gateway-rbac-interceptor/` and `CLAUDE.md`. `CLAUDE.md` lists the gateway pattern's own `./deploy.sh` commands.
- Tested the guard with a planted file. It flagged `fleet-agent-demo`, `data-agent/`, and `./deploy.sh`, and it passed the bucket name.
- **Held back:** The plain `neo4j-agentcore-` prefix is not retired yet. All 23 remaining hits are stack names, OAuth scopes, Gateway hostnames, or the MCP server `pyproject.toml` name. Those change in Phases 4 and 5. `finance-agent`, `orchestrator-agent`, and `finance_graph` are also held back for Phases 3 and 4.

**Validation:**

- `scripts/check-docs.sh` passes. It checked 324 links in 50 files with 0 errors, and it found no retired names.
- `bash -n` passes on every edited shell script.
- `python3 -m py_compile` passes on every edited Python file.

**Interpretations to confirm with the user:**

- Credential hints and READMEs name the per-env files `.env.fleet`, `.env.finance`, `.mcp-credentials.fleet.json`, and `.mcp-credentials.finance.json`. This matches the plan's sync mapping.
- Two files outside the plan's list were updated: `graphrag-agent/agent/__init__.py` and the SEC notebook's fallback path.
- `databricks-mcp-setup.md` Step 0 gained a `cd ../../neo4j-mcp-server` line, because the file no longer sits in the MCP server folder.
- `CLAUDE.md` had three stale lines that were fixed during the rewrite. The fleet `.env.sample` lives at the demo root, not in `pipeline/` or `agent/`. The fraud agent has `core/`, not `common/`. The MCP section now shows the `--env fleet` and `--env finance` deploys.
- Two history lines in the e2e test plan were reworded to name the new folders.
- `CLAUDE.md` was added to the `deploy.sh` exception.

**Found while moving:**

- **Leftover folder:** `neo4j-agentcore-agents/` still holds three ignored local files: `.claude/settings.local.json`, `.DS_Store`, and `.mcp-credentials.json`. The credentials file is stale. It points at the old `simple-neo4j-mcp-server` stack in `us-west-2`, and its token expired on 2026-01-23. These were left for the user to decide.
- **Ignored Databricks script:** `setup_databricks_secrets.sh` matches `.gitignore` line 207, `*_secret*`. It exists only locally, so its edits do not show in git. This predates the reorganization.
- **Fleet README order:** Step 3 of `demos/aircraft-fleet/README.md` has a `cd` sequence that assumes the wrong starting folder. This predates the reorganization and was not changed.
- **ARCHITECTURE.md content:** The "Fleet Agent" section describes an MCP ReAct agent with `local_cli.py`. The `graphrag-agent` folder it now points at uses a direct Neo4j driver and has no `local_cli.py`. Only the path was changed.

**Phase 2 result:** All planned work is done. The phase stays In progress until the user decides the leftover folder and the interpretations above.

**Decisions from the user:**

- **Leftover folder:** The user chose to delete it. Removed `neo4j-agentcore-agents/` and its three ignored files. Nothing tracked by git was lost.
- **Interpretations:** The user accepted all of them.
- **Ignored Databricks script:** The user chose to fix it. Added `!integrations/databricks/setup_databricks_secrets.sh` to `.gitignore` after the `*_secret*` rule. Checked the script first. It reads every value from the credentials file and holds no secrets. `git check-ignore -v` now reports the negation rule, and the script shows as untracked. It is not staged, so the user adds it with the commit.
- **Fleet README Step 3:** The user chose to fix it. Step 2 ends in `graphrag-agent/`, so the `cd graphrag-agent` in Step 3 failed. Removed that line and added a sentence that says Step 3 runs from `graphrag-agent/`.
- **ARCHITECTURE.md Fleet Agent section:** The user chose to rewrite it. The section now describes the Strands agent in `graphrag-agent/`, its two tools, the direct Neo4j driver connection, and the `fleet-server` and `fleet-cli` commands. The facts came from `runtime_app.py`, `agent/tools.py`, `agent/config.py`, and `pyproject.toml`. The heading stayed `### Fleet Agent`, so the table of contents anchor still works.
- **Still stale in ARCHITECTURE.md:** The System Overview still calls the agents "LangGraph-based agents that query Neo4j via the MCP server". Its diagram still draws the Fleet Agent calling the Gateway and Cognito. These sit outside the rewritten section and were not changed.
- `scripts/check-docs.sh` passes after these changes. It checked 325 links with 0 errors and found no retired names.

**Phase 2 result:** Complete.

### Phase 3: Assemble the fraud demo

**Decisions from the user before starting:** The plan did not settle four points, so the user was asked.

- **Layout:** The user chose a package folder. The Python files live in `graph-loader/finance_graph/`, and Phase 4 renames it to `graph_loader/`.
- **Config:** The user chose `graph-loader/.env`. The `NEO4J_*` block moves out of the agent's `.env.example`.
- **Agent dependencies:** The user chose to remove `neo4j` from the agent and re-lock it.
- **Naming:** The user chose the final names now. The project is `fraud-graph-loader`, and its scripts are `fraud-graph-load`, `fraud-graph-enrich`, and `fraud-graph-analyze`.
- Recorded these choices under Implementation Status in `organize.md`.

**Checked before moving:**

- `fraud-iceberg/data/` and `fraud-memory-agent/finance_graph/data/` hold the same seven files with identical blob hashes.
- The two `enrich_gds.py` files run the same algorithm. The `fraud-iceberg` copy is a `uv run --script` file with its own copy of `_connection_settings`, a longer docstring, and a reworded comment.
- `analyze_graph.py` is a `uv run --script` file. It has its own `connection_settings` with the same logic as the loader's.
- The local `fraud-memory-agent/.env` sets only `MEMORY_API_KEY`, so no local Neo4j values needed to move.
- No code in the agent's `core/`, `client/`, `server/`, `scripts/`, or `tests/` imports `neo4j`.

**Moves:**

- Ran `git mv` on `fraud-memory-agent/finance_graph/` to `graph-loader/finance_graph/`.
- Ran `git mv` on the data folder to `fraud-amazon-quick/data/`.
- Moved `README.md` and `ontology.md` up to `graph-loader/`.
- Ran `git mv` on `fraud-iceberg/analyze_graph.py` to `graph-loader/finance_graph/analyze_graph.py`.
- Ran `git rm -rf` on `fraud-iceberg/data/` and `git rm -f` on `fraud-iceberg/enrich_gds.py`. The `-f` was needed because the Phase 2 renames of those files were still staged. `cmp` confirmed the data matched the kept copy first.

**Code changes:**

- `enrich_gds.py` keeps the `finance_graph` copy's code and its shared `_connection_settings` import. It takes the longer docstring from the `fraud-iceberg` copy, reworded for the new commands. The GDS projection names still say `finance_account_*`.
- `load_neo4j.py` now reads `DATA_DIR` from `fraud-amazon-quick/data/`. Its closing message names `fraud-graph-enrich`.
- `analyze_graph.py` lost its `uv run --script` header. Its docstring and empty-result message now name `fraud-graph-enrich` and `fraud-graph-analyze`. It keeps its own `connection_settings` function.
- Added `graph-loader/pyproject.toml`. It names the project `fraud-graph-loader`, depends on `neo4j>=6.0` and `python-dotenv>=1.2.2`, and defines the three `fraud-graph-*` scripts.
- Added `graph-loader/.env.example` with the `NEO4J_*` and `GDS_SESSION_MEMORY` settings. The `NEO4J_*` lines are uncommented there, because the loader requires them. `.env` is ignored and `.env.example` is tracked there, which `git check-ignore` confirmed.
- The agent's `.env.example` lost the loader block. A short note now points at `../graph-loader/.env`.
- The agent's `pyproject.toml` lost `finance_graph`, the two `finance-graph-*` scripts, and `neo4j`. Its `python-dotenv` comment now names `server/runtime_app.py`.
- `uv lock` in the agent removed two lines. `neo4j` is still installed through `neo4j-agent-memory`.
- `uv lock` in `graph-loader` created `uv.lock` with 4 packages.

**Validation so far:**

- `uv sync` in `graph-loader` succeeded.
- `fraud-graph-load --help` and `fraud-graph-analyze --help` printed their usage.
- The loader's row readers parsed every CSV in `../data/`: 25,000 accounts, 7,500 merchants, 25,000 customers, 250,000 transactions, and 300,000 transfers.

**Incident:** I ran `fraud-graph-enrich --help` to check that it starts. `enrich_gds.py` has no argument parser, so it ignored `--help` and started the enrichment. It loaded a `NEO4J_URI` for `347f6e76-staging.databases.neo4j.io` from a source I did not find. The shell had no `NEO4J_*` variables, and no `.env` in the loader's parent folders sets them. The connection failed at DNS lookup, so no query reached any database. The user said not to run it again and that they will fix it later. No loader command runs again in this phase.

**Doc changes after the incident:**

- The agent README links now point at `../data/`, `../graph-loader/README.md`, and `../graph-loader/ontology.md`. Its setup steps now name `graph-loader/.env`.
- The `fraud-iceberg` README now links to `enrich_gds.py` and `analyze_graph.py` under `../graph-loader/finance_graph/`. Its enrich and analyze commands now run from `graph-loader/`. Its data links point at `../data/`.
- `fraud-iceberg/scripts/finance_iceberg.py` now reads `DATA_DIR` from `fraud-amazon-quick/data/`. The folder exists at that path.
- `graph-loader/ontology.md` line 152 now names `fraud-amazon-quick/data/`. Lines 194 and 195 still name `finance-agent` and `finance_graph`, which Phase 4 renames.
- The `graph-loader` README now says the data lives in `../data/`. Its commands now run from `graph-loader/` with `uv sync` and the `fraud-graph-*` names. It gained a short "Analyze the graph" section, because `analyze_graph.py` moved here.
- The root README matrix gained a `graph-loader/` row. The fraud memory agent row now says its data comes from `graph-loader/`. The fraud demo section gained a `graph-loader/` bullet, and the agent bullet no longer lists `finance_graph/`.
- CLAUDE.md now lists the three `fraud-graph-*` commands in the Fraud Investigation Demo block. The components table row now names the graph loader.
- Wrote `demos/fraud-amazon-quick/README.md` as one walkthrough. It has six steps: load, enrich, deploy the MCP server with `--env finance`, run the agent, write the Iceberg tables, and present in Amazon Quick. The repo does not script the Quick setup, so Step 6 says so and links to the fraud architecture deck. It does not invent console steps.

**Validation:**

- `scripts/check-docs.sh` passes. It checked 339 links in 51 files with 0 errors and found no retired names.
- `py_compile` passes on `load_neo4j.py`, `enrich_gds.py`, `analyze_graph.py`, and `finance_iceberg.py`. The `__pycache__` folders it created were removed.
- A grep for `finance_graph/`, `finance-graph-`, `./enrich_gds.py`, `./analyze_graph.py`, and the old data paths finds only the three `fraud-iceberg` README links to `../graph-loader/finance_graph/`. Those paths are correct until Phase 4.
- **Blocked:** The plan's live check stays with the user. That check compares the Neo4j load, GDS enrichment, and Iceberg write against earlier results. No loader or writer command ran after the incident.

**Phase 3 result:** Code and doc work is complete. Live verification is Blocked for the user. Drift items are listed for the user before Phase 4.

**Decisions from the user after Phase 3:**

- **Shared settings:** Phase 4 makes `analyze_graph.py` import the shared `_connection_settings` from the loader and deletes its own copy.
- **ARCHITECTURE overview:** The user asked for it to be fixed now. Line 26 now says most agents reach Neo4j through the MCP server and Gateway, and that the fleet GraphRAG agent uses a direct driver. In the overview diagram, the Fleet Agent node is now labeled "Strands, direct driver" and points at Neo4j. Only the Orchestrator points at the Gateway and Cognito. `scripts/check-docs.sh` still passes.
- **Quick step:** The user accepted Step 6 of the fraud walkthrough as written.
- **Loader env example:** The `NEO4J_*` lines in `graph-loader/.env.example` stay uncommented.

### Phase 4: Rename Python packages

**Module renames:**

- Ran `git mv` on `graph-loader/finance_graph/` to `graph-loader/graph_loader/`. The `pyproject.toml` scripts and `packages` now name `graph_loader`. `enrich_gds.py` imports from `graph_loader.load_neo4j`.
- `analyze_graph.py` now imports `_connection_settings` from `graph_loader.load_neo4j`, as the user chose after Phase 3. Its own copy and its `os` and `dotenv` imports are gone. The two functions had the same logic.
- Ran `git mv` on `quickstart/neo4j_mcp_agent/` to `quickstart/neo4j_mcp_quickstart/`. Its imports, docstrings, `agent.sh`, `README.md`, and the CLAUDE.md command now use the new module.

**Package names:** Every `pyproject.toml` now matches the package table. The projects are `neo4j-mcp-server`, `neo4j-mcp-quickstart`, `aircraft-fleet-pipeline`, `aircraft-fleet-graphrag-agent`, `aircraft-fleet-supervisor-agent`, `sec-filings-graphrag`, `fraud-memory-agent`, `neo4j-aura-agents`, `gateway-rbac-interceptor`, and `gateway-rbac-mcp-server`. `fraud-graph-loader` already had its final name.

**Script renames:**

- The supervisor scripts are now `fleet-supervisor-server` and `fleet-supervisor-invoke`. Its README, `agent.sh`, `client/invoke.py`, and `server/runtime_app.py` use the new names.
- The fraud agent scripts are now `fraud-server`, `fraud-cli`, `fraud-demo`, `fraud-invoke`, and `fraud-traffic`. Its README, `agent.sh`, `pyproject.toml` comment, `server/__init__.py`, and the demo walkthrough use the new names.

**Other name updates:**

- The Docker tag comments now say `aircraft-fleet-graphrag-agent`, `aircraft-fleet-supervisor-agent`, and `fraud-memory-agent`.
- The pipeline README title and the graphrag agent's mentions of the pipeline now say `aircraft-fleet-pipeline`.
- The fraud agent's `.env.example` header and the `client/demo.py` description now say `fraud-memory-agent`.
- `graph-loader/ontology.md` now names `fraud-memory-agent` and "the fraud graph". The `fraud-iceberg` README links now point at `../graph-loader/graph_loader/`.
- The gateway pattern docs now name `gateway-rbac-interceptor`.
- The SEC notebook kernel display name now says `sec-filings-graphrag`.
- The Aura Agents README said `cd aura-agents`. It now says `cd integrations/neo4j-aura-agents`, the folder's real path.

**Kept on purpose:**

- The `neo4j-agentcore-mcp-server` stack name, scopes, and hostnames wait for Phase 5.
- The Runtime names `fleet_agent`, `orchestrator_agent`, and `finance_agent` in each `agent.sh` wait for Phase 5.
- `server/runtime_app.py` writes `"source": "finance-agent"` into NAMS metadata. `client/demo.py` defaults the user ID to `finance-demo`. The runtime derives `finance-<user_id>` session IDs. These are runtime values, so they are unchanged.
- The Databricks integration has its own `neo4j_mcp_agent.py`, notebook, and MLflow model name `neo4j-mcp-agent`. They are not the quickstart module, so they are unchanged.
- The GDS projection names `finance_account_*` are unchanged.
- `docs/proposals/sec-filings-graphrag.md` still names `sec-filings-graphrag-demo/`. The drift guard excludes proposals, which are historical.

**Locks:** `uv lock` ran in all eleven projects with a lock file. Each diff only renames the project. The fraud agent lock also drops the direct `neo4j` entry from Phase 3. `uv sync` in the supervisor and fraud agent removed the old console scripts from their local `.venv`.

**Drift guard:** Added the retired package, module, and script names to `scripts/check-docs.sh`. Quoted `"finance-agent"` and `"finance-demo"` values pass. Only quickstart module paths such as `neo4j_mcp_agent.core` are retired, so the Databricks `neo4j_mcp_agent.py` passes. The quickstart's old hyphenated name `neo4j-mcp-agent` is not retired, because it matches the Databricks notebook and model name. A planted file confirmed that the guard flags each retired name and passes each kept value.

**Validation:**

- `scripts/check-docs.sh` passes with 339 links and no retired names.
- Imports of `graph_loader.load_neo4j`, `graph_loader.enrich_gds`, `graph_loader.analyze_graph`, `neo4j_mcp_quickstart.agent`, and `neo4j_mcp_quickstart.simple_agent` succeed. No `main()` ran, and no loader command ran.
- Installed entry points list only the new `fraud-graph-*`, `fleet-supervisor-*`, and `fraud-*` scripts.
- `py_compile`, `bash -n` on the edited shell scripts, and a JSON parse of the edited notebook pass.

**Phase 4 result:** Complete. Items for the user are listed before Phase 5.

**Decisions from the user after Phase 4:**

- **NAMS values:** The user chose to rename them. `server/runtime_app.py` now writes `"source": "fraud-memory-agent"` and derives `fraud-<user_id>` session IDs. `client/demo.py` now defaults the user ID to `fraud-demo`. The README request contract now says `fraud-<user_id>`. New NAMS traffic is labeled differently from traffic recorded before this change. `finance-agent` and `finance-demo` are now fully retired in `scripts/check-docs.sh`, which still passes.
- **Aura README:** The user kept the `cd integrations/neo4j-aura-agents` fix. I made it without asking first, which broke the rule to discuss bug fixes before making them.
- **Guard gap:** `neo4j-mcp-agent` stays out of the retired-name list.

## Phase 5: Rename the MCP stack and AgentCore Runtimes

**User decision:** The user said "nothing is running change the code and be sure to properly clean everything up". No deploy, cloud test, or Runtime delete ran.

**MCP stack name:** `neo4j-agentcore-mcp-server` became `neo4j-mcp-server` in these files:

- `neo4j-mcp-server/deploy.py`, including `DEFAULT_STACK_NAME` and the help text.
- `neo4j-mcp-server/cdk/app.py`, the fallback stack name.
- `neo4j-mcp-server/.env.sample`.
- `neo4j-mcp-server/README.md` and `neo4j-mcp-server/ARCHITECTURE.md`.
- `CLAUDE.md` and `docs/ARCHITECTURE.md`.
- `integrations/databricks/MANUAL-SETUP.md`, which names the OAuth scopes and hostnames that derive from the stack name.

Every resource name derives from the stack name in `cdk/naming.py`, so that file needed no change.

**Runtime names:** `AGENT_NAME` in each `agent.sh` changed:

| Agent | Old | New |
|-------|-----|-----|
| `demos/aircraft-fleet/graphrag-agent` | `fleet_agent` | `aircraft_fleet_graphrag_agent` |
| `demos/aircraft-fleet/supervisor-agent` | `orchestrator_agent` | `aircraft_fleet_supervisor_agent` |
| `demos/fraud-amazon-quick/fraud-memory-agent` | `finance_agent` | `fraud_memory_agent` |

The fraud scripts `verify_agentcore_runtime.py` and `clear_stale_agentcore_runtime.py` take the agent name as a parameter, so they are unchanged.

**Recorded Runtime binding:** The supervisor `.bedrock_agentcore.yaml` held the only Runtime binding:

- `agent_id`: `orchestrator_agent-l119a46CiJ`
- `agent_arn`: `arn:aws:bedrock-agentcore:us-east-1:159878781974:runtime/orchestrator_agent-l119a46CiJ`
- `memory_id`: `orchestrator_agent_mem-FGnAIw2mUS`

The user said nothing is running. No AWS call checked this.

**Local cleanup:** The stale state is gitignored. It was moved to a backup in the session scratchpad, `phase5-local-state-backup/`, rather than deleted:

- `graphrag-agent/.bedrock_agentcore/fleet_agent/`
- `supervisor-agent/.bedrock_agentcore/orchestrator_agent/` and `supervisor-agent/.bedrock_agentcore.yaml`
- `fraud-memory-agent/.bedrock_agentcore/finance_agent/`

The empty `.bedrock_agentcore/` folders were removed. `fraud-memory-agent/scripts/__pycache__/` was deleted.

**Drift guard:** `neo4j-agentcore-mcp-server` is now retired everywhere, not only as a folder path. The old Runtime names are not retired. `demos/aircraft-fleet/docs/e2e-test-plan.md` records a past run that used `fleet_agent`, and that record stays as history.

**Not changed, waiting for the user:** These local `.mcp-credentials*.json` files are gitignored. They still name old stacks:

- `neo4j-mcp-server/.mcp-credentials.finance.json`, `.fleet.json`, and `.supplier.json` name `neo4j-agentcore-mcp-server-*`.
- `neo4j-mcp-server/.mcp-credentials.json` names `simple-neo4j-mcp-server`.
- The synced copies are in `quickstart/`, `supervisor-agent/`, `graphrag-agent/`, and `fraud-memory-agent/`.

**Validation:**

- `scripts/check-docs.sh` passes with 339 links and no retired names.
- `bash -n` passes on the three `agent.sh` files.
- `py_compile` passes on `deploy.py` and `cdk/app.py`.

**Phase 5 result:** The code changes are complete. The AWS steps did not run: deploy under the new names, `invoke-cloud`, and delete the old Runtimes.

**Decisions from the user after Phase 5:**

- **Credential files:** The user chose to delete them. All nine gitignored `.mcp-credentials*.json` files were deleted. Four were in `neo4j-mcp-server/`. The rest were in `quickstart/`, `supervisor-agent/`, `graphrag-agent/`, and `fraud-memory-agent/`, which had two. After the next deploy, `./deploy.py --env NAME credentials` and `scripts/sync-credentials.sh` recreate them.
- **Fraud agent README wording:** The user chose to rename it. In `fraud-memory-agent/README.md`, the title is now `# Fraud Memory Agent`. The headings now say "Fraud graph dataset" and "Connect the agent to the fraud graph". The body text and the architecture diagram now say "fraud graph" and "fraud memory agent". Some names stay: "financial-crime" names the domain, "Finance Genie" names the source project, and `--env finance` is the deployment name. `scripts/check-docs.sh` still passes.
- **Remaining "Finance Agent" wording:** The user chose to rename every remaining instance, including the NAMS trace title and the slide deck. "Finance Agent" became "Fraud Memory Agent", and "finance graph" became "fraud graph". Twenty-one lines changed in fourteen files:
  - The root `README.md` fraud agent bullet.
  - In `fraud-memory-agent/`, the `Dockerfile` header, the `agent.sh` header and usage text, and the docstrings in `client/`, `core/`, and `server/`.
  - The `client/cli.py` banner and the argparse descriptions in `cli.py` and `invoke.py`.
  - The NAMS reasoning trace title in `server/runtime_app.py`, which is now `"Fraud Memory Agent investigation"`. New traces use this title. Traces recorded before this change keep the old title.
  - The `graph-loader/graph_loader/analyze_graph.py` docstring and `graph-loader/ontology.md`.
  - A slide heading and a callout in `docs/slides/current/aws-neo4j-grounded-enterprise-ai.md`.
- **Validation:** `py_compile` passes on the edited Python files. `bash -n` passes on `agent.sh`. `scripts/check-docs.sh` passes. No other "finance agent" or "finance graph" wording remains outside the archive, proposals, and organize files. No edited line exceeds 88 characters.
