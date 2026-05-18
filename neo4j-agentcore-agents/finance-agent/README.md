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
* **Same path local and cloud:** the local CLI and the deployed agent take
  the identical Gateway route, so the demo runs the same in process and
  against the deployed runtime.

## Prerequisites

- A deployed Neo4j MCP server with an AgentCore Gateway. See
  [../../neo4j-agentcore-mcp-server/](../../neo4j-agentcore-mcp-server/).
- `.mcp-credentials.json` with `gateway_url`, `client_id`, `client_secret`,
  and `token_url`.
- AWS credentials with Bedrock model access.

## Quick Start: Local

Set up once:

```bash
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
uv sync
```

Then pick one of the following. They are alternatives, not a sequence.

**Run the showcase in process** (no server, no deploy). This is the fastest
way to see the agent work end to end:

```bash
uv run python client/demo.py            # every question in the Demo table
uv run python client/demo.py -n 4       # just question 4
uv run python client/demo.py --list     # list the questions, run nothing
```

**Ask a one-off question** (no server):

```bash
uv run python client/local.py "Which accounts have the highest risk scores, and who do they transfer money to?"
```

**Run the AgentCore server locally** on port 7020. `./agent.sh start` binds
the port and blocks, so use two terminals:

```bash
# terminal 1: leave this running
./agent.sh start
```

```bash
# terminal 2: send the default demo query
./agent.sh test

# or send your own query
curl -s -X POST http://127.0.0.1:7020/invocations \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Find circular transfer chains where money returns to its origin account"}'
```

The server response streams back as `data:` server-sent events, one JSON
chunk per line (`{"type": "chunk", "data": "..."}`), ending with
`{"type": "complete"}`.

Running against the deployed agent (`client/demo.py --remote`) is covered in
[Quick Start: Cloud](#quick-start-cloud) and [Demo](#demo).

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
`uv run python client/demo.py --remote` (see [Demo](#demo)).

Notes:

- `agent.sh deploy` reads `default_agent` from `.bedrock_agentcore.yaml`. It
  must point at `finance_agent` with `entrypoint: .../server/runtime_app.py`. If
  `./agent.sh configure` cannot run interactively in your environment, set
  those two fields directly; everything else in that file is reused as is.
- If the venv was created under a different path, console scripts such as
  `agentcore` carry a stale interpreter. Recreate it with
  `rm -rf .venv && uv sync`.

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

**Deploys to AgentCore.** The deployed target is an Amazon Bedrock
AgentCore Runtime agent. Invoke it with `agent.sh invoke-cloud` or with boto3
via `client/remote.py`, which calls `bedrock-agentcore` `invoke_agent_runtime`
against the deployed runtime ARN.

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
| `server/runtime_app.py` | AgentCore Runtime entrypoint (8080 deployed, 7020 local via `PORT`) |
| `client/demo.py` | Showcase client, runs the demo questions local or `--remote` |
| `client/local.py` | Local CLI, run a single query directly in the terminal |
| `client/remote.py` | Call the deployed agent programmatically with boto3 |
| `agent.sh` | CLI wrapper for start, test, deploy, invoke |

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
| `PORT` | No | `8080`. HTTP port the runtime binds; `./agent.sh start` sets `7020` for local |

The deployed AgentCore container always listens on **8080** — that is the
platform's fixed `/invocations` contract and is not configurable. For local
runs, `./agent.sh start` exports `PORT=7020` so it does not collide with
anything already on 8080; the same `server/runtime_app.py` serves both.

## Refreshing Credentials

The token refreshes itself at runtime. If the Gateway URL or client
credentials change, regenerate and re-copy the file:

```bash
cd ../../neo4j-agentcore-mcp-server && ./deploy.sh credentials && cd -
cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .
```
