# Aircraft Fleet Demo

This demo builds an aircraft fleet graph in Neo4j and answers questions about
it with a supervisor agent on Amazon Bedrock. One pipeline builds the graph.
One supervisor agent and its two specialists read it.

![The pipeline builds the Neo4j fleet graph. One supervisor routes each question to a Maintenance or Operations specialist. The specialists read the graph directly with the Neo4j driver. The supervisor keeps conversation memory in a separate Neo4j database. The browser UI relays the supervisor's stream and looks up each tool call's evidence in the fleet graph.](docs/images/architecture.svg)

## Overview

- **One graph, two kinds of data:** The graph joins live fleet records with knowledge from maintenance manuals. An agent can move from a sensor on one aircraft to the limit the manual sets for it.
- **One pipeline:** The pipeline generates the fleet data, loads it, enriches it from the manuals with Bedrock, links the two graphs, and verifies the result.
- **One agent:** The supervisor agent routes each question to a Maintenance or Operations specialist. The specialists read Neo4j directly with the Neo4j Python driver.
- **Memory:** The supervisor remembers each session and what it learns about a user. Memory lives in its own Neo4j database, apart from the fleet graph.
- **Browser UI:** The UI shows the answer next to a live evidence graph and a trace of the tool calls.
- **AgentCore Runtime:** The supervisor runs locally for development and deploys to Amazon Bedrock AgentCore Runtime.

## The three projects

### Pipeline

The [`pipeline/`](./pipeline/) project builds the Aircraft Digital Twin graph.

- **Synthetic fleet:** It generates aircraft, systems, components, sensors, hourly readings, flights, delays, and maintenance events from a fixed seed.
- **Operating limits:** The generator writes the limits that the manuals state to a CSV. The loader writes them to the graph and links each sensor to its limits.
- **Manual enrichment:** It chunks the maintenance manuals, embeds each chunk with Bedrock Titan, and extracts faults and procedures with Bedrock Claude. It links each operating limit to the chunks that state it.
- **Graph fusion:** It links the extracted knowledge to the real aircraft, systems, and components.
- **Indexes:** It creates the vector and fulltext chunk indexes that the Maintenance specialist searches.
- **Checks:** It stamps each dataset and verifies node counts and stamps after every load. It also checks that every sensor except `AirDataDisagree` has a limit. It checks that every limit links to a manual chunk.

### Supervisor agent

The [`supervisor-agent/`](./supervisor-agent/) project is a Strands supervisor with two specialists.

- **Routing:** The supervisor sends each question to the Maintenance Agent, the Operations Agent, or both. It then writes one answer from their results.
- **Text2Cypher:** Both specialists use `graph_query_tool`, which writes Cypher from the live schema for exact and aggregate questions.
- **Hybrid search:** The Maintenance specialist also uses `vector_search_tool`, which combines vector and fulltext search over the manual chunks.
- **Read-only:** Each generated query must plan as read-only before it runs. The deployed agent logs in as a read-only Neo4j user.
- **Safe errors:** The tools replace raw database errors before the model sees them, so no address leaks into an answer.

### Browser UI

The [`ui/`](./ui/) project pairs the supervisor chat with a live evidence graph
and a tool call trace. Select a finished tool call to highlight its evidence.

## Quick start

Check the [prerequisites](#prerequisites) first. `./setup.sh` needs AWS
credentials with Bedrock access, and the default dataset needs a paid Aura tier
or a local Neo4j.

Run these commands from `demos/aircraft-fleet/`:

```bash
cp .env.sample .env          # set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, MEM_NEO4J_URI, MEM_NEO4J_PASSWORD

cd pipeline
uv sync
./setup.sh                   # build the graph

cd ../supervisor-agent
uv sync
./agent.sh start             # terminal 1: serves http://localhost:7071
./agent.sh test-maintenance  # terminal 2: a question for Maintenance
./agent.sh test-operations   # a question for Operations
```

## Prerequisites

- **Neo4j:** You need a Neo4j 5.23 or later database for the fleet graph. Neo4j Aura works well. The default dataset is past the Aura Free limits, so use a paid tier or a local Neo4j.
- **Memory database:** You need a second Neo4j database or instance for agent memory. It can start empty.
- **Read-only user:** The cloud deploy reads the fleet graph as a read-only Neo4j user. The [supervisor README](./supervisor-agent/README.md#create-the-secrets) shows how to create it, including the extra role Aura needs.
- **AWS:** You need AWS credentials with Bedrock access to Claude and the Titan embedding model.
- **Tools:** You need the [`uv`](https://docs.astral.sh/uv/) package manager and Python 3.12 or later. The UI build needs Node.js 20 or later.
- **Deploy tools:** Cloud deploys need the AgentCore CLI, installed with `npm install -g @aws/agentcore`. The agent is tested with version 1.2.0.

## Configure

The pipeline, the supervisor agent, and the UI read one `.env` file in
`demos/aircraft-fleet/`.

```bash
cp .env.sample .env
```

- **Fleet graph:** Set `NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD`. The pipeline writes with this login. The supervisor and the UI read with it until the secret ARNs are set.
- **Memory:** Set `MEM_NEO4J_URI` and `MEM_NEO4J_PASSWORD`. Set `MEM_NEO4J_USERNAME` and `MEM_NEO4J_DATABASE` too if they are not `neo4j`. The supervisor stops at startup if the URI or the password is missing.
- **Secrets:** For a deploy, set `NEO4J_PASSWORD_SECRET_ARN` and `MEM_NEO4J_PASSWORD_SECRET_ARN`. See Step 3.
- **Another file:** Set `FLEET_ENV_FILE` to load a different file. A value already set in the environment wins.

## Step 1: Build the graph

![Pipeline flow](docs/images/pipeline-flow.svg)

Run these commands from `demos/aircraft-fleet/pipeline/`:

```bash
uv sync
./setup.sh                   # generate, load, enrich, index and fuse, verify
```

- **Default size:** The default loads 30 aircraft over 90 days, about 800,000 nodes.
- **Full size:** Set `LOAD_FULL_DATASET=true` in `.env` to load 100 aircraft.
- **No model calls:** Run `./setup.sh load-operational` to build only the operational graph. Its final check prints warnings for the missing manual enrichment. It still fails on a problem in the operational data.

See the [pipeline README](./pipeline/README.md) for each stage and the dual graph.

![The dual graph](docs/images/dual-graph.svg)

## Step 2: Run the supervisor agent

Run these commands from `demos/aircraft-fleet/supervisor-agent/`:

```bash
uv sync
./agent.sh start             # serves http://localhost:7071
./agent.sh test-maintenance
./agent.sh test-operations
uv run fleet-supervisor-cli "Compare fault counts with delay counts"
```

To use the browser UI, keep the server running and start the UI in a second
terminal from `demos/aircraft-fleet/ui/`:

```bash
npm ci
npm run build
uv run --project ../supervisor-agent python server.py   # serves http://127.0.0.1:8081
```

See the [UI README](./ui/README.md) for the starter question and for using a
deployed supervisor.

## Step 3: Deploy to AgentCore Runtime

The deployed agent logs in to the fleet graph as a read-only user and reads
both passwords from Secrets Manager. Run these steps from
`demos/aircraft-fleet/supervisor-agent/`:

1. **Create the read-only user:** Create `fleet_reader` on the fleet graph with the Cypher in [Create the read-only user](./supervisor-agent/README.md#create-the-read-only-user).
2. **Create the secrets:** Add `NEO4J_READER_USERNAME` and `NEO4J_READER_PASSWORD` to `.env`, run `uv run fleet-supervisor-secrets`, and add the two ARN lines it prints to `.env`.
3. **Deploy:** Run `./agent.sh deploy`. When the deploy succeeds, it writes the runtime's `AGENT_ARN` and `AWS_REGION` to `.env`. Then run `./agent.sh invoke-cloud "What are the most common maintenance faults?"`.

See the [supervisor agent README](./supervisor-agent/README.md) for routing,
the deploy settings, load testing, and teardown.

## Keep the embedder the same

`vector_search_tool` works only when the agent and the pipeline use the same
embedding model and dimensions.

- **Default:** Both sides use `amazon.titan-embed-text-v2:0` with 1024 dimensions.
- **Changes:** If you change the pipeline embedder, set `EMBED_MODEL_ID` and `EMBED_DIMENSIONS` in `.env` to match.
- **Mismatch:** A mismatch makes vector search return poor results or nothing.

## Diagrams

The diagrams live in [`docs/images/`](./docs/images/) as SVG files.

| Diagram | Shows |
|---------|-------|
| [`architecture.svg`](docs/images/architecture.svg) | The pipeline, the supervisor and its specialists, the browser UI, and the two databases |
| [`pipeline-flow.svg`](docs/images/pipeline-flow.svg) | The five pipeline stages and what each one writes |
| [`dual-graph.svg`](docs/images/dual-graph.svg) | The operational graph, the knowledge graph, and the links between them |
| [`supervisor-request-flow.svg`](docs/images/supervisor-request-flow.svg) | One request through the supervisor, a specialist, and its graph tools |
| [`memory-lifecycle.svg`](docs/images/memory-lifecycle.svg) | How the supervisor opens, uses, and closes conversation memory |
| [`data-model.svg`](docs/images/data-model.svg) | The operational node labels and relationship types, including the operating limits |
| [`generator-flow.svg`](docs/images/generator-flow.svg) | The six data generator stages, atomic publish, and the output checks |
| [`end-to-end-sequence.svg`](docs/images/end-to-end-sequence.svg) | One question through the Maintenance specialist, Text2Cypher, and Neo4j |
| [`deployment-topology.svg`](docs/images/deployment-topology.svg) | The one stack, the AWS services, and the two Neo4j databases |

## More detail

- **Architecture:** The [fleet architecture document](./docs/ARCHITECTURE.md) explains how the parts fit together. Each part has its own document: [pipeline](./docs/architecture/pipeline.md), [supervisor agent](./docs/architecture/supervisor-agent.md), [memory](./docs/architecture/memory.md), and [deployment](./docs/architecture/deployment.md).
- **Pipeline:** The [pipeline README](./pipeline/README.md) covers the stages, Bedrock structured output, and dataset sizes.
- **Supervisor agent:** The [supervisor agent README](./supervisor-agent/README.md) covers routing, the graph tools, the secrets, and cloud deployment.
- **Browser UI:** The [UI README](./ui/README.md) covers the build and the evidence graph.
- **Test plan:** The [end-to-end test plan](./docs/e2e-test-plan.md) holds the test steps and the recorded runs.
