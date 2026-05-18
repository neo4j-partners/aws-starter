# Finance Agent

A ReAct agent for financial-crime analysis over a Neo4j transaction graph:
accounts, merchants, money transfers, behavioral similarity, and pre-computed
graph metrics. It connects to a Neo4j MCP server through an AgentCore Gateway
and reasons with Claude on Bedrock. This is the simplest agent to deploy:
`agentcore deploy` zips the Python source and uploads it, with no Docker image
required.

* **Neo4j MCP server over an AgentCore Gateway:** every graph query goes out
  through a separate Neo4j MCP server reached via an AgentCore Gateway with
  OAuth2 JWT auth. The agent never talks to Neo4j directly.
* **Cross-session agent memory:** Strands semantic memory backed by a Context
  Graph persists durable facts and recalls them in fresh sessions, isolated
  per user.
* **Code-only deploy to AgentCore Runtime:** `agentcore deploy` zips the
  Python source and uploads it with no Docker image, then runs as a
  `BedrockAgentCoreApp` on AgentCore Runtime.
* **Self-refreshing OAuth2 credentials:** an in-memory client-credentials
  flow mints and refreshes the Gateway bearer token, so long-running
  deployments keep working without re-syncing credentials.
* **Graph-native financial-crime analysis:** Claude on Bedrock reasons in a
  ReAct loop over a GDS-enriched money-movement graph with communities,
  betweenness centrality, and similarity edges.
* **One server, thin clients:** `server/runtime_app.py` is the only thing
  that builds the agent. Everything in `client/` is a thin wire client that
  sends a prompt to that running server and streams the answer, so the demo
  is identical against the local server and the deployed runtime.

## Prerequisites

- A deployed Neo4j MCP server with an AgentCore Gateway. See
  [../../neo4j-agentcore-mcp-server/](../../neo4j-agentcore-mcp-server/).
- `.mcp-credentials.json` with `gateway_url`, `client_id`, `client_secret`,
  and `token_url`.
- AWS credentials with Bedrock model access.

## Quick Start: Local

The agent only runs as a server. `client/` holds thin clients that talk to
it; nothing in `client/` builds an agent. So the server must be running
first. It runs in the foreground of its own terminal and stops with Ctrl+C —
nothing backgrounds it, so there is no PID or port to manage.

Set up once:

```bash
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
uv sync
```

Start the server. `uv run finance-server` binds port 7020 and blocks, so
leave it in its own terminal; Ctrl+C stops it:

```bash
# terminal 1: leave this running, Ctrl+C to stop
uv run finance-server
```

In a second terminal, drive it with the thin clients:

```bash
# terminal 2
uv run finance-cli "Which accounts have the highest risk scores?"
uv run finance-demo                      # all demo questions, local server
uv run finance-demo -n 4                 # just question 4
uv run finance-demo --list               # list the questions, run nothing
```

`finance-cli` and `finance-demo` post to the running server and parse its
`data:` server-sent event stream (one JSON chunk per line,
`{"type": "chunk", "data": "..."}`, ending with `{"type": "complete"}`). A
raw `curl` works too:

```bash
curl -s -X POST http://127.0.0.1:7020/invocations \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Find circular transfer chains where money returns to its origin account"}'
```

The same clients hit the deployed agent with `--remote` instead of the local
server. See [Quick Start: Cloud](#quick-start-cloud) and [Demo](#demo).

## Quick Start: Cloud

```bash
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
uv sync

# AWS auth: boto3 and the agentcore CLI need resolvable credentials.
# With AWS SSO, refresh the token and export the profile so boto3 picks
# it up (the AWS CLI may work while boto3 still fails without this):
aws sso login
export AWS_PROFILE=<your-sso-profile>

./agent.sh configure        # generates .bedrock_agentcore.yaml
./agent.sh deploy           # zips source, uploads, creates the runtime
./agent.sh invoke-cloud "Which accounts have the highest risk scores, and who do they transfer money to?"
```

`agentcore deploy` uses `direct_code_deploy`. It packages the source, uploads
it to S3, and creates or updates the AgentCore Runtime agent. No container
build runs. Run the full demo against the deployed agent with
`uv run finance-demo --remote` (see [Demo](#demo)).

Notes:

- `./agent.sh deploy` reads `default_agent` from `.bedrock_agentcore.yaml`. It
  must point at `finance_agent` with `entrypoint: .../server/runtime_app.py`. If
  `./agent.sh configure` cannot run interactively in your environment, set
  those two fields directly; everything else in that file is reused as is.
- If the venv was created under a different path, console scripts such as
  `agentcore` carry a stale interpreter. Recreate it with
  `rm -rf .venv && uv sync`.

## Demo

These questions exercise the parts of the graph that a flat database cannot
answer well. `finance-demo` runs all of them in order against the local
server by default, or against the deployed agent with `--remote`. They also
work one at a time via `uv run finance-cli "..."` (local) or
`./agent.sh invoke-cloud "..."` (deployed).

```bash
uv run finance-demo            # all questions, local server
uv run finance-demo --remote   # all questions, deployed agent
uv run finance-demo --memory   # Context Graph memory showcase
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
uv run finance-invoke memory-demo                    # default user
uv run finance-invoke memory-demo --user-id analyst-1  # specific user_id

uv run finance-demo --memory   # 4-section showcase
```

`finance-invoke memory-demo` runs two sessions: the first states a durable
fact, the second confirms the agent recalls it from the Context Graph in a
fresh session. Add `--verify-neo4j` via
`uv run finance-invoke memory-demo --verify-neo4j` for the ground-truth
check that queries Neo4j directly for the persisted message.

`finance-demo --memory` runs a fuller four-section showcase against the
deployed agent (it ignores `--remote` / `-n`, since Context Graph memory
lives only in the deployed runtime):

1. **Cold start** — a brand-new user; the agent should admit it knows nothing.
2. **Teaching** — the user states a durable preference; the agent persists it
   via `add_memory`.
3. **Cross-session recall** — a fresh session, same user, the preference never
   restated; recall here proves memory survives across sessions.
4. **Per-user isolation** — a different user asks the same question; the first
   user's memory must not leak across the tenant boundary.

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
deployment keeps working without re-syncing credentials. The MCP/Gateway path
lives entirely in `server/runtime_app.py`; the thin clients in `client/` only
send prompts to that server (locally over HTTP, deployed over boto3) and never
touch the Gateway themselves.

**How the remote deploy works.** `./agent.sh configure` runs
`agentcore configure`, which writes `.bedrock_agentcore.yaml` with the agent
name, IAM role, and region. `./agent.sh deploy` runs `agentcore deploy`, which
uses `direct_code_deploy`: it zips the Python source, uploads it to S3,
triggers CodeBuild to install dependencies, and creates or updates the
AgentCore Runtime agent. No Docker image is built.

**Deploys to AgentCore.** The deployed target is an Amazon Bedrock
AgentCore Runtime agent. Invoke it with `./agent.sh invoke-cloud`, or with any
thin client plus `--remote`: `client/transport.py`'s `invoke_deployed` calls
`bedrock-agentcore` `invoke_agent_runtime` against the deployed runtime ARN.

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

## Layout

| Path | Use |
|------|-----|
| `core/` | Shared credentials, token refresh, model config, prompt, MCP transport + model/client factories |
| `server/runtime_app.py` | The agent. AgentCore Runtime entrypoint and the only agent builder. `main()` is `finance-server` (7020 local); the cloud container uses `__main__` (fixed 8080) |
| `client/transport.py` | The one wire layer: `invoke_local` (HTTP+SSE) / `invoke_deployed` (boto3) |
| `client/cli.py` | `finance-cli`: thin terminal client, one prompt, `--remote` toggles target |
| `client/demo.py` | `finance-demo`: thin showcase client, all demo questions + `--memory`, local or `--remote` |
| `client/invoke.py` | `finance-invoke`: deployed harness: one-shot, `load-test`, `memory-demo`, `--verify-neo4j` |
| `agent.sh` | Deployment helper only: `configure`, `deploy`, `status`, `invoke-cloud`, `destroy` |

## Commands

The server and clients run as `uv` console scripts (no wrapper script).
Run the server in its own terminal; Ctrl+C stops it:

| Command | Description |
|---------|-------------|
| `uv run finance-server` | Run the agent server locally on port 7020 (Ctrl+C to stop) |
| `uv run finance-cli "prompt"` | Ask the running local server (`--remote` for the deployed agent) |
| `uv run finance-demo` | Run the demo questions against the local server (`--remote`, `-n N`, `--list`, `--memory`) |
| `uv run finance-invoke memory-demo` | Cross-session Context Graph memory demo (`--user-id`, `--verify-neo4j`) |
| `uv run finance-invoke load-test` | Load test the deployed agent (`--interval N`) |

`./agent.sh` is the deployment helper (it injects `NEO4J_URI`/`NEO4J_PASSWORD`
into the runtime env on `deploy`):

| Command | Description |
|---------|-------------|
| `configure` | Generate AWS deployment config |
| `deploy` | Deploy to AgentCore Runtime |
| `status` | Check deployment status |
| `invoke-cloud "prompt"` | Invoke the deployed agent |
| `destroy` | Remove from AgentCore |

## Environment Variables

| Variable | Required | Default |
|----------|----------|---------|
| `MODEL_ID` | No | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `AWS_REGION` | No | `us-west-2` |
| `NEO4J_URI`, `NEO4J_PASSWORD` | No | Unset. Enables Strands semantic memory when set |
| `PORT` | No | Local: `7020` (`finance-server` default). Cloud container: fixed `8080` |

The deployed AgentCore container always listens on **8080**: that is the
platform's fixed `/invocations` contract and is not configurable. For local
runs, `finance-server` defaults to `PORT=7020` so it does not collide with
anything already on 8080; an explicit `PORT` still wins. The same
`server/runtime_app.py` serves both.

## Refreshing Credentials

The token refreshes itself at runtime. If the Gateway URL or client
credentials change, regenerate and re-copy the file:

```bash
cd ../../neo4j-agentcore-mcp-server && ./deploy.sh credentials && cd -
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
```
