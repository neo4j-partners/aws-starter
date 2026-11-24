# Supervisor Agent Architecture

A question such as "Do the aircraft with the most faults also have the most
delays?" spans two domains. Maintenance knowledge covers faults, components,
and sensors. Operations knowledge covers flights, delays, and routes. One
prompt that holds both domains grows long and blurs which parts of the graph
matter. The supervisor agent in [`supervisor-agent/`](../../supervisor-agent/)
gives each domain its own specialist agent and lets a supervisor model decide
which ones to ask. The specialists read the fleet graph directly with the
Neo4j Python driver over Bolt.

![The supervisor routes each question to one or both specialists. Both specialists use graph_query_tool, which runs Text2Cypher over the live schema. Only the Maintenance specialist uses vector_search_tool, which runs hybrid vector and fulltext search over the manual chunks.](../images/supervisor-request-flow.svg)

## Routing

The supervisor is a Strands agent with two tools, `maintenance_specialist`
and `operations_specialist`. The supervisor model reads the two tool
descriptions and picks one, both, or neither. No separate classifier runs.

| Specialist | Description covers | Example questions |
|------------|--------------------|-------------------|
| Maintenance | Maintenance events, faults, components, systems, sensors, severity, and the maintenance manuals | "Most common maintenance faults", "Hydraulic leak detection procedure" |
| Operations | Flights, delays, routes, airports, operators, and schedules, plus the graph schema and simple counts | "Common delay causes", "Busiest routes" |

When the supervisor calls both tools in one turn, Strands runs the calls
concurrently. The supervisor then writes the final answer from both results.

### A fresh specialist per call

`SpecialistTool` in `core/agents.py` builds a new specialist `Agent` on each
call and runs it through `Agent.as_tool`. `Agent.as_tool` holds a lock while
the agent runs and fails a second call with "already processing a request".
The supervisor can call the same specialist twice in one turn, so a shared
specialist would refuse the second call. A fresh agent per call keeps
parallel calls and concurrent requests apart, at the cost of a short build on
each call.

## The graph tools

The two specialists differ in their tools. The `core/graph/` package exports
`MAINTENANCE_TOOLS` and `OPERATIONS_TOOLS`.

| Specialist | Tools |
|------------|-------|
| Maintenance | `graph_query_tool` and `vector_search_tool` |
| Operations | `graph_query_tool` |

The Maintenance model picks a tool from the two tool descriptions. Each
description names the other tool for the questions it does not handle, so
the choice follows the question's shape.

- **Graph query:** `graph_query_tool(question)` answers exact lookups, counts, aggregations, and traversals. It hands the question to a Text2Cypher retriever from `neo4j-graphrag`, which asks Claude Sonnet 5.5 for Cypher against the live schema and runs it. The Maintenance prompt sends operating limit values here, to the graph's `OperatingLimit` nodes.
- **Vector search:** `vector_search_tool(query, top_k=5, aircraft_type=None)` answers descriptive questions over the manual chunks. `top_k` runs from 1 to 20. With `aircraft_type` set, it searches only that type's manual. For limits it is the fallback when the graph has none.

The tools share one driver per process. It is a connection pool, created on
first use. The login comes from `core/secrets.py`, which reads
`NEO4J_PASSWORD_SECRET_ARN` when it is set and `NEO4J_USERNAME` and
`NEO4J_PASSWORD` otherwise. When Neo4j rejects the login as `Unauthorized`,
`retry_on_rotated_login` in `core/graph/retrieval.py` has the driver's
`RotatingLoginAuthManager` read the login again. The tool runs once more
only when the login changed. `graph_query_tool` then asks Claude for the
Cypher again, so the second query can differ. `vector_search_tool` reuses
the embedding it already made. A rotated password then recovers in the same
request, and a wrong password fails at once.

![A sequence for one question. Claude picks the Maintenance specialist. The specialist calls graph_query_tool in a loop. The tool asks Claude for Cypher, checks it with EXPLAIN, and runs it read-only against Neo4j. The answer streams back to the user as SSE events.](../images/end-to-end-sequence.svg)

The sequence above follows one question from the user to Neo4j and back.

1. **Route:** Claude on Bedrock reads the supervisor prompt and the two specialist tool specs, then calls `maintenance_specialist`.
2. **Build the specialist:** The supervisor builds a new Maintenance Agent for this call. The specialist sends its own prompt, with the schema, and the question to Claude.
3. **Tool loop:** Claude calls `graph_query_tool`. The tool asks Claude for Cypher, checks the query with `EXPLAIN`, and runs it read-only on Neo4j. The loop repeats until Claude has an answer.
4. **Answer:** The specialist's answer returns to the supervisor as a tool result. Claude writes the final answer, and the server streams it to the user as server-sent events.

### Hybrid search

The vector search tool uses `HybridCypherRetriever` over two indexes that the
pipeline builds on `Chunk` nodes. The `maintenanceChunkEmbeddings` vector index
matches meaning. The `maintenanceChunkText` fulltext index matches exact terms
such as part numbers and sensor names, which embeddings tend to blur.

The fulltext index parses its input as Lucene syntax, and a question such as
"Is A320-200 EGT/N1 OK?" contains Lucene operators. `fulltext_query()` reduces
the text to lowercase word tokens before the search, so no question can break
the query. The vector side embeds the original question with Titan Text
Embeddings v2. That embedder must match the one the pipeline used.

Each hit then runs `CHUNK_RETRIEVAL_QUERY`. The query follows `FROM_DOCUMENT`
to the source manual and `FROM_CHUNK` back to the entities extracted from the
chunk, at most 10 per chunk. The tool result starts each chunk with its
document ID, aircraft type, and chunk number, followed by those entities. The
model can cite the source and see which faults or limits the chunk mentions.

## Schema in the prompt

Both specialist prompts hold the live Neo4j schema, so the model knows the
labels and relationship types before it writes a question for the graph query
tool. Each request reads the schema and formats it into the prompts. The
schema is cached for 600 seconds, and `SCHEMA_TTL_S` changes that. The TTL
lets a running server pick up a pipeline reload without a restart.

The graph query tool passes the current cached schema on every call, so a
refresh reaches the Cypher prompt without rebuilding the retriever. The
Bedrock prompt cache misses once after each refresh, because the specialist
system prompts change.

## The read-only guard

The model writes the Cypher, so one bad query could write to the graph, scan
the whole graph, or return millions of rows. `BoundedText2CypherRetriever` in
`core/graph/text2cypher.py` closes all three.

1. **Plan first:** The retriever runs `EXPLAIN` on the generated query. `EXPLAIN` plans the query without running it. The retriever refuses any query whose `query_type` is not `READ_ONLY_QUERY_TYPE`.
2. **Time limit:** Both the `EXPLAIN` and the real query run as a `neo4j.Query` with a server-side transaction timeout of 30 seconds. `TEXT2CYPHER_TIMEOUT_S` changes it.
3. **Row cap:** The retriever fetches `max_rows + 1` records and keeps `max_rows`. The default cap is 200, and `TEXT2CYPHER_MAX_ROWS` changes it. When the extra row arrives, the tool tells the model it saw only the first rows and should aggregate or filter.

Both queries use read routing. The class copies one method from
`neo4j-graphrag` 1.24.0 and changes only the timeouts and the bounded fetch. A
test fails if the upstream signature changes.

The deployed Runtime also logs in as a read-only Neo4j user, `fleet_reader`,
so the database refuses a write even if a query passes the guard. The
[supervisor README](../../supervisor-agent/README.md#create-the-secrets)
shows how to create that user.

## Errors the model sees

Strands sends a tool's exception text to the model, and a driver message can
name the server address. The tools in `core/graph/tools.py` replace that text
with fixed results and log the details. `core/graph/neo4j_errors.py`
classifies the driver errors.

| Failure | Result the model gets |
|---------|-----------------------|
| The generated Cypher fails, or the guard refuses a write | The Neo4j message or the refusal, cut to 500 characters, with a request to rephrase |
| The transaction times out | The query took too long, with a hint to narrow the question |
| Neo4j is unreachable, or the login fails | The graph database is unavailable right now |
| Any other Neo4j error | The graph database returned an error |
| Any other failure, such as a Bedrock error | The query or search could not be run |

A failed Cypher query keeps its message because the model can use it to fix
the next attempt. The other failures carry nothing the model can act on. A
specialist that fails outright returns a generic error to the supervisor
model, and the details go to the server log.

## Streaming

The server is a `BedrockAgentCoreApp` that streams server-sent events.

- **`agent`:** The server emits one `agent` event when the supervisor calls a specialist.
- **`tool`:** The server emits one `tool` event when a specialist calls a graph tool. Strands repeats a tool call on every input delta while the call is being assembled, so the server emits each `toolUseId` once.
- **`chunk`:** A `chunk` event carries text of the supervisor's answer.
- **`complete`:** The `complete` event ends a successful stream.
- **`error`:** An `error` event carries a generic message. The details go to the server log.

A payload with `"trace": true` adds a `call_id` and a `parent_id` to the
`agent` and `tool` events. It also adds a `tool_complete` event when a
specialist or graph tool call finishes. The [browser UI](../../ui/) uses the
trace to draw each tool call's evidence.

## Memory and serving

The supervisor keeps conversation memory in the memory database with a
`Neo4jSessionManager` per request. The specialists hold no memory.
[Memory](memory.md) covers the lifecycle, and [Deployment](deployment.md)
covers the Runtime deploy and the secret ARNs.

| Component | Technology |
|-----------|------------|
| Supervisor and specialists | Strands `Agent` on Claude Sonnet 5.5, with `MAX_TOKENS` 16000 and effort high |
| Specialists | Built per call and wrapped with `Agent.as_tool` |
| Prompt caching | `CacheConfig(strategy="auto")` on the system prompt and tool specs |
| Graph tools | Text2Cypher and hybrid search from `neo4j-graphrag`, over one Neo4j driver |
| Memory | `Neo4jSessionManager` from `neo4j_agent_memory` |
| Server | `BedrockAgentCoreApp` on port 7071 locally and 8080 on the Runtime |
| Tracing | AWS Distro for OpenTelemetry on the Runtime |

The [supervisor agent README](../../supervisor-agent/README.md) has the full
command list.
