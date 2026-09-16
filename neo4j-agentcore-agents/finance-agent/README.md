# Finance Agent

This Strands agent investigates financial-crime patterns in a Neo4j graph
through an Amazon Bedrock AgentCore Gateway. It uses the hosted Neo4j Agent
Memory Service (NAMS) to capture every user and assistant turn, extract
entities, and record MCP tool calls as reasoning traces.

The finance graph and agent memory are deliberately separate. The MCP server
owns graph access; NAMS owns memory storage, embeddings, and its schema. The
agent needs no direct Neo4j credentials for memory.

## What NAMS captures

Each invocation is captured in a NAMS conversation tagged with the request's
`user_id` and `session_id`.

- Text messages are persisted automatically when the turn completes.
- NAMS extracts entities server-side.
- MCP tool uses are saved as reasoning traces.
- NAMS assigns the stored conversation UUID; `session_id` is retained as
  metadata so load runs can be grouped in the NAMS workspace.

This sample captures traffic without injecting workspace-wide search results
into prompts. That keeps a shared NAMS workspace safe for synthetic
multi-user load runs.

## Prerequisites

- A deployed Neo4j MCP server and AgentCore Gateway. See
  [../../neo4j-agentcore-mcp-server/](../../neo4j-agentcore-mcp-server/).
- AWS credentials with access to the configured Bedrock model.
- A NAMS API key from [NAMS](https://memory.neo4jlabs.com/).

## Finance graph dataset

The exact synthetic fraud dataset used by this agent is committed in
[finance_graph/data/](./finance_graph/data/). Its 25,000 accounts, 7,500
merchants, 250,000 merchant transactions, and 300,000 transfers are copied
from Finance Genie. The direct Neo4j loader and optional GDS enrichment step
are documented in [finance_graph/](./finance_graph/README.md).

[finance_graph/ontology.md](./finance_graph/ontology.md) defines the proposed
informal, graph-native business vocabulary for the fraud domain. It documents
the meaning and limits of investigation signals without adding a formal
RDF/TTL ontology.

### Connect the agent to the finance graph

Yes: the agent needs a deployed Neo4j MCP server whose `NEO4J_*` settings
point to the database that contains this dataset. The agent never opens a
Bolt connection itself. It sends tool calls to the MCP server through the
AgentCore Gateway, and that server connects to Neo4j.

Set up the graph and MCP server in this order:

1. In [../../neo4j-agentcore-mcp-server/](../../neo4j-agentcore-mcp-server/),
   configure `.env` with the URI, database name, username, and password for a
   dedicated Neo4j database.
2. In this directory, put the same values in `.env` and load the bundled
   graph. Run the GDS enrichment command if the investigation prompts need
   risk scores, communities, betweenness, or account similarity.
3. Deploy the MCP server, then create its Gateway client credentials and copy
   them here:

   ```bash
   cd ../../neo4j-agentcore-mcp-server
   ./deploy.py
   ./deploy.py credentials
   cp .mcp-credentials.json ../neo4j-agentcore-agents/finance-agent/
   ```

4. Return here and start or deploy the finance agent. It reads
   `.mcp-credentials.json`, refreshes the OAuth token in memory, and uses the
   Gateway URL in that file to discover and call the Neo4j MCP tools.

The `NEO4J_*` values in this project's `.env` are only for
`finance-graph-load` and `finance-graph-enrich`; they must identify the same
database configured for the MCP server. The credentials file is required by
the agent and contains the Gateway OAuth client secret, so keep it untracked.

## Local run

```bash
cp .env.example .env
# Set MEMORY_API_KEY=nams_... in .env
uv sync

# Terminal 1
uv run finance-server

# Terminal 2
uv run finance-cli --user-id analyst-1 "Find circular transfer chains"
uv run finance-demo
```

Open your NAMS workspace to inspect the conversations, extracted entities,
and reasoning traces produced by these real agent invocations.

## Deploy to AgentCore

```bash
./agent.sh configure
./agent.sh deploy
./agent.sh verify
```

`agent.sh deploy` reads `MEMORY_API_KEY` from `.env` and injects it into the
runtime. It also forwards optional `MEMORY_ENDPOINT` and `MEMORY_WORKSPACE_ID`
values when present. A deploy is only reported as verified after the runtime is
`READY` and a one-turn graph smoke test succeeds. That request intentionally
uses the real NAMS, model, and Neo4j MCP integration. To upload without this
check, use `./agent.sh deploy --skip-smoke`, then run `./agent.sh verify`
before directing traffic to it.

Useful recovery and diagnostics commands:

```bash
./agent.sh status                 # control-plane deployment state
./agent.sh verify                 # READY state plus the end-to-end graph smoke test
./agent.sh logs --errors          # recent failed AgentCore observability traces
./agent.sh reset-config           # archive only local config; AWS resources stay intact
./agent.sh configure              # create fresh local config after reset-config
```

`deploy` also clears a runtime binding only when it is cross-region or AWS
confirms the configured runtime no longer exists. It records a local dependency
fingerprint and forces an AgentCore dependency rebuild when `pyproject.toml` or
`uv.lock` changes.

## Generate NAMS traffic

The load generator invokes the real agent. It uses only synthetic analyst
profiles, shares a session ID across the turns in each synthetic conversation,
and limits concurrent sessions. Every successful request becomes NAMS memory
and records any MCP tool calls as reasoning traces.

Preview a plan first:

```bash
uv run python -m client.traffic --users 20 --sessions-per-user 3 \
  --turns-per-session 4 --concurrency 4 --dry-run
```

That plan has 240 agent turns. Run it locally after starting `finance-server`:

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

The last command generates 2,000 agent turns. It uses four concurrent sessions
and a ten-minute read timeout, which provides headroom for multi-step model,
graph, and NAMS work. Start at this level and increase concurrency only after
checking Bedrock, AgentCore, and NAMS limits. A nonzero exit code means one or
more requests failed. The generator logs each session and turn as it starts and
completes, including its session number, turn number, duration, and any error,
so active concurrent work is visible while a run is in progress. Failed traffic
can be rerun by `--run-id`.

Remote turns have a five-minute read timeout by default because model, graph,
and NAMS work can exceed botocore's 60-second default. The generator makes one
attempt by default: retrying an invocation after a read timeout can duplicate
a completed turn in NAMS. Use `--retry-attempts 2` only when that duplication
is acceptable. After a turn fails, later dependent turns in that session are
not sent unless `--continue-after-error` is supplied. Ctrl+C prevents unsent
sessions from starting and exits the load client immediately; at most the
current `--concurrency` invocations can still complete server-side.

For a continuous low-rate stream in one conversation:

```bash
uv run finance-invoke load-test --local --user-id soak-test --interval 5
```

## Request contract

The local `/invocations` endpoint and AgentCore runtime accept:

```json
{
  "prompt": "Find high-risk transfer communities",
  "user_id": "analyst-1",
  "session_id": "investigation-42"
}
```

`session_id` is optional. If omitted, the runtime derives a stable correlation
ID from the user (`finance-<user_id>`), which is stored in conversation metadata.

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
AgentCore Gateway --> Neo4j MCP server --> finance graph
```

NAMS and the finance graph do not share credentials or a database connection.

## Published Strands session-manager limitation

The newer Neo4j Agent Memory documentation describes a Strands
`Neo4jSessionManager` that persists and restores a conversation automatically
when an agent reuses a session ID. That API is not exported by the released
`neo4j-agent-memory` 0.5.0 package used by this sample. It is therefore not
enabled here.

This sample creates one NAMS conversation for each agent invocation, stores
the supplied `session_id` as conversation metadata, and records the prompt,
response, and MCP tool calls. It is suitable for generating and inspecting
memory traffic, but it does not inject or restore earlier turns into a later
agent invocation. Upgrade to a release that exports `Neo4jSessionManager`
before relying on automatic cross-invocation session recall.
