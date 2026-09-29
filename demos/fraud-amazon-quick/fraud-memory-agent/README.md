# Fraud Memory Agent

This Strands agent investigates financial-crime patterns in a Neo4j graph. It
reaches the graph through an Amazon Bedrock AgentCore Gateway and records every
turn in the hosted Neo4j Agent Memory Service.

## Overview

- **Graph access:** The agent calls Neo4j MCP tools through the AgentCore Gateway. It never connects to Neo4j directly.
- **NAMS:** The Neo4j Agent Memory Service, called **NAMS** below, stores each user and assistant turn. It also extracts entities and records MCP tool calls as reasoning traces.
- **Separate stores:** The fraud graph and agent memory stay apart. The MCP server owns graph access. NAMS owns memory storage, embeddings, and its schema.
- **Credentials:** The agent needs no `NEO4J_*` values. It needs a NAMS API key and the Gateway credentials file `.mcp-credentials.json`.
- **Local and cloud:** You can run the agent locally on port 7020 or deploy it to AgentCore Runtime with `agent.sh`.
- **Traffic generator:** A load client sends synthetic analyst traffic so you can inspect memory in NAMS.

## Quick start

This assumes the graph is loaded and the MCP server is deployed. See
[Connect the agent to the fraud graph](#connect-the-agent-to-the-fraud-graph).
Run from `demos/fraud-amazon-quick/fraud-memory-agent/`:

```bash
cp .env.sample .env              # set MEMORY_API_KEY=nams_...
uv sync

uv run fraud-server              # Terminal 1
uv run fraud-cli --user-id analyst-1 "Find circular transfer chains"   # Terminal 2

./agent.sh configure             # deploy to AgentCore Runtime
./agent.sh deploy
./agent.sh verify
```

## Prerequisites

- **MCP server:** You need a deployed Neo4j MCP server and AgentCore Gateway. See [`neo4j-mcp-server/`](../../../neo4j-mcp-server/).
- **AWS credentials:** Your AWS credentials need access to the configured Bedrock model.
- **NAMS API key:** You can create a key at [NAMS](https://memory.neo4jlabs.com/).

## What NAMS captures

Each call to the agent creates a NAMS conversation. The conversation is
tagged with the request's `user_id` and `session_id`.

- **Messages:** NAMS saves the text messages when the turn completes.
- **Entities:** NAMS extracts entities on the server side.
- **Reasoning traces:** NAMS saves each MCP tool call as a reasoning trace.
- **Conversation ID:** NAMS assigns the stored conversation UUID. The agent keeps `session_id` as metadata, so you can group load runs in the NAMS workspace.

The agent does not add workspace-wide search results to its prompts. This
keeps a shared NAMS workspace safe for synthetic multi-user load runs.

## Fraud graph dataset

The synthetic fraud dataset is committed in
[`demos/fraud-amazon-quick/data/`](../data/). It holds 25,000 accounts, 7,500
merchants, 250,000 merchant transactions, and 300,000 transfers.

- **Loader:** The direct Neo4j loader and the optional GDS enrichment step are documented in [`demos/fraud-amazon-quick/graph-loader/`](../graph-loader/README.md).
- **Ontology:** The file [`demos/fraud-amazon-quick/graph-loader/ontology.md`](../graph-loader/ontology.md) defines the business terms for the fraud domain. It explains what each investigation signal means and where it stops. It is an informal graph vocabulary, not an RDF or TTL ontology.

## Connect the agent to the fraud graph

The agent needs a deployed Neo4j MCP server whose `NEO4J_*` settings point to
the database with this dataset. The agent sends tool calls to the MCP server
through the AgentCore Gateway. The MCP server then connects to Neo4j.

Set up the graph and MCP server in this order. All paths and commands start
from the repo root.

1. In [`neo4j-mcp-server/`](../../../neo4j-mcp-server/), set the URI, database name, username, and password in `.env.finance`. Use a Neo4j database set aside for this demo.
2. In [`demos/fraud-amazon-quick/graph-loader/`](../graph-loader/README.md), put the same values in `.env` and load the graph. Run the GDS enrichment command if your questions need risk scores, communities, betweenness, or account similarity.
3. Deploy the MCP server, create its Gateway client credentials, and copy them to this agent:

   ```bash
   cd neo4j-mcp-server
   ./deploy.py --env finance
   ./deploy.py --env finance credentials
   ../scripts/sync-credentials.sh
   ```

   `sync-credentials.sh` copies `.mcp-credentials.finance.json` to
   `demos/fraud-amazon-quick/fraud-memory-agent/.mcp-credentials.json`.

4. Go to `demos/fraud-amazon-quick/fraud-memory-agent/` and start or deploy the agent. The agent reads `.mcp-credentials.json`, refreshes the OAuth token in memory, and uses the Gateway URL in that file to find and call the Neo4j MCP tools.

- **Graph loader settings:** The graph loader keeps its `NEO4J_*` values in `demos/fraud-amazon-quick/graph-loader/.env`. They must point to the same database as the MCP server.
- **Credentials file:** The file `.mcp-credentials.json` holds the Gateway OAuth client secret. Keep it out of git.

## Local run

Run from `demos/fraud-amazon-quick/fraud-memory-agent/`:

```bash
cp .env.sample .env
# Set MEMORY_API_KEY=nams_... in .env
uv sync

# Terminal 1
uv run fraud-server              # or ./agent.sh start; ./agent.sh stop stops it

# Terminal 2
uv run fraud-cli --user-id analyst-1 "Find circular transfer chains"
uv run fraud-demo                # runs a set of sample graph questions
uv run fraud-invoke --local memory-demo   # two turns in one session
./agent.sh test                  # one default question to the local server
```

- **`MEMORY_API_KEY`:** This key is required. Without it, every request returns an error.
- **`MEMORY_ENDPOINT` and `MEMORY_WORKSPACE_ID`:** These values are optional. Set them for a private or staging NAMS deployment.
- **`MODEL_ID`:** This value is optional. The default is `global.anthropic.claude-haiku-4-5-20251001-v1:0`.
- **`AWS_REGION`:** This value is optional. The default is `us-west-2`.
- **`PORT`:** This value is optional. The local server uses port 7020 by default.
- **`--remote`:** This `fraud-cli` flag sends the question to the deployed runtime instead of the local server.

Open your NAMS workspace to see the conversations, extracted entities, and
reasoning traces from these runs.

## Deploy to AgentCore

Run from `demos/fraud-amazon-quick/fraud-memory-agent/`:

```bash
./agent.sh configure
./agent.sh deploy
./agent.sh verify
./agent.sh invoke-cloud "Find circular transfer chains"
```

- **Memory settings:** `agent.sh deploy` reads `MEMORY_API_KEY` from `.env` and injects it into the runtime. It also passes `MEMORY_ENDPOINT` and `MEMORY_WORKSPACE_ID` when you set them.
- **Smoke test:** A deploy counts as verified only after the runtime is `READY` and a one-turn graph test succeeds. This test calls the real NAMS, model, and Neo4j MCP server.
- **`--skip-smoke`:** This flag uploads without the smoke test. Run `./agent.sh verify` before you send traffic to it.
- **Dependency rebuild:** Deploy records a fingerprint of `pyproject.toml` and `uv.lock`. When either file changes, deploy forces AgentCore to rebuild dependencies. Add `--force-rebuild-deps` to force a rebuild yourself.
- **Stale runtime binding:** Deploy clears the saved runtime binding only when the runtime is in another Region or AWS confirms it no longer exists.

Recovery and diagnostics commands:

```bash
./agent.sh status                 # control-plane deployment state
./agent.sh verify                 # READY state plus the end-to-end graph smoke test
./agent.sh logs --errors          # recent failed AgentCore observability traces
./agent.sh reset-config           # archive only local config; AWS resources stay intact
./agent.sh configure              # create fresh local config after reset-config
./agent.sh destroy                # remove the agent from AgentCore Runtime
```

## Generate NAMS traffic

The load generator calls the real agent with synthetic analyst profiles.
Every successful request becomes NAMS memory, and its MCP tool calls become
reasoning traces.

- **Sessions:** Each synthetic conversation shares one session ID across its turns.
- **Concurrency:** The generator limits how many sessions run at once.
- **Progress:** The generator logs each session and turn as it starts and ends. Each line shows the session number, turn number, duration, and any error.
- **Exit code:** A nonzero exit code means at least one request failed.

Run from `demos/fraud-amazon-quick/fraud-memory-agent/`. Preview a plan first:

```bash
uv run python -m client.traffic --users 20 --sessions-per-user 3 \
  --turns-per-session 4 --concurrency 4 --dry-run
```

That plan has 240 agent turns. Run it locally after you start `fraud-server`:

```bash
uv run python -m client.traffic --users 20 --sessions-per-user 3 \
  --turns-per-session 4 --concurrency 4
```

Or send it to the deployed runtime:

```bash
uv run python -m client.traffic --remote --users 100 \
  --sessions-per-user 5 --turns-per-session 4 --concurrency 4 \
  --timeout 600 --retry-attempts 1 --run-id sept-demo-retry
```

The last command sends 2,000 agent turns. It runs four sessions at once and
waits up to ten minutes for each reply. Multi-step model, graph, and NAMS work
needs that time. Start at this level. Raise concurrency only after you check
your Bedrock, AgentCore, and NAMS limits.

`uv run fraud-traffic` is the same command as `uv run python -m client.traffic`.

- **`--timeout`:** This flag sets the read timeout in seconds. The default is 300. The botocore default of 60 seconds is too short for model, graph, and NAMS work.
- **`--retry-attempts`:** This flag sets the total number of attempts. The default is 1. A retry after a read timeout can store a completed turn twice in NAMS, so use `--retry-attempts 2` only when duplicates are acceptable.
- **`--continue-after-error`:** This flag keeps sending later turns in a session after one fails. By default, the generator skips them.
- **`--run-id`:** This flag adds an identifier to the synthetic user and session IDs, so you can tell runs apart.
- **Ctrl+C:** Pressing Ctrl+C stops unsent sessions and exits right away. Up to `--concurrency` requests already in flight can still finish on the server.

For a slow, steady stream in one conversation:

```bash
uv run fraud-invoke load-test --local --user-id soak-test --interval 5
```

## Request format

The local `/invocations` endpoint and the AgentCore runtime accept this
payload:

```json
{
  "prompt": "Find high-risk transfer communities",
  "user_id": "analyst-1",
  "session_id": "investigation-42"
}
```

`session_id` is optional. Without it, the runtime uses `fraud-<user_id>` as
the ID and stores it in the conversation metadata.

## Architecture

```text
client.traffic / client.cli
          |
          v
Bedrock AgentCore Runtime
  |                     |
  |                     +--> NAMS
  |                          messages, entities, reasoning traces
  v
AgentCore Gateway --> Neo4j MCP server --> fraud graph
```

NAMS and the fraud graph share no credentials and no database connection.

## Limitation: no session recall yet

The newer Neo4j Agent Memory docs describe a Strands `Neo4jSessionManager`.
It saves a conversation and restores it when an agent reuses a session ID.
The released `neo4j-agent-memory` 0.5.0 package used here does not export that
API, so this agent does not use it.

- **What the agent does:** The agent creates one NAMS conversation per call. It stores `session_id` as metadata and records the prompt, response, and MCP tool calls.
- **What the agent does not do:** The agent does not load earlier turns into a later call.
- **Upgrade path:** Upgrade to a release that exports `Neo4jSessionManager` before you rely on recall across calls.
