# Proposal: Reorganize the Repository

## Goal

A reader should be able to look at the top-level folder names and the root README and know three things:

1. Which sample to start with.
2. How each sample reaches Neo4j.
3. Which business domain each sample uses.

The current layout answers none of these reliably. This proposal groups end-to-end demos by domain, keeps shared building blocks at the top level, and records how each sample reaches Neo4j in a sample matrix in the root README. It also fixes documentation that has drifted from the code and adds a check so the drift does not return.

The decisions it records are listed at the end.

## Implementation Status

Implementation started on 2026-09-28. Every change is recorded in [organize-audit-log.md](./organize-audit-log.md).

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Fix documentation drift and add the drift guard | Complete | All drift rows fixed. Five more broken links fixed. `scripts/check-docs.sh` passes. Two stale memory docs deleted. `deploy.sh` is retired everywhere except the gateway pattern |
| 2. Move folders | Complete | All moves and reference updates are done. `scripts/check-docs.sh` passes with the retired-name check on. The user accepted the logged interpretations. The leftover `neo4j-agentcore-agents/` folder was deleted. Three older problems were fixed: the Databricks script is no longer ignored, fleet README Step 3 no longer runs a bad `cd`, and the ARCHITECTURE.md Fleet Agent section now matches `graphrag-agent` |
| 3. Assemble the fraud demo | Complete, live check Blocked | All eight steps are done. `scripts/check-docs.sh` and `py_compile` pass. The live load, enrichment, and Iceberg comparison is Blocked until the user runs it. `analyze_graph.py` sits in `graph-loader/finance_graph/`, per the layout choice |
| 4. Rename Python packages | Complete | Every package matches the table. `finance_graph` is now `graph_loader`, and `neo4j_mcp_agent` is now `neo4j_mcp_quickstart`. The supervisor and fraud agent scripts are renamed. All eleven locks are regenerated. Retired names are in `scripts/check-docs.sh`, which passes. The user chose to rename the NAMS values too, so the agent now writes `"source": "fraud-memory-agent"` and `fraud-<user_id>` session IDs |
| 5. Rename the MCP stack and AgentCore Runtimes | Complete, AWS steps not run | The default stack name is now `neo4j-mcp-server` in code and docs. `AGENT_NAME` is now `aircraft_fleet_graphrag_agent`, `aircraft_fleet_supervisor_agent`, and `fraud_memory_agent`. The user said nothing is running, so no deploy, cloud test, or Runtime delete ran. Stale local AgentCore state for the old names was moved to a backup. `neo4j-agentcore-mcp-server` is retired in `scripts/check-docs.sh`, which passes. The user chose to delete the old `.mcp-credentials*.json` files and to rename the "Finance Agent" wording in the fraud agent README |

Implementation choices confirmed with the user:

- **Git:** Changes stay uncommitted on `main`. The user commits.
- **Link checker:** `lychee` 0.24.2 is installed with Homebrew for local runs.
- **Phase 3 validation:** Validation is static. It covers imports, data paths, CLI startup, and the `enrich_gds.py` merge.
- **Phase 5 scope:** Only code changes are in scope. Deploys, cloud tests, and Runtime deletes need separate approval.
- **Phase 5 live stacks:** The user said nothing is running. The code changes proceed, and stale local state is cleaned up.
- **Graph loader layout:** The Python files live in a package folder, `graph-loader/finance_graph/`. Phase 4 renames it to `graph_loader/`. `README.md`, `ontology.md`, and `pyproject.toml` sit at `graph-loader/`.
- **Graph loader config:** The loader reads `graph-loader/.env`. The `NEO4J_*` and `GDS_SESSION_MEMORY` block moves from the agent's `.env.example` to `graph-loader/.env.example`.
- **Agent dependencies:** `neo4j` leaves the agent's `pyproject.toml`, and the agent is re-locked. `python-dotenv` stays, because `server/runtime_app.py` uses it.
- **Graph loader names:** The new project uses its final names in Phase 3. The package is `fraud-graph-loader`, and the scripts are `fraud-graph-load`, `fraud-graph-enrich`, and `fraud-graph-analyze`. Phase 4 only renames the module.
- **Shared loader settings:** Phase 4 makes `analyze_graph.py` import `_connection_settings` from `load_neo4j` and deletes its own copy.

## What Is Wrong Today

### Folder names repeat the repo name and hide the domain

Almost every folder starts with `neo4j-agentcore-`. The whole repo is about Neo4j on AgentCore, so the prefix adds length without adding meaning. It also crowds out the words that would help: the domain and the technique.

- `neo4j-agentcore-agents/finance-agent/` is a fraud-ring investigation agent with Neo4j Agent Memory. It is being built to show how Neo4j integrates with Amazon Quick. "Finance" does not say "fraud," "memory," or "Quick."
- `neo4j-agentcore-agents/orchestrator-agent/` is a supervisor over the aviation fleet graph. The folder name does not mention aviation, so a reader cannot tell it shares a domain with `fleet-agent-demo/`.
- `data-agent/` contains no agent. It loads the fraud dataset into Iceberg tables, queries them with Athena, and runs graph analysis.

### Groupings do not match what the samples do

- `infra-samples/` holds three unrelated things. `aura-agents/` is a REST client for Neo4j-hosted agents. `databrick-samples/` is a Databricks integration. `simple-oauth-gateway/` is a Gateway security pattern. Only the last one is infrastructure.
- `neo4j-agentcore-agents/` holds two agents that deploy to AgentCore Runtime and one that does not. `langgraph-mcp-agent/` runs locally or in SageMaker Studio, yet it sits beside the Runtime agents. The root README already lists it as a separate section.
- Databricks content lives in two places. `infra-samples/databrick-samples/` has the notebooks. `neo4j-agentcore-mcp-server/databricks-mcp-setup.md` has the Unity Catalog MCP Service setup.

### Each domain is split across folders

- **Aviation fleet:** The aviation fleet domain spans two top-level folders. `fleet-agent-demo/pipeline/` loads the aviation graph. `neo4j-agentcore-agents/orchestrator-agent/` queries that same graph through the MCP Gateway. Its prompts expect `Aircraft`, `System`, `Component`, and `MaintenanceEvent` nodes. A reader who tries the supervisor first finds an empty database, because nothing in its folder says the pipeline must run first.
- **Fraud:** The fraud story spans three folders. `data-agent/` holds the Iceberg side, `finance-agent/finance_graph/` holds the Neo4j loader, and `finance-agent/` holds the agent. The fraud deck in `docs/slides/current/fraud-data-architecture.md` presents them as one architecture: Athena over S3 Tables, Neo4j for connected context, and Amazon Quick for presentation.

### One credentials file cannot serve two datasets

The fleet and fraud demos need different Neo4j databases. The MCP server already supports this with `--env`. `./deploy.py --env fleet credentials` writes `.mcp-credentials.fleet.json`, and `--env finance` writes `.mcp-credentials.finance.json`. `neo4j-agentcore-agents/sync-credentials.sh` ignores this. It copies the default `.mcp-credentials.json` to both the orchestrator and the finance agent, so at least one of them points at the wrong graph.

### Loose files at the root

- `fintech-demo.md` is the design proposal for `sec-filings-graphrag-demo/`. Its name suggests a different demo.
- `test-s3-access.sh` is a one-off utility with no connection to any sample.
- `images/` holds three screenshots. Only one is used, by `infra-samples/aura-agents/README.md`. The other two, `Sagemaker Domains.png` and `sagemakeruibuild.png`, are referenced nowhere.

### The fraud dataset is committed twice

`data-agent/data/` and `neo4j-agentcore-agents/finance-agent/finance_graph/data/` hold the same seven files, about 29 MB. All seven have identical git blob hashes. Git stores each blob once, so the copy does not grow the clone. It does create two sources of truth that can drift apart. The `enrich_gds.py` scripts show the risk: each folder has its own copy, and the two have already diverged.

### Documentation has drifted from the code

| Where | What it says | What is true |
|-------|--------------|--------------|
| Root `README.md` | `finance-agent` is an SEC-filings agent with a `common/` core wired to LangGraph and Strands | It is a Strands fraud agent with `core/`, `finance_graph/`, `client/`, and `server/` |
| `neo4j-agentcore-agents/README.md` | Quick start runs `langgraph/agent.sh deploy` | There is no `langgraph/` folder. `agent.sh` is at the agent root |
| `neo4j-agentcore-agents/README.md` | A `cfn/` folder deploys agents with CloudFormation | There is no `cfn/` folder |
| `neo4j-agentcore-agents/sync-credentials.sh` | Deploy the MCP server with `./deploy.sh` | The script is `./deploy.py` |
| `infra-samples/databrick-samples/neo4j-mcp-http-connection.ipynb` | Deploy and check the MCP server with `./deploy.sh` | The script is `./deploy.py` |
| `infra-samples/databrick-samples/setup_databricks_secrets.sh` lines 8 and 21 | Deploy with `cd ../neo4j-agentcore-mcp-server && ./deploy.sh` | The script is `./deploy.py`. The server is two levels up, not one |
| `orchestrator-agent/core/credentials.py` line 37 | Copy credentials with `cp ../fleet-agent/.mcp-credentials.json .` | There is no `fleet-agent/` sibling. Credentials come from the MCP server |
| `infra-samples/aura-agents/README.md` line 46 | The screenshot is at `../images/auraagentsapikey.png` | That resolves to `infra-samples/images/`, which does not exist. The link is broken |
| `CLAUDE.md` | `infra_samples/simple-agentcore-agent` and `infra_samples/sample-agentcore-mcp-server` exist | Neither exists. The folder is `infra-samples/` with a hyphen |
| `CLAUDE.md` | Databricks samples live in `databrick_samples/` | They live in `infra-samples/databrick-samples/` |
| `neo4j-agentcore-agents/docs/memory-fixes.md` and `future-improvements.md` | Memory lives in `common/memory.py` and `strands/runtime_app.py` | Those paths no longer exist. The user chose to delete both files in Phase 1 |
| `docs/slides/current/aws-neo4j-grounded-enterprise-ai.md` line 630 | The slide source is `finance-agent/core/memory.py` | There is no `core/memory.py`. Memory lives in `server/runtime_app.py`. Only the source comment is fixed. The slide's claims are left for the user |

## Organizing Principle

The top level separates what a reader deploys once from what a reader picks to present.

| Group | What it holds | How a reader chooses |
|-------|---------------|----------------------|
| `neo4j-mcp-server/` | The shared MCP server and Gateway | Deploy it once. Most samples need it |
| `quickstart/` | The smallest Gateway client | Run it first to prove the Gateway works |
| `demos/` | End-to-end demos, one folder per domain | Pick by customer story |
| `integrations/` | Neo4j surfaced through another platform, such as Databricks or Neo4j Aura | Pick by the platform the customer uses |
| `patterns/` | Standalone AgentCore patterns that each teach one concept | Pick by the concept |

Each demo keeps all of its parts in one folder: the data, the loaders, and every agent that uses that data. A demo can hold agents that reach Neo4j in different ways. `demos/aircraft-fleet/` holds a direct-driver agent and an MCP Gateway agent over the same graph.

Folder names do not try to encode how a sample reaches Neo4j. That is the job of the sample matrix below, which goes in the root README.

Inside a demo, name each part after its role, such as `pipeline/`, `graph-loader/`, or `supervisor-agent/`. The demo folder already names the domain.

## Proposed Layout

```
aws-starter/
├── README.md                            # adds the sample matrix and learning path
├── CLAUDE.md
├── neo4j-mcp-server/                    # was neo4j-agentcore-mcp-server/
├── quickstart/                          # was neo4j-agentcore-agents/langgraph-mcp-agent/
│
├── demos/
│   ├── aircraft-fleet/
│   │   ├── README.md                    # one walkthrough: load, query direct, query via Gateway
│   │   ├── .env.sample                  # was fleet-agent-demo/.env.sample
│   │   ├── pipeline/                    # was fleet-agent-demo/pipeline/
│   │   ├── graphrag-agent/              # was fleet-agent-demo/agent/
│   │   ├── supervisor-agent/            # was neo4j-agentcore-agents/orchestrator-agent/
│   │   └── docs/
│   ├── fraud-amazon-quick/
│   │   ├── README.md                    # one walkthrough: load, enrich, query, Quick
│   │   ├── data/                        # single copy of the fraud CSVs
│   │   ├── graph-loader/                # was finance-agent/finance_graph/
│   │   ├── fraud-iceberg/               # was data-agent/
│   │   └── fraud-memory-agent/          # was finance-agent/, without finance_graph/
│   └── sec-filings-graphrag/            # was sec-filings-graphrag-demo/
│
├── integrations/
│   ├── databricks/                      # was infra-samples/databrick-samples/
│   └── neo4j-aura-agents/               # was infra-samples/aura-agents/
│       └── images/                      # was images/auraagentsapikey.png
│
├── patterns/
│   └── gateway-rbac-interceptor/        # was infra-samples/simple-oauth-gateway/
│
├── scripts/
│   ├── sync-credentials.sh              # was neo4j-agentcore-agents/sync-credentials.sh
│   ├── check-docs.sh                    # new: link and retired-name check
│   └── test-s3-access.sh                # was ./test-s3-access.sh
│
├── .github/workflows/
│   ├── deploy-aws-in-depth-slides.yml   # unchanged
│   └── check-docs.yml                   # new: runs scripts/check-docs.sh on pull requests
│
└── docs/
    ├── ARCHITECTURE.md
    ├── proposals/
    │   └── sec-filings-graphrag.md      # was ./fintech-demo.md
    └── slides/                          # unchanged, see Decision 9
```

The root `images/` folder goes away. The Aura screenshot moves, and the two unused SageMaker screenshots are deleted.

## Sample Matrix

This table goes in the root README, directly under the project overview. It answers the three goals no matter what the folders are called.

| Sample | Domain and dataset | How the data is loaded | How it reaches Neo4j | Needs the MCP server | MCP `--env` | Deploys to Runtime | Main AWS services |
|--------|--------------------|------------------------|----------------------|----------------------|-------------|--------------------|-------------------|
| `neo4j-mcp-server/` | Any graph | Not applicable | It is the MCP server | Not applicable | Any | Yes, the MCP server | AgentCore Runtime, Gateway, Cognito, Secrets Manager |
| `quickstart/` | Any graph the MCP server points at | Not applicable | MCP Gateway | Yes | Default | No | AgentCore Gateway, Bedrock, SageMaker Unified Studio |
| `demos/aircraft-fleet/pipeline/` | Aviation fleet digital twin | `pipeline/setup.sh` | Neo4j Python driver | No | Not applicable | No | Bedrock Titan embeddings, Bedrock Claude |
| `demos/aircraft-fleet/graphrag-agent/` | Aviation fleet digital twin | `pipeline/` | Neo4j Python driver | No | Not applicable | Yes | AgentCore Runtime, Bedrock |
| `demos/aircraft-fleet/supervisor-agent/` | Aviation fleet digital twin | `pipeline/` | MCP Gateway | Yes | `fleet` | Yes | AgentCore Runtime, Gateway, Bedrock, CloudWatch |
| `demos/fraud-amazon-quick/graph-loader/` | Synthetic fraud rings | `graph-loader/` from `data/` | Neo4j Python driver | No | Not applicable | No | None |
| `demos/fraud-amazon-quick/fraud-iceberg/` | Synthetic fraud rings | `fraud-iceberg/` from `data/` | Does not reach Neo4j | No | Not applicable | No | S3 Tables, Glue, Athena |
| `demos/fraud-amazon-quick/fraud-memory-agent/` | Synthetic fraud rings | `graph-loader/` | MCP Gateway for the graph, Neo4j Agent Memory Service for memory | Yes | `finance` | Yes | AgentCore Runtime, Gateway, Bedrock, Amazon Quick |
| `demos/sec-filings-graphrag/` | SEC 10-K filings | The notebook | Neo4j Python driver | No | Not applicable | No | Bedrock |
| `integrations/databricks/` | Any graph the MCP server points at | Not applicable | MCP Gateway through a Unity Catalog HTTP connection | Yes | Default | No | AgentCore Gateway, Cognito |
| `integrations/neo4j-aura-agents/` | Any AuraDB graph | The Neo4j Aura console | Neo4j Aura Agents REST API | No | Not applicable | No | None |
| `patterns/gateway-rbac-interceptor/` | None | Not applicable | Does not reach Neo4j | No, it has its own MCP server | Not applicable | Yes, its own MCP server | AgentCore Gateway, Cognito, Lambda |

The MCP `--env` column assumes the current suffixes. `--env fleet` and `--env finance` already exist in `neo4j-agentcore-mcp-server/.env.sample` and in the local credentials files.

## Rename Rationale

### Folders

| Current | Proposed | Reason |
|---------|----------|--------|
| `neo4j-agentcore-mcp-server/` | `neo4j-mcp-server/` | Drops the repeated prefix. Keeps `neo4j` because `patterns/gateway-rbac-interceptor/` has its own small MCP server. |
| `neo4j-agentcore-agents/langgraph-mcp-agent/` | `quickstart/` | It is the smallest Gateway client and the natural first step. A top-level `quickstart/` tells a reader to start here. |
| `neo4j-agentcore-agents/` | Removed | Its three agents move to `quickstart/`, `demos/aircraft-fleet/`, and `demos/fraud-amazon-quick/`. |
| `fleet-agent-demo/` | `demos/aircraft-fleet/` | Names the domain. Drops "demo," since the `demos/` group already says it. |
| `fleet-agent-demo/agent/` | `demos/aircraft-fleet/graphrag-agent/` | A second agent now shares the folder, so `agent/` no longer identifies it. "GraphRAG" names what sets it apart: Text2Cypher plus vector search over a direct driver. |
| `neo4j-agentcore-agents/orchestrator-agent/` | `demos/aircraft-fleet/supervisor-agent/` | It queries the aviation graph that `pipeline/` loads, so it lives with that pipeline. "Supervisor" names the pattern. |
| `sec-filings-graphrag-demo/` | `demos/sec-filings-graphrag/` | Drops "demo," since the group already says it. Keeps "GraphRAG" because the notebook teaches four levels of GraphRAG retrieval. |
| Parts of `finance-agent/` and `data-agent/` | `demos/fraud-amazon-quick/` | Names the domain first and the presentation layer second. The fraud deck presents these parts as one architecture. |
| `finance-agent/` | `demos/fraud-amazon-quick/fraud-memory-agent/` | Names the domain and the feature that sets it apart, which is Neo4j Agent Memory. |
| `finance-agent/finance_graph/` | `demos/fraud-amazon-quick/graph-loader/` | It is setup tooling, not part of the agent. The `Dockerfile` never copies it, and the runtime never imports it. |
| `finance-agent/finance_graph/data/` and `data-agent/data/` | `demos/fraud-amazon-quick/data/` | The two folders hold the same files. One copy serves both the graph loader and the Iceberg writers. |
| `data-agent/` | `demos/fraud-amazon-quick/fraud-iceberg/` | It contains no agent. It loads the fraud data into Iceberg and S3 Tables for Athena. |
| `infra-samples/databrick-samples/` | `integrations/databricks/` | Fixes the "databrick" spelling. Groups it as an integration. |
| `infra-samples/aura-agents/` | `integrations/neo4j-aura-agents/` | It calls agents that Neo4j hosts. It deploys no AWS infrastructure. |
| `infra-samples/simple-oauth-gateway/` | `patterns/gateway-rbac-interceptor/` | Names what it teaches: role-based access with a Lambda interceptor. `patterns/` is also the home for future small AgentCore samples. |
| `neo4j-agentcore-agents/sync-credentials.sh` | `scripts/sync-credentials.sh` | Its targets now span `quickstart/` and two demos, so it no longer belongs to one group. |
| `images/auraagentsapikey.png` | `integrations/neo4j-aura-agents/images/auraagentsapikey.png` | Keeps the screenshot next to the only README that uses it. Fixes the broken link. |
| `fintech-demo.md` | `docs/proposals/sec-filings-graphrag.md` | The file is the SEC filings proposal. |
| `test-s3-access.sh` | `scripts/test-s3-access.sh` | Keeps the root limited to entry points. |

### Python packages

Each `pyproject.toml` name is unique across the repo. Inside a demo, the package name is the demo name plus the folder role, unless the folder name already carries the domain.

| Folder | Current name | Proposed name | Script and module changes |
|--------|--------------|---------------|---------------------------|
| `neo4j-mcp-server/` | `neo4j-agentcore-mcp-server` | `neo4j-mcp-server` | None. `neo4j-mcp-cdk` and `neo4j-mcp-client` already fit. |
| `quickstart/` | `neo4j-mcp-agent` | `neo4j-mcp-quickstart` | The `neo4j_mcp_agent` module becomes `neo4j_mcp_quickstart`. |
| `demos/aircraft-fleet/pipeline/` | `bedrock-graphrag-pipeline` | `aircraft-fleet-pipeline` | None. |
| `demos/aircraft-fleet/graphrag-agent/` | `neo4j-fleet-agent` | `aircraft-fleet-graphrag-agent` | None. The `fleet-*` scripts already fit. |
| `demos/aircraft-fleet/supervisor-agent/` | `neo4j-orchestrator-agent` | `aircraft-fleet-supervisor-agent` | `orchestrator-server` and `orchestrator-invoke` become `fleet-supervisor-server` and `fleet-supervisor-invoke`. The Docker image tag in the `Dockerfile` comments changes to match. |
| `demos/sec-filings-graphrag/` | `sec-filings-graphrag-demo` | `sec-filings-graphrag` | None. |
| `demos/fraud-amazon-quick/fraud-memory-agent/` | `finance-agent` | `fraud-memory-agent` | The `finance-*` scripts become `fraud-server`, `fraud-cli`, `fraud-demo`, `fraud-invoke`, and `fraud-traffic`. `finance_graph` leaves `packages`. |
| `demos/fraud-amazon-quick/graph-loader/` | Part of `finance-agent` | `fraud-graph-loader` | New project. The `finance_graph` module becomes `graph_loader`. Scripts are `fraud-graph-load`, `fraud-graph-enrich`, and `fraud-graph-analyze`. |
| `demos/fraud-amazon-quick/fraud-iceberg/` | None | None | Stays a set of `uv run --script` files. |
| `integrations/neo4j-aura-agents/` | `aura-agents` | `neo4j-aura-agents` | None. |
| `patterns/gateway-rbac-interceptor/` | `simple-oauth-gateway` | `gateway-rbac-interceptor` | None. |
| `patterns/gateway-rbac-interceptor/mcp-server/` | `simple-oauth-mcp-server` | `gateway-rbac-mcp-server` | None. |

### AgentCore Runtime names

Each Runtime name is its package name with underscores. Runtime names allow only letters, digits, and underscores.

| Agent | Current Runtime | Proposed Runtime |
|-------|-----------------|------------------|
| `demos/fraud-amazon-quick/fraud-memory-agent/` | `finance_agent` | `fraud_memory_agent` |
| `demos/aircraft-fleet/supervisor-agent/` | `orchestrator_agent` | `aircraft_fleet_supervisor_agent` |
| `demos/aircraft-fleet/graphrag-agent/` | `fleet_agent` | `aircraft_fleet_graphrag_agent` |

### MCP server stack name

The default CDK stack name matches the new folder. `--env NAME` still appends `-NAME`.

| Command | Current stack | Proposed stack |
|---------|---------------|----------------|
| `./deploy.py` | `neo4j-agentcore-mcp-server` | `neo4j-mcp-server` |
| `./deploy.py --env fleet` | `neo4j-agentcore-mcp-server-fleet` | `neo4j-mcp-server-fleet` |
| `./deploy.py --env finance` | `neo4j-agentcore-mcp-server-finance` | `neo4j-mcp-server-finance` |

Every resource name in the stack derives from the stack name, including the Cognito domain, IAM roles, Gateway, and Secrets Manager path. `cdk/naming.py` caps the stack name at 41 characters. The shorter default leaves 25 characters for an `--env` suffix instead of 15.

No MCP server is deployed today, so the rename replaces nothing in AWS.

## Smaller Moves Inside Samples

These moves happen in Phase 2 alongside the folder moves, except the graph loader, which moves in Phase 3.

- **Databricks setup:** Move `neo4j-mcp-server/databricks-mcp-setup.md` into `integrations/databricks/`. All Databricks setup then lives in one folder.
- **Agent memory docs:** Move `neo4j-agentcore-agents/docs/agent-memory-strands.md` into `demos/fraud-amazon-quick/fraud-memory-agent/docs/`. It describes that agent's memory. The other two files, `memory-fixes.md` and `future-improvements.md`, were deleted in Phase 1.
- **Aircraft fleet shared config:** Keep the shared `.env` at the demo root, now `demos/aircraft-fleet/.env`. `pipeline/` and `graphrag-agent/` both read it today. `supervisor-agent/` does not read it, because it reaches Neo4j through the Gateway.
- **Aircraft fleet README:** Extend `demos/aircraft-fleet/README.md` with a third step after the pipeline and the GraphRAG agent. That step deploys the MCP server with `--env fleet` against the same `NEO4J_URI`, syncs credentials, and runs the supervisor. `pipeline/setup.sh` already ends by telling the reader to point the MCP server at this `NEO4J_URI`.
- **Graph loader contents:** Split `finance_graph/` by what each file is.

  | Current | Destination |
  |---------|-------------|
  | `finance_graph/data/` | `fraud-amazon-quick/data/`, shared with `fraud-iceberg/` |
  | `finance_graph/load_neo4j.py` | `graph-loader/load_neo4j.py` |
  | `finance_graph/enrich_gds.py` | `graph-loader/enrich_gds.py`, merged with `data-agent/enrich_gds.py` |
  | `finance_graph/ontology.md` | `graph-loader/ontology.md` |
  | `finance_graph/README.md` | `graph-loader/README.md` |
  | `data-agent/analyze_graph.py` | `graph-loader/analyze_graph.py` |

  `analyze_graph.py` runs Cypher against Neo4j, so it belongs with the graph tooling rather than the Iceberg writers.
- **Interceptor fix log:** Move `simple-oauth-gateway/FIX_32.md` to `patterns/gateway-rbac-interceptor/docs/troubleshooting.md`. The issue is resolved, so the content reads better as a troubleshooting note than as a fix ticket.
- **Fleet test plan:** Move `fleet-agent-demo/E2E-TEST-PLAN.md` to `demos/aircraft-fleet/docs/e2e-test-plan.md`. Add the supervisor agent to it.

## Suggested Learning Path

The root README presents the samples in the order a new reader should try them. A numbered list in the README gives this guidance without numbering the folders, which would make future insertions awkward. Each step needs only what earlier steps set up.

1. `neo4j-mcp-server/` deploys the foundation.
2. `quickstart/` makes the first Gateway call against whatever graph the server points at.
3. `demos/sec-filings-graphrag/` introduces GraphRAG retrieval in one notebook.
4. `demos/aircraft-fleet/` loads the aviation graph, queries it with a direct-driver agent, then deploys the MCP server with `--env fleet` and adds multi-agent routing with the supervisor.
5. `demos/fraud-amazon-quick/` combines Athena, Neo4j, agent memory, and Amazon Quick in one demo.

## Drift Guard

Drift is the root problem this proposal fixes, so the fix includes a check that keeps it from returning.

`scripts/check-docs.sh` runs two checks:

1. **Links:** `lychee --offline` checks every relative link in Markdown files and notebooks.
2. **Retired names:** A grep fails on any retired name outside the excluded paths. The list starts with `neo4j-agentcore-`, `infra-samples`, `databrick-samples`, `fleet-agent-demo`, `finance_graph`, `finance-agent`, `data-agent`, `orchestrator-agent`, `langgraph-mcp-agent`, and `deploy.sh`.

The check excludes `docs/slides/archive/`, `docs/proposals/`, `organize.md`, `uv.lock`, and generated folders such as `cdk.out/`, `node_modules/`, and `dist/`.

`.github/workflows/check-docs.yml` runs the script on every pull request. The script also runs locally, so each migration phase ends by running it.

## Migration Plan

Each phase ends in a working repo, so the work can stop between phases. Each phase from Phase 2 onward ends with `scripts/check-docs.sh` passing.

### Phase 1: Fix documentation drift and add the drift guard

1. Correct the rows in the drift table above. This step changes no paths.
2. Fix the Aura screenshot link to `../../images/auraagentsapikey.png` so it works before the move.
3. Add `scripts/check-docs.sh` and `.github/workflows/check-docs.yml`. Run the link check only in this phase. The retired-name check turns on at the end of Phase 2, once the old names are gone.

### Phase 2: Move folders

Use `git mv` so history follows each file. Move every folder in the folder rename table except `finance_graph/`, which moves in Phase 3. Apply the smaller moves in the same change. Delete `images/Sagemaker Domains.png` and `images/sagemakeruibuild.png` with `git rm`.

Untracked local state does not move with `git mv`. Several samples hold `.env`, `.mcp-credentials*.json`, and `.bedrock_agentcore/` files that must be moved by hand. The MCP server holds `.mcp-credentials.fleet.json` and `.mcp-credentials.finance.json`. Runtime names do not change in this phase. Each `agent.sh` sets its agent name explicitly, for example `AGENT_NAME="finance_agent"`, so moving a folder does not create a new Runtime.

Update these references in the same change so the repo still works:

- `README.md`, `CLAUDE.md`, and `docs/ARCHITECTURE.md`. Add the sample matrix and the learning path to `README.md`.
- Every sample README that links to a sibling, such as `../neo4j-agentcore-mcp-server/`.
- `docs/slides/current/aws-neo4j-grounded-enterprise-ai.md` lines 621 and 630, which name `neo4j-agentcore-agents/finance-agent`.
- `scripts/sync-credentials.sh`. Its `SOURCE` becomes a per-target file under `../neo4j-mcp-server/`, and each target gets the credentials for its dataset:

  | Target | Source file |
  |--------|-------------|
  | `../quickstart` | `.mcp-credentials.json` |
  | `../demos/aircraft-fleet/supervisor-agent` | `.mcp-credentials.fleet.json` |
  | `../demos/fraud-amazon-quick/fraud-memory-agent` | `.mcp-credentials.finance.json` |

  Its error message points at `./deploy.py` and `--env`, not `./deploy.sh`.
- Code and scripts that print or use a relative path to the MCP server:
  - `finance-agent/core/credentials.py`
  - `finance-agent/.env.example`
  - `orchestrator-agent/core/credentials.py`
  - `langgraph-mcp-agent/neo4j_mcp_agent/core.py`
  - `langgraph-mcp-agent/agent.sh`
  - `fleet-agent-demo/pipeline/setup.sh`
  - `infra-samples/databrick-samples/neo4j-mcp-http-connection.ipynb`
  - `infra-samples/databrick-samples/setup_databricks_secrets.sh`
- Comments that name the `fleet-agent-demo` root: `fleet-agent-demo/.env.sample`, `pipeline/setup.sh`, `pipeline/src/populate_aircraft_db/config.py`, `agent/agent.sh`, `agent/agent/config.py`, and `agent/agent/retrieval.py`.
- `.gitignore` line 194, which ignores `data-agent/.public-urls.txt`.

Folder depth changes, so relative paths to the MCP server change:

| Sample | Old path to the MCP server | New path |
|--------|----------------------------|----------|
| `quickstart/` | `../../neo4j-agentcore-mcp-server/` | `../neo4j-mcp-server/` |
| `demos/aircraft-fleet/*/` | `../../neo4j-agentcore-mcp-server/` | `../../../neo4j-mcp-server/` |
| `demos/fraud-amazon-quick/*/` | `../../neo4j-agentcore-mcp-server/` | `../../../neo4j-mcp-server/` |
| `integrations/databricks/` | `../../neo4j-agentcore-mcp-server/` | `../../neo4j-mcp-server/` |

`.github/workflows/deploy-aws-in-depth-slides.yml` watches `docs/slides/**`. That path does not change, so the workflow needs no update.

End the phase by turning on the retired-name check in `scripts/check-docs.sh`.

### Phase 3: Assemble the fraud demo

1. Move `fraud-memory-agent/finance_graph/` to `fraud-amazon-quick/graph-loader/` and give it its own `pyproject.toml`.
2. Move the data files to `fraud-amazon-quick/data/`. Delete the duplicate copy in `fraud-iceberg/data/`.
3. Point `load_neo4j.py` and the `fraud-iceberg` writers at `../data/`.
4. Merge the two `enrich_gds.py` files into `graph-loader/enrich_gds.py`.
5. Move `fraud-iceberg/analyze_graph.py` into `graph-loader/`.
6. Remove `finance_graph` and the `finance-graph-*` scripts from the agent's `pyproject.toml`.
7. Update the agent README so its `finance_graph/` links point at `../graph-loader/`.
8. Write `fraud-amazon-quick/README.md` as one walkthrough from load to Quick.

Verify that the Neo4j load, GDS enrichment, and Iceberg write produce the same results as before.

### Phase 4: Rename Python packages

Apply the package table above. For each project:

1. Change `name` in `pyproject.toml` and rename console scripts where the table says so.
2. Rename modules where the table says so, and fix their imports. `graph-loader/enrich_gds.py` imports `_connection_settings` from `finance_graph.load_neo4j`, which becomes `graph_loader.load_neo4j`.
3. Run `uv lock` to regenerate `uv.lock`.
4. Update README commands, `CLAUDE.md` commands, `agent.sh` scripts, `Dockerfile` comments, and notebooks that call the old script or module names.
5. Add the old package, module, and script names to the retired-name list in `scripts/check-docs.sh`.

The `neo4j_mcp_agent` module rename touches the most files. Its notebooks and README use `python -m neo4j_mcp_agent...` commands.

### Phase 5: Rename the MCP stack and AgentCore Runtimes

#### MCP server stack

No MCP server is deployed, so this is a code change only. Change the default stack name to `neo4j-mcp-server` in these places:

- `deploy.py` line 81, `DEFAULT_STACK_NAME`, and the help text at lines 1206, 1207, and 1226.
- `cdk/app.py` line 11, the fallback stack name.
- `.env.sample` lines 17, 54, and 63.
- The `STACK_NAME` example in `CLAUDE.md`.

Deploy the MCP server under the new name, once for each `--env` a demo needs. Run `./deploy.py --env NAME credentials` for each, then `scripts/sync-credentials.sh`.

#### Agent Runtimes

Do this after the code under each agent is stable. For an agent with no deployed Runtime, only step 2 applies. For each agent in the Runtime table:

1. Record the current Runtime ARN from `.bedrock_agentcore.yaml`.
2. Change `AGENT_NAME` in `agent.sh` to the new name.
3. Run `./agent.sh configure` and `./agent.sh deploy` to create the new Runtime.
4. Test it with `./agent.sh invoke-cloud`.
5. Delete the old Runtime by its recorded ARN. `scripts/clear_stale_agentcore_runtime.py` in the fraud agent removes the old binding from local config.

Anything that points at an old Runtime ARN must be repointed before step 5. This includes the Amazon Quick setup for `fraud_memory_agent` and any load-test or client configs.

## Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Should `pyproject.toml` package names change to match the new folders? | Yes. See the Python packages table and Phase 4. |
| 2 | Should deployed Runtime names change to match the new folders? | Yes. See the Runtime names table and Phase 5. |
| 3 | Should the top level group samples by how they reach Neo4j? | No. That grouping could not hold end-to-end demos whose parts reach Neo4j in different ways. The top level groups by what a reader deploys or picks. The sample matrix records the access path instead. |
| 4 | Where does the aviation supervisor agent go? | In `demos/aircraft-fleet/supervisor-agent/`, next to the pipeline that loads its data. This fixes the learning path, which previously ran the supervisor before its data existed. |
| 5 | Should `fraud-iceberg/` get its own `lakehouse/` group? | No. It goes inside `demos/fraud-amazon-quick/`. |
| 6 | Where does `finance-agent/finance_graph/` end up? | In `demos/fraud-amazon-quick/graph-loader/`, as its own project. Its data moves to `fraud-amazon-quick/data/`. |
| 7 | Should the MCP server stack name change? | Yes, to `neo4j-mcp-server`. No MCP server is deployed, so nothing in AWS needs migrating. |
| 8 | What happens to `images/Sagemaker Domains.png` and `images/sagemakeruibuild.png`? | Delete them in Phase 2. Nothing references them. |
| 9 | What happens to `docs/slides/archive/`? | Leave it in place. It is out of scope for this reorganization, and the drift guard excludes it. |
