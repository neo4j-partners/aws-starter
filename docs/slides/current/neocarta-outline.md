# Neocarta: A Semantic Map for Enterprise Data

Build the map in Neo4j, serve it to agents over MCP, keep the data where it lives.

An overview with optional technical details.

# Agents See Metadata in Pieces, Not as a Connected Map

- Schemas: Show which tables and columns exist.
- Business terms: Explain what the data means.
- Relationships: Show joins, lineage, and source locations.
- Query history: Shows how people use the data.

The problem: These facts live in separate systems. An agent must connect them before it can answer a business question.

# Neocarta Builds a Connected Map of Enterprise Metadata

Neocarta prepares metadata in four steps:

- Collect: Connectors read schemas, glossaries, semantic models, and query history.
- Normalize: Each source becomes a shared set of databases, schemas, tables, and columns.
- Connect: Neo4j links technical assets to business terms, joins, metrics, and usage.
- Enrich: Text indexes and embeddings make the graph searchable.

Data boundary: Only metadata enters Neo4j. Source data stays in its original system.

Neocarta is a Neo4j Labs project supported by the Neo4j field team. It is not a Neo4j product. Apache 2.0, Python 3.10 or higher.

# Neocarta Turns Metadata Into Context for Agents

At run time, Neocarta helps the agent understand where the answer lives.

- Ask: The user asks a business question.
- Search: The agent calls Neocarta through MCP.
- Resolve: Neocarta follows business terms, schemas, and relationships.
- Return: Neocarta provides the relevant tables, columns, values, and joins.

Neocarta's job: Return focused, connected context that grounds the next step.

# Agents Query the Data Through a Governed Tool

The agent uses Neocarta's context to build and run the query.

- Write: The agent uses the returned context to write a query.
- Check: The query tool applies access controls and validation.
- Execute: The query tool runs the query against the source system.
- Answer: The agent returns the result with the tables and query it used.

Clear ownership: Neocarta supplies context. The agent writes the query. The query tool controls and runs it.

# Neocarta Is the Context Layer in the Full Agent System

Neocarta sits between enterprise metadata sources and the agent layer. It owns metadata ingestion, the semantic map in Neo4j, and context retrieval. A separate query service provides access to source data. Feedback and memory return to the semantic layer.

# How Neocarta Works

Connect metadata, find the right assets, and serve trusted context.

# Seven Connectors Map Schemas and Structure

| Connector | Metadata source |
| --- | --- |
| BigQuery Schema | BigQuery information schema |
| Dataplex Schema | BigQuery assets cataloged in Dataplex |
| Snowflake Schema | Snowflake information schema |
| Databricks Schema | Managed Unity Catalog information schema |
| Unity Catalog Schema | Open Unity Catalog REST API |
| JDBC Schema | SchemaCrawler across JDBC databases |
| CSV | Curated metadata files |

One structural model: Each path produces databases, schemas, tables, columns, values, and known references where the source provides them.

# Six Connectors Add Context Beyond the Schema

| Context | Connectors | What they add |
| --- | --- | --- |
| Usage | BigQuery Logs, Snowflake Logs, Query Log | Queries, CTEs, and table or column usage |
| Governance | Dataplex Glossary, Databricks Tags | Business terms, asset mappings, and tag definitions |
| Semantics | OSI | Datasets, fields, metrics, joins, and AI context |

Thirteen source connectors, one graph: OSI is bidirectional; the other source connectors ingest metadata into Neo4j.

# Embeddings Add Semantic Search After Ingestion

Graph descriptions flow to an embedding provider, then to vector properties and indexes.

| Enrichment path | Best fit |
| --- | --- |
| LiteLLM | Multiple providers, including Bedrock, OpenAI, Azure OpenAI, Gemini, Cohere, and Vertex AI |
| OpenAI SDK | Direct client control, custom endpoints, retries, proxies, and explicit dimensions |

- Targets: Database, Schema, Table, Column, and BusinessTerm descriptions.
- Incremental: Processes only nodes that do not already have an embedding.
- Result: Enables vector and hybrid retrieval over the metadata graph.

Enrichment, not ingestion: Run embeddings after the source connectors have populated Neo4j.

# Agents Can Find a Table in Five Ways

The MCP server supports simple browsing and several kinds of search.

- Catalog browsing: Lists schemas and tables so the agent can see what exists.
- Full-text search: Finds exact names and words in descriptions.
- Vector search: Finds similar meaning when the words differ.
- Hybrid search: Combines full-text and vector results.
- Glossary bridge: Connects governed business terms to the assets that implement them.

Table and column search: Each method can find a table or a specific column.

# The MCP Server Offers Only Tools the Graph Can Support

1. Server starts.
2. Checks the graph for indexes and business terms.
3. Selects the best available search method.
4. Shows the agent only tools that will work.

- With business terms: Offer glossary-based hybrid search.
- With text and vector indexes: Offer hybrid search.
- With one index: Offer full-text or vector search.
- With no search index: Offer catalog browsing.

Result: The agent sees a smaller tool list and avoids calls the graph cannot support.

# Governance Keeps Retrieved Context Trustworthy

Trusted retrieval requires clear checks and clear owners.

- Automated checks: Test retrieval quality and query validity.
- User feedback: Record approvals, corrections, and outcomes.
- Expert review: Confirm mappings, metrics, and query paths.
- Traceability: Keep context, queries, and evidence.
- Authority: Use approved definitions for high-risk decisions.

Why it matters: Metadata changes. Named owners keep the map current.

# How a Business Term Resolves to a Real Column

"largest orders" resolves through a BusinessTerm to a Column, then to its Table, Schema, and Database. The column's `REFERENCES` relationship identifies the join.

- Built from: The connectors load catalog metadata, glossary terms, semantic models, and query history into one graph.
- What the agent gets back: The traversal returns the exact column, its table and platform, sample values, and the foreign keys needed to join.
- Why a graph: Every step is a stored relationship, so the agent can show which glossary entry led it to that column.

Candidates versus a query plan: Embedding search ranks table names and hands back a confidence number. The traversal hands back the column, the join, and the reason it was chosen.

# A Grounded Text-to-Query Flow: Who Does What

For the question, "Which customers placed the largest orders last quarter?":

1. The agent calls one Neocarta retrieval tool.
2. Neocarta returns orders and customers, with columns, types, sample values, and `orders.customer_id -> customers.id`.
3. The agent LLM writes the SQL, using that reference as the join.
4. The query tool runs the SQL against BigQuery.
5. The agent answers, citing the tables and the query it ran.

Where the join comes from: `REFERENCES` is already in the graph, so the foreign key arrives in the first retrieval result. Neocarta supplies the schema and never writes or runs SQL.

# Metadata Model and Connectors

How metadata is represented, extended, and brought into the graph.

# The Core Metadata Model

Database has schemas; schemas have tables; tables have columns; columns have example values and `REFERENCES` relationships to other columns.

- Every connector converts to this shape. That is the contract.
- `REFERENCES` carries the foreign key, so joins are traversable.
- `Value` holds example values, which ground SQL generation.

# The Glossary Extension Bridges Business Language

A Glossary has Categories; Categories have BusinessTerms; Tables and Columns are `TAGGED_WITH` BusinessTerms.

- `BusinessTerm` merges on name, so catalog and OSI sources collide cleanly.
- `TAGGED_WITH` is the bridge from vocabulary to physical asset.
- Business-term hybrid search traverses this edge, not just the index.

# Query Logs and Semantic Models Extend the Same Model

Usage knowledge:

- A Query `USES_TABLE` a Table and `USES_COLUMN` a Column.
- CTEs capture real queries, real joins, and real access paths.

Governed semantics:

- OSI models include OsiSemanticModel, OsiTable, OsiColumn, Metric, Expression, Join, and OsiAiContext.
- Open Semantic Interchange is bidirectional.

OSI is the only bidirectional connector: It ingests a YAML spec and exports a semantic model subgraph back to spec-compliant YAML.

# Every Connector Decomposes the Same Way

Source-system metadata flows through an Extractor, Transformer, and Loader into the Neo4j graph.

- Extractors connect to the source and read its metadata.
- Transformers validate and convert to the shared model.
- Loaders write indexed nodes and relationships.
- Connectors orchestrate the three as one class.

Optional accelerator: `neocarta[performance]` swaps in neo4j-rust-ext for 60 to 90 percent faster bulk loads. Requires Python 3.11 or higher.

# The Connector Contract

```bash
# List connectors and their detected kind
make connectors-list

# Scaffold a new source connector plus a conformance test
make connector-new NAME=glue

# Verify a connector against the contract
make connector-verify NAME=glue
```

- New platforms contribute metadata without changing agent behavior.
- A conformance test ships with the scaffold, not after the fact.
- Static checks plus pytest enforce the shared model.

# Retrieval, Reuse, and Adoption

What the agent receives, what the system can retain, and how to start.

# What a Retrieval Result Contains

Example result for `ecommerce.orders`:

| Column | Type | Detail |
| --- | --- | --- |
| `order_id` | INT64 | Primary key; examples: 1001, 1002 |
| `customer_id` | INT64 | Foreign key to `customers.id` |
| `total_amount` | NUMERIC | Examples: 49.99, 128.50 |
| `status` | STRING | Examples: shipped, cancelled |

- Types let the agent cast and compare correctly.
- Example values stop the agent guessing at enum spellings.
- Foreign keys are the difference between a list and a query plan.

# From Query Logs to Process Paths

Ships today:

- A Query `USES_TABLE` a Table and `USES_COLUMN` a Column.
- This shows which assets a query touched.

The next step:

- Capture the whole path: Question, selected concepts, source choice, generated query, evidence, and result.

The shift: Query logs record what happened. A process path records why, so a later agent can reuse the reasoning rather than rediscover it.

# Reuse and Its Boundary

- Find similar requests and start from a path that worked.
- Attach signals: quality, latency, cost, and user feedback.
- Preserve rejected paths with the reason they were rejected.
- The boundary: A reused path is a starting point, not an answer.

Why keep failures: A path that was rejected for a stated reason stops the next agent repeating the mistake. Deleting it guarantees the mistake recurs.

# Start With One Governed Question

1. Choose one business question that spans several related tables.
2. Connect source schema, glossary terms, and representative query history.
3. Map the highest-value links between business terms and physical assets.
4. Serve focused context through the Neocarta MCP server.
5. Execute through one governed query tool with real access controls.
6. Measure retrieval relevance, SQL correctness, answer quality, and cost.
7. Expand once the first workflow has proven itself.

Why one question: A whole-catalog ingest produces a large graph and no evidence. One question end to end produces a working path and a number you can defend.
