# Finance Agent

A ReAct agent for financial-crime analysis over a Neo4j transaction graph:
accounts, merchants, money transfers, behavioral similarity, and pre-computed
graph metrics. It connects to a Neo4j MCP server through an AgentCore Gateway
and reasons with Claude on Bedrock. This is the simplest agent to deploy:
`agentcore deploy` zips the Python source and uploads it, with no Docker image
required.

## The Graph

The agent is tuned for the money-movement graph behind the MCP server:

| Element | Properties |
|---------|------------|
| `Account` node (25K) | `balance`, `account_type`, `region`, `risk_score` (unbounded, higher is riskier), `community_id`, `betweenness_centrality` |
| `Merchant` node (7.5K) | `merchant_name`, `category` (gaming, restaurant, grocery, ...), `region` |
| `TRANSACTED_WITH` (Account to Merchant, 249K) | `amount`, `txn_hour`, `txn_timestamp` |
| `TRANSFERRED_TO` (Account to Account, 223K) | `amount`, `transfer_timestamp` |
| `SIMILAR_TO` (Account to Account, 243K) | `similarity_score` |

The data is pre-enriched with Neo4j GDS: community IDs, betweenness
centrality, and similarity edges. Questions that traverse the graph
(transfer chains, shared counterparties, communities) get the most out of it.

## Architecture

The agent runs as a `BedrockAgentCoreApp` on AgentCore Runtime. It reasons
with Claude on Bedrock in a ReAct loop, and every Neo4j query goes out through
an AgentCore Gateway to a separate Neo4j MCP server. The agent never talks to
Neo4j directly.

```
  AWS Bedrock AgentCore
  +-------------------------------------------------------------------+
  |                                                                   |
  |  +--------------------------+         +----------------------+     |
  |  |  Finance Agent           |  tools  |  AgentCore Gateway   |     |
  |  |  (AgentCore Runtime)     | ------>  |  (OAuth2 JWT auth)   |     |
  |  |                          |         +----------+-----------+     |
  |  |  BedrockAgentCoreApp     |                    |                 |
  |  |  ReAct loop              |                    v                 |
  |  |   - Claude (Bedrock)     |         +----------------------+     |
  |  |   - MCP client           |         |  Neo4j MCP Server    |     |
  |  |     (streamable_http)    |         |  (AgentCore Runtime) |     |
  |  +--------------------------+         +----------+-----------+     |
  |                                                  |                 |
  +--------------------------------------------------|-----------------+
                                                     v
                                          +--------------------+
                                          |   Neo4j database   |
                                          +--------------------+
```

**How it uses the MCP server.** `core/credentials.py` reads
`.mcp-credentials.json` for the Gateway URL and OAuth2 client credentials. It
runs an OAuth2 client-credentials flow to mint a bearer token, then refreshes
that token in memory before it expires. The MCP client connects to the Gateway
over `streamable_http` with an `Authorization: Bearer` header and loads the
Neo4j tools at runtime. Because tokens refresh themselves, a long-running
deployment keeps working without re-syncing credentials. The local CLI and the
deployed agent take the exact same Gateway path.

**How the remote deploy works.** `agent.sh configure` runs
`agentcore configure`, which writes `.bedrock_agentcore.yaml` with the agent
name, IAM role, and region. `agent.sh deploy` runs `agentcore deploy`, which
uses `direct_code_deploy`: it zips the Python source, uploads it to S3,
triggers CodeBuild to install dependencies, and creates or updates the
AgentCore Runtime agent. No Docker image is built.

**Yes, it deploys to AgentCore.** The deployed target is an Amazon Bedrock
AgentCore Runtime agent. Invoke it with `agent.sh invoke-cloud` or with boto3
via `client/remote.py`, which calls `bedrock-agentcore` `invoke_agent_runtime`
against the deployed runtime ARN.

## Unique Features

- **Shared core, thin entrypoint.** `core/` holds the credentials, token
  refresh, model config, system prompt, MCP transport, and the Bedrock
  model / MCP client factories. The Strands `server/runtime_app.py` and the
  `client/` tooling are thin wrappers over it.
- **Neo4j-backed semantic memory.** When `NEO4J_URI` and
  `NEO4J_PASSWORD` are set, the agent adds Context Graph memory
  tools: `search_context`, `get_entity_graph`, `add_memory`, and
  `get_user_preferences`. Memory is scoped per request by `user_id`. It is
  best-effort and disables cleanly when those env vars are absent.
- **Low-cost default model.** Defaults to Claude Haiku 4.5. Override with
  `MODEL_ID` to use a larger model.

## Layout

| Path | Use |
|------|-----|
| `core/` | Shared credentials, token refresh, model config, prompt, MCP transport + model/client factories |
| `server/runtime_app.py` | AgentCore Runtime entrypoint (8080 deployed, 7020 local via `PORT`) |
| `client/demo.py` | Showcase client, runs the demo questions local or `--remote` |
| `client/local.py` | Local CLI, run a single query directly in the terminal |
| `client/remote.py` | Call the deployed agent programmatically with boto3 |
| `agent.sh` | CLI wrapper for start, test, deploy, invoke |

## Prerequisites

- A deployed Neo4j MCP server with an AgentCore Gateway. See
  [../../neo4j-agentcore-mcp-server/](../../neo4j-agentcore-mcp-server/).
- `.mcp-credentials.json` with `gateway_url`, `client_id`, `client_secret`,
  and `token_url`.
- AWS credentials with Bedrock model access.

## Quick Start: Local

```bash
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
uv sync

# Showcase: runs ALL demo questions in-process, no server, no deploy
uv run python client/demo.py

# Same six questions against the deployed AgentCore agent instead
uv run python client/demo.py --remote

# Pick one question, or just list them
uv run python client/demo.py -n 4
uv run python client/demo.py --list

# One-off question, no server
uv run python client/local.py "Which accounts have the highest risk scores, and who do they transfer money to?"

# Or run the AgentCore server locally on port 7020
./agent.sh start          # in one terminal, leave running
./agent.sh test           # in another, sends the default demo query
```

`client/demo.py` with no arguments runs every question in the
[Demo](#demo) table, locally and in process. It is the fastest way to see
the agent work end to end after `uv sync`.

`./agent.sh start` binds port 7020 and blocks. Run `./agent.sh test` from a
second terminal, or send your own query:

```bash
curl -s -X POST http://127.0.0.1:7020/invocations \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Find circular transfer chains where money returns to its origin account"}'
```

The response streams back as `data:` server-sent events, one JSON chunk per
line (`{"type": "chunk", "data": "..."}`), ending with `{"type": "complete"}`.

## Quick Start: Cloud

```bash
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
uv sync

./agent.sh configure        # generates .bedrock_agentcore.yaml
./agent.sh deploy           # zips source, uploads, creates the runtime
./agent.sh invoke-cloud "Which accounts have the highest risk scores, and who do they transfer money to?"
```

`agentcore deploy` uses `direct_code_deploy`. It packages the source, uploads
it to S3, and creates or updates the AgentCore Runtime agent. No container
build runs.

## Remote Quick Start: Deploy and Run the Demo

End-to-end path from a clean checkout to the full demo running against the
deployed AgentCore Runtime agent.

```bash
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
uv sync

# AWS auth: boto3 and the agentcore CLI need resolvable credentials.
# With AWS SSO, refresh the token and export the profile so boto3 picks
# it up (the AWS CLI may work while boto3 still fails without this):
aws sso login
export AWS_PROFILE=<your-sso-profile>

./agent.sh deploy            # zips source, uploads, creates/updates the runtime

# Run the full six-question demo against the deployed agent
uv run python client/demo.py --remote

# Or a single question against the deployed agent
uv run python client/demo.py --remote -n 1
```

`client/demo.py --remote` reuses `client/remote.py`, which reads the deployed
runtime ARN from `.bedrock_agentcore.yaml` and streams the agent's answer back
to the terminal. The same questions run identically in local mode by dropping
`--remote`, so the demo is the same locally and in the cloud.

Notes:

- `agent.sh deploy` reads `default_agent` from `.bedrock_agentcore.yaml`. It
  must point at `finance_agent` with `entrypoint: .../server/runtime_app.py`. If
  `./agent.sh configure` cannot run interactively in your environment, set
  those two fields directly; everything else in that file is reused as is.
- If the venv was created under a different path, console scripts such as
  `agentcore` carry a stale interpreter. Recreate it with
  `rm -rf .venv && uv sync`.

## Demo

These questions exercise the parts of the graph that a flat database cannot
answer well. `client/demo.py` runs all of them in order: locally by default,
or against the deployed agent with `--remote`. They also work one at a time
via `client/local.py`, `curl`, or `./agent.sh invoke-cloud "..."`.

```bash
uv run python client/demo.py            # all questions, local
uv run python client/demo.py --remote   # all questions, deployed agent
```

| Question | What it shows |
|----------|---------------|
| `Which accounts have the highest risk scores, and who do they transfer money to?` | Risk ranking joined to one hop of transfer behavior. This is the default query. |
| `Find communities of accounts that transfer money among themselves but rarely transact with merchants.` | Uses pre-computed `community_id` to surface insular clusters. |
| `Show the accounts with the highest betweenness centrality and explain why they are money-flow intermediaries.` | Centrality as a structural signal, not just a property lookup. |
| `Detect circular transfer chains where money leaves an account and returns to it, A to B to C to A.` | Multi-hop path pattern, a classic layering signal. |
| `Pick a high-risk account, find behaviorally similar accounts via SIMILAR_TO, and check whether they share transfer counterparties.` | Combines similarity edges with shared-neighbor traversal. |
| `Which merchant categories see the most transaction volume by region?` | Aggregation across `TRANSACTED_WITH` for a baseline, non-graph answer. |

Cross-session memory demo (requires `NEO4J_URI` and `NEO4J_PASSWORD`, see
[Environment Variables](#environment-variables)):

```bash
./agent.sh memory-demo            # default user
./agent.sh memory-demo analyst-1  # scoped to a specific user_id
```

This runs two sessions: the first states a durable fact, the second confirms
the agent recalls it from the Context Graph in a fresh session.

## Commands

`./agent.sh` accepts:

| Command | Description |
|---------|-------------|
| `start` | Run locally on port 7020 |
| `stop` | Stop the local agent |
| `test` | Send a sample query with curl |
| `configure` | Generate AWS deployment config |
| `deploy` | Deploy to AgentCore Runtime |
| `status` | Check deployment status |
| `invoke-cloud "prompt"` | Invoke the deployed agent |
| `memory-demo [user_id]` | Cross-session Context Graph memory demo |
| `destroy` | Remove from AgentCore |

## Environment Variables

| Variable | Required | Default |
|----------|----------|---------|
| `MODEL_ID` | No | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `AWS_REGION` | No | `us-west-2` |
| `NEO4J_URI`, `NEO4J_PASSWORD` | No | Unset. Enables Strands semantic memory when set |

## Refreshing Credentials

The token refreshes itself at runtime. If the Gateway URL or client
credentials change, regenerate and re-copy the file:

```bash
cd ../../neo4j-agentcore-mcp-server && ./deploy.sh credentials && cd -
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
```
