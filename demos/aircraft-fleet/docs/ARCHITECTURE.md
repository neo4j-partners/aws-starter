# Aircraft Fleet Architecture

A maintenance question about one aircraft needs three things at once. It needs
the sensor history of that aircraft, the faults logged against its parts, and
the limit that the maintenance manual sets for each sensor. The fleet records
live in rows and the limits live in prose. This demo puts both into one Neo4j
graph, links them, and answers questions over that graph with one supervisor
agent and two specialists.

![The pipeline builds the Neo4j fleet graph. One supervisor routes each question to a Maintenance or Operations specialist. The specialists read the graph directly with the Neo4j driver. The supervisor keeps conversation memory in a separate Neo4j database. The browser UI relays the supervisor's stream and looks up each tool call's evidence in the fleet graph.](images/architecture.svg)

## Components

- **Pipeline:** The [`pipeline/`](../pipeline/) project builds the fleet graph in five stages. It generates a synthetic fleet, loads it, extracts knowledge from the manuals with Bedrock, links the two graphs, and verifies the result. It is the only component that writes the fleet graph.
- **Supervisor agent:** The [`supervisor-agent/`](../supervisor-agent/) project is a Strands supervisor with two specialist agents as its tools. The Maintenance specialist writes Cypher from the live schema and runs hybrid search over the manual chunks. The Operations specialist writes Cypher only.
- **Graph access:** The specialists reach Neo4j with the Neo4j Python driver over Bolt. On the Runtime, they log in as a read-only user whose password comes from Secrets Manager.
- **Browser UI:** The [`ui/`](../ui/) project shows the supervisor's answer, the specialist and tool calls, and the graph evidence for each call.
- **Memory:** The supervisor keeps conversation memory with Neo4j Agent Memory in a second Neo4j database.

## Read-only by two guards

The model writes the Cypher, so the read path has two guards.

- **Query check:** Each generated query runs `EXPLAIN` first, and the tool refuses any query that is not read-only. Each query also gets a 30-second timeout and a 200-row cap.
- **Database user:** The deployed Runtime logs in as `fleet_reader`, which holds only read roles. The database refuses a write even if a query passes the check.

The [supervisor architecture](architecture/supervisor-agent.md#the-read-only-guard)
covers the check.

## Two databases

- **Fleet graph:** The fleet graph holds the operational graph from the generated CSVs and the knowledge graph extracted from the manuals. The pipeline writes it. The supervisor and the UI only read it.
- **Memory database:** The memory database holds sessions, messages, extracted entities, and user preferences for the supervisor. It stays apart from the fleet graph, because memory labels in the fleet graph would reach the Text2Cypher schema prompt.

## Models

| Model | Used by |
|-------|---------|
| Claude Sonnet 5.5, `global.anthropic.claude-sonnet-5-5` | Pipeline extraction, the supervisor and specialist loops, Text2Cypher, and memory extraction |
| Amazon Titan Text Embeddings v2, 1024 dimensions | Chunk embeddings, query embeddings, and memory embeddings |

The pipeline and the supervisor's vector search must use the same embedder. A
mismatch makes vector search return poor results or nothing.

## Detail by part

| Document | Covers |
|----------|--------|
| [Pipeline](architecture/pipeline.md) | The generator, the data model, manual enrichment, fusion, indexes, and verify |
| [Supervisor agent](architecture/supervisor-agent.md) | Routing, specialists, the graph tools, the schema cache, the read-only guard, errors, and streaming |
| [Memory](architecture/memory.md) | The shared client, per-request managers, deferred extraction, the retrieval threshold, and shutdown |
| [Deployment](architecture/deployment.md) | The one stack, the secrets, the deploy order, and teardown |

## Diagrams

All diagrams are SVG files in [`images/`](images/).

| Diagram | Shows |
|---------|-------|
| [`architecture.svg`](images/architecture.svg) | The pipeline, the supervisor and its specialists, the browser UI, and the two databases |
| [`pipeline-flow.svg`](images/pipeline-flow.svg) | The five pipeline stages and what each one writes |
| [`generator-flow.svg`](images/generator-flow.svg) | How `generate-data` builds one dataset from one seed |
| [`data-model.svg`](images/data-model.svg) | The operational graph's labels and relationships |
| [`dual-graph.svg`](images/dual-graph.svg) | The operational graph, the knowledge graph, and the links between them |
| [`supervisor-request-flow.svg`](images/supervisor-request-flow.svg) | One request through the supervisor, a specialist, and its graph tools |
| [`end-to-end-sequence.svg`](images/end-to-end-sequence.svg) | One question through the Maintenance specialist, Text2Cypher, and Neo4j |
| [`memory-lifecycle.svg`](images/memory-lifecycle.svg) | How the supervisor opens, uses, and closes conversation memory |
| [`deployment-topology.svg`](images/deployment-topology.svg) | The one stack, the AWS services, and the two Neo4j databases |
