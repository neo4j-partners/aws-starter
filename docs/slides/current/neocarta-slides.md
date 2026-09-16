---
marp: true
theme: default
paginate: true
---

<style>
section {
  --marp-auto-scaling-code: false;
  color: #0f172a;
  font-size: 26px;
  padding: 48px 64px;
}

h1 {
  color: #0f172a;
  font-size: 52px;
}

h2 {
  color: #0f172a;
  font-size: 37px;
  margin-bottom: 18px;
}

h3 {
  color: #0f766e;
  font-size: 26px;
}

table {
  font-size: 21px;
  width: 100%;
}

th {
  background: #e2e8f0;
}

td, th {
  padding: 9px 13px;
}

code {
  font-size: 21px;
}

small {
  color: #64748b;
  font-size: 13px;
}

section.lead {
  background: linear-gradient(135deg, #f8fafc 0%, #ecfeff 100%);
}

section.lead h1 {
  font-size: 58px;
  max-width: 1050px;
}

section.lead h2 {
  color: #0f766e;
  font-size: 29px;
  font-weight: 500;
  max-width: 980px;
}

.promise {
  color: #475569;
  font-size: 21px;
  margin-top: 72px;
}

.callout {
  background: #ecfeff;
  border-left: 6px solid #14b8a6;
  margin-top: 18px;
  padding: 12px 18px;
}

.status-now {
  color: #047857;
  font-weight: 700;
}

.status-preview {
  color: #a16207;
  font-weight: 700;
}

.status-roadmap {
  color: #7c3aed;
  font-weight: 700;
}

.cols {
  display: grid;
  gap: 30px;
  grid-template-columns: 1fr 1fr;
}

.center {
  text-align: center;
}

.tight li {
  margin: 6px 0;
}

li {
  opacity: 1 !important;
  visibility: visible !important;
}

section.section {
  background: linear-gradient(135deg, #0f172a 0%, #134e4a 100%);
}

section.section h1 {
  color: #f8fafc;
  font-size: 44px;
  max-width: 980px;
}

section.section h2 {
  color: #5eead4;
  font-size: 25px;
  font-weight: 500;
  max-width: 940px;
}

</style>

<!-- _class: lead -->

# Neocarta: A Semantic Map for Enterprise Data

## Build the map in Neo4j, serve it to agents over MCP, keep the data where it lives

<div class="promise">An overview with optional technical details</div>

<!--
Neocarta is an experimental Neo4j Labs Python library. It builds a
semantic layer in Neo4j from your data sources and serves it to agents
through an MCP server.

Two things to set up front. First, only metadata crosses into Neo4j.
Source data stays in its platform. Second, Neocarta does not run your
queries. It gives an agent the context to write one, and a separate
database tool executes it. That boundary is the whole design.

Deck structure: a core overview, three technical sections, and a close.
-->

---

## Agents See Metadata in Pieces, Not as a Connected Map

- **Schemas:** Show which tables and columns exist
- **Business terms:** Explain what the data means
- **Relationships:** Show joins, lineage, and source locations
- **Query history:** Shows how people use the data

<div class="callout"><strong>The problem:</strong> These facts live in separate systems. An agent must connect them before it can answer a business question.</div>

<!--
Give an agent raw schema access and it still cannot answer a business
question reliably.

The metadata it needs is split across systems. Schemas show structure.
Glossaries explain business language. Relationships show joins and
lineage. Query history shows how people use the data. An agent needs all
four kinds of context, connected around the same assets.

This is a retrieval problem, not a context-window problem.
-->

---

## Neocarta Builds a Connected Map of Enterprise Metadata

Neocarta prepares metadata in four steps:

- **Collect:** Connectors read schemas, glossaries, semantic models, and query history
- **Normalize:** Each source becomes a shared set of databases, schemas, tables, and columns
- **Connect:** Neo4j links technical assets to business terms, joins, metrics, and usage
- **Enrich:** Text indexes and embeddings make the graph searchable

<div class="callout"><strong>Data boundary:</strong> Only metadata enters Neo4j. Source data stays in its original system.</div>

<small>Neocarta is a Neo4j Labs project supported by the Neo4j field team. It is not a Neo4j product. Apache 2.0, Python 3.10 or higher.</small>

<!--
Neocarta first builds the map that agents will use.

Connectors collect metadata from source systems. Neocarta normalizes each
source into a shared model, connects related facts in Neo4j, and adds the
indexes and embeddings needed for search.

Only metadata enters Neo4j. The source data remains in its original system.
-->

---

## Neocarta Turns Metadata Into Context for Agents

At run time, Neocarta helps the agent understand where the answer lives.

- **Ask:** The user asks a business question
- **Search:** The agent calls Neocarta through MCP
- **Resolve:** Neocarta follows business terms, schemas, and relationships
- **Return:** Neocarta provides the relevant tables, columns, values, and joins

<div class="callout"><strong>Neocarta's job:</strong> Return focused, connected context that grounds the next step.</div>

<!--
The first run-time step is finding the right data.

The user asks a business question. The agent calls Neocarta through MCP.
Neocarta searches the graph and follows the relationships between business
terms, tables, columns, and joins.

The result is a focused set of context that tells the agent where the answer
lives and how the relevant assets connect.
-->

---

## Agents Query the Data Through a Governed Tool

The agent uses Neocarta's context to build and run the query.

- **Write:** The agent uses the returned context to write a query
- **Check:** The query tool applies access controls and validation
- **Execute:** The query tool runs the query against the source system
- **Answer:** The agent returns the result with the tables and query it used

<div class="callout"><strong>Clear ownership:</strong> Neocarta supplies context. The agent writes the query. The query tool controls and runs it.</div>

<!--
The next step is querying the source data.

The agent uses the tables, columns, values, and joins returned by Neocarta to
write a query. A separate governed tool checks access and validates the query
before running it against the source system.

The agent then returns the answer with the tables and query it used. Neocarta
never enters the execution path.
-->

---

## Neocarta Is the Context Layer in the Full Agent System

![w:1150](./neocarta.svg)

<!--
This diagram places Neocarta inside the larger agent system.

Data sources are on the left. They include ontologies, documents, query
logs, catalogs, databases, lakes, and warehouses.

They feed a semantic layer in Neo4j, in the middle. That is the map.

The context MCP service retrieves metadata from the map. A separate query
service provides the path to the source data.

Then the agent layer, the consumption layer, and the user.

And the arc across the top: feedback and memory returning to the semantic
layer, so what an investigation learns is not thrown away.

Neocarta owns metadata ingestion, the semantic map, and context retrieval.
The agent, query service, and user interface are parts of the larger system.
-->

---

<!-- _class: section -->

# How Neocarta Works

## Connect metadata, find the right assets, and serve trusted context

<!--
The next six slides give the core overview.

First, seven connectors bring schemas and curated structural metadata into
the graph. Six more add usage, governance, and semantic context. Embeddings
then enrich selected graph descriptions for semantic search. Retrieval tools
find the right assets, the MCP server exposes only the tools the graph can
support, and governance keeps the returned context current and trusted.
-->

---

## Seven Connectors Map Schemas and Structure

| Connector | Metadata source |
| --- | --- |
| **BigQuery Schema** | BigQuery information schema |
| **Dataplex Schema** | BigQuery assets cataloged in Dataplex |
| **Snowflake Schema** | Snowflake information schema |
| **Databricks Schema** | Managed Unity Catalog information schema |
| **Unity Catalog Schema** | Open Unity Catalog REST API |
| **JDBC Schema** | SchemaCrawler across JDBC databases |
| **CSV** | Curated metadata files |

<div class="callout"><strong>One structural model:</strong> Each path produces databases, schemas, tables, columns, values, and known references where the source provides them.</div>

<!--
The first seven connectors bring technical structure into the graph.

Five read platform catalogs directly: BigQuery, Dataplex, Snowflake,
managed Databricks Unity Catalog, and the open Unity Catalog API.

JDBC uses SchemaCrawler to cover databases with a JDBC driver. CSV is the
portable path for curated or exported metadata when there is no direct API.

They all normalize what they find into the same structural model. The exact
detail depends on the source: some expose keys, sample values, and references;
others expose only the catalog hierarchy.
-->

---

## Six Connectors Add Context Beyond the Schema

| Context | Connectors | What they add |
| --- | --- | --- |
| **Usage** | BigQuery Logs, Snowflake Logs, Query Log | Queries, CTEs, and table or column usage |
| **Governance** | Dataplex Glossary, Databricks Tags | Business terms, asset mappings, and tag definitions |
| **Semantics** | OSI | Datasets, fields, metrics, joins, and AI context |

<div class="callout"><strong>Thirteen source connectors, one graph:</strong> OSI is bidirectional; the other source connectors ingest metadata into Neo4j.</div>

<!--
These six connectors add the context that makes a schema useful to an agent.

The three usage connectors capture query history and record which tables and
columns real queries use. Dataplex Glossary links governed business terms to
assets. Databricks Tags brings governed-tag definitions into the graph.

OSI contributes a governed semantic model: datasets, fields, metrics,
expressions, joins, and AI context. It is the only bidirectional source
connector, so it can also export a model from Neo4j back to OSI YAML.

Together with the seven structural connectors, that makes thirteen source
connectors. All thirteen bring source metadata into the shared graph model.
-->

---

## Embeddings Add Semantic Search After Ingestion

```text
graph descriptions  ->  embedding provider  ->  vector properties + indexes
```

| Enrichment path | Best fit |
| --- | --- |
| **LiteLLM** | Multiple providers, including Bedrock, OpenAI, Azure OpenAI, Gemini, Cohere, and Vertex AI |
| **OpenAI SDK** | Direct client control, custom endpoints, retries, proxies, and explicit dimensions |

- **Targets:** Database, Schema, Table, Column, and BusinessTerm descriptions
- **Incremental:** Processes only nodes that do not already have an embedding
- **Result:** Enables vector and hybrid retrieval over the metadata graph

<div class="callout"><strong>Enrichment, not ingestion:</strong> Run embeddings after the source connectors have populated Neo4j.</div>

<!--
Embeddings are a separate step after source ingestion.

The enrichment reads descriptions already stored on graph nodes, sends them
to an embedding provider, writes the vectors back to Neo4j, and creates a
cosine-similarity vector index for each selected label.

LiteLLM is the flexible path across providers such as Bedrock, OpenAI, Azure
OpenAI, Gemini, Cohere, and Vertex AI. The direct OpenAI implementation is for
applications that already own an OpenAI client or need explicit control over
dimensions, endpoints, retries, or proxies.

The process is incremental. Nodes that already have an embedding are skipped.
This enrichment enables vector and hybrid retrieval; it does not ingest a new
data source or change the shared metadata model.
-->

---

## Agents Can Find a Table in Five Ways

The MCP server supports simple browsing and several kinds of search.

- **Catalog browsing:** Lists schemas and tables so the agent can see what exists
- **Full-text search:** Finds exact names and words in descriptions
- **Vector search:** Finds similar meaning when the words differ
- **Hybrid search:** Combines full-text and vector results
- **Glossary bridge:** Connects governed business terms to the assets that implement them

<div class="callout"><strong>Table and column search:</strong> Each method can find a table or a specific column.</div>

<!--
Agents can find data in five ways.

Catalog browsing provides orientation. Full-text search matches exact
names and description terms. Vector search matches similar meaning.
Hybrid search combines both signals. The glossary bridge connects governed
business language to the physical tables and columns that implement it.

The methods work at table and column level. This lets the agent use the
method that fits the question and the indexes available in the graph.
-->

---

## The MCP Server Offers Only Tools the Graph Can Support

```text
Server starts
      |
      v
Checks the graph for indexes and business terms
      |
      v
Selects the best available search method
      |
      v
Shows the agent only tools that will work
```

- **With business terms:** Offer glossary-based hybrid search
- **With text and vector indexes:** Offer hybrid search
- **With one index:** Offer full-text or vector search
- **With no search index:** Offer catalog browsing

<div class="callout"><strong>Result:</strong> The agent sees a smaller tool list and avoids calls the graph cannot support.</div>

<!--
The MCP server checks the graph when it starts.

It looks for search indexes and business terms. It then registers the best
search tool each label can support. Business-term hybrid search has the
highest priority, followed by hybrid search, then one search method on its
own. Catalog browsing remains available without search indexes.

The agent sees only tools that will work against the current graph. This
removes a common source of failed tool calls.
-->

---

## Governance Keeps Retrieved Context Trustworthy

Trusted retrieval requires clear checks and clear owners.

- **Automated checks:** Test retrieval quality and query validity
- **User feedback:** Record approvals, corrections, and outcomes
- **Expert review:** Confirm mappings, metrics, and query paths
- **Traceability:** Keep context, queries, and evidence
- **Authority:** Use approved definitions for high-risk decisions

<div class="callout"><strong>Why it matters:</strong> Metadata changes. Named owners keep the map current.</div>

<!--
Governance keeps the semantic map useful over time.

Automated evaluation measures retrieval quality, query validity, and
performance. User feedback records approvals and corrections. Data
stewards review important mappings, metric definitions, and query paths.

Traceability preserves the evidence behind each answer. Expert-approved
definitions provide the final authority for high-risk decisions.
-->

---

## How a Business Term Resolves to a Real Column

```text
"largest orders"
     |
     v
(BusinessTerm) -> (Column) -> (Table) -> (Schema) -> (Database)
                      |
                      +-[:REFERENCES]-> (Column)   the join
```

- **Built from:** The connectors load catalog metadata, glossary terms, semantic models, and query history into one graph.
- **What the agent gets back:** The traversal returns the exact column, its table and platform, sample values, and the foreign keys needed to join.
- **Why a graph:** Every step is a stored relationship, so the agent can show which glossary entry led it to that column.

<div class="callout"><strong>Candidates versus a query plan:</strong> Embedding search ranks table names and hands back a confidence number. The traversal hands back the column, the join, and the reason it was chosen.</div>

<!--
One traversal is the reading of that picture.

Somebody says "largest orders." That phrase is a business term. The term
is tagged to a column. The column belongs to a table, the table sits in a
schema, the schema lives in a database. And the column carries a
REFERENCES edge to the column it joins against.

So the traversal does not just narrow the search. It ends with everything
needed to write the query: the exact column, the platform it lives on,
what the values look like, and the join key.

Two things are worth pulling out of that.

First, every step is a stored relationship. Somebody's glossary said this
term maps to this column, and the connector recorded it. The agent is
reading facts, not inferring them, and it can show you the path it took.

Second, compare that to embedding your table descriptions and returning
the top five by cosine similarity. You get candidates and a confidence
number. That is not enough to write SQL. It does not give you the column,
it does not give you the join, and it cannot tell you that two catalogs
use the same term for different things.

Candidates versus a query plan. That is the whole argument for a graph
rather than a vector index.

ARTWORK NOTE: replace the previous slide's diagram with the three-state
graph model SVG when built, and highlight this path on it.
-->

---

## A Grounded Text-to-Query Flow: Who Does What

```text
"Which customers placed the largest orders last quarter?"
      v
[agent]       calls one Neocarta retrieval tool
      v
[Neocarta]    returns orders and customers, with columns, types,
              sample values, and orders.customer_id -> customers.id
      v
[agent LLM]   writes the SQL, using that reference as the JOIN
      v
[query tool]  runs the SQL against BigQuery
      v
[agent]       answers, citing the tables and the query it ran
```

<div class="callout"><strong>Where the join comes from:</strong> <code>REFERENCES</code> is already in the graph, so the foreign key arrives in the first retrieval result. Neocarta supplies the schema and never writes or runs SQL.</div>

<!--
One request, end to end, and the point of this slide is who is doing each
step. Neocarta appears exactly once.

The agent makes one retrieval call with the question. Neocarta answers
with the orders and customers tables: their columns, types, sample values,
and the foreign key between them.

That foreign key is worth stopping on, because people assume it is a
second call. It is not. REFERENCES is already a relationship in the graph,
loaded by the connector when it read the source catalog. So the join
arrives in the same result as the schema, and the agent never has to
infer it or ask again.

Then Neocarta is done. The agent's own LLM writes the SQL. Neocarta does
not generate SQL, and it does not have an opinion about the SQL. It
supplied real column names and a real join key, which is what keeps the
generated query grounded.

A separate tool executes it. In the runnable example in the repo that is
a BigQuery query tool, driven by LangGraph.

The answer comes back citing the tables and the query, so it is traceable.

That division is the whole architecture: Neocarta describes, the LLM
composes, a governed tool executes.
-->

---

<!-- _class: section -->

# Metadata Model and Connectors

## How metadata is represented, extended, and brought into the graph

<!--
This section opens the hood on the graph, then connects the shared model to
the contract every source connector implements.
-->

---

## The Core Metadata Model

```text
(Database) -[:HAS_SCHEMA]-> (Schema) -[:HAS_TABLE]-> (Table)
                                                        |
                                              [:HAS_COLUMN]
                                                        v
                          (Value) <-[:HAS_VALUE]- (Column)
                                                        |
                                              [:REFERENCES]
                                                        v
                                                   (Column)
```

- **Every connector converts to this shape.** That is the contract
- **`REFERENCES`** carries the foreign key, so joins are traversable
- **`Value`** holds example values, which ground SQL generation

<!--
Five node labels, five relationship types. That is the whole core model.

Database, Schema, Table, Column, and Value, with a hierarchy running down
through them.

Two relationships do the real work. REFERENCES connects a foreign key
column to the column it points at, which is how an agent discovers a join
without guessing. And HAS_VALUE holds sample values, which is how the
agent knows that a status column contains 'cancelled' rather than 'CANCEL'.

The important property of this model is that it is shared. Every connector,
BigQuery or Snowflake or CSV, has to produce this shape. That is why one
MCP server works against all of them.

Database, Schema, Table, and Column all carry an optional embedding
property for vector search.
-->

---

## The Glossary Extension Bridges Business Language

```text
(Glossary) -[:HAS_CATEGORY]-> (Category) -[:HAS_BUSINESS_TERM]-> (BusinessTerm)
                                                                       ^
                                                            [:TAGGED_WITH]
                                                                       |
                                                          (Table) and (Column)
```

- **`BusinessTerm`** merges on name, so catalog and OSI sources collide cleanly
- **`TAGGED_WITH`** is the bridge from vocabulary to physical asset
- **Business-term hybrid search** traverses this edge, not just the index

<!--
This is where the business language lives.

The Dataplex connector brings glossaries, categories, and business terms
out of the catalog and links them to tables and columns with TAGGED_WITH.

One detail worth knowing: BusinessTerm nodes merge on name. So a term that
arrives from the Dataplex glossary and the same term arriving as a synonym
from an OSI semantic model land on the same node. Sources reinforce each
other instead of duplicating.

And this is what the business-term retrieval tools use. When the full-text
branch of a hybrid search is bridged through BusinessTerm, a question
phrased in business language reaches the physical column even when the
column name shares no words with the question. That is the case a plain
vector index over column names handles badly.
-->

---

## Query Logs and Semantic Models Extend the Same Model

<div class="cols">
<div>

**Usage knowledge**

```text
(Query) -[:USES_TABLE]->  (Table)
(Query) -[:USES_COLUMN]-> (Column)
(CTE)
```

Real queries, real joins, real access paths.

</div>
<div>

**Governed semantics**

```text
(OsiSemanticModel)
   -> (OsiTable) -> (OsiColumn)
   -> (Metric) -> (Expression)
   -> (Join)
   -> (OsiAiContext)
```

Open Semantic Interchange, bidirectional.

</div>
</div>

<div class="callout"><strong>OSI is the only bidirectional connector:</strong> It ingests a YAML spec and exports a semantic model subgraph back to spec-compliant YAML.</div>

<!--
Two extensions on the same core.

On the left, usage. The query log connectors parse SQL and record which
tables and columns each query touched, including through CTEs. That gives
you the access paths people actually use, which is a much better discovery
signal than the schema alone.

On the right, governed semantics through Open Semantic Interchange. OSI is
a YAML interchange format for semantic models. The connector brings in
datasets, fields, metrics with dialect-specific expressions, joins with
ordered column lists for composite keys, and AI context.

OSI is the only connector that goes both ways. You can ingest a spec, and
you can export a semantic model subgraph back out as compliant YAML with
column ordering preserved. So Neo4j can be the editing surface for a
semantic model that other tools consume.
-->

---

## Every Connector Decomposes the Same Way

```text
Source          Extractor      Transformer         Loader        Neo4j
system    -->   read raw  -->  validate with  -->  write    -->  graph
metadata        metadata       Pydantic            indexed
                                                   nodes
```

- **Extractors:** connect to the source and read its metadata
- **Transformers:** validate and convert to the shared model
- **Loaders:** write indexed nodes and relationships
- **Connectors:** orchestrate the three as one class

<div class="callout"><strong>Optional accelerator:</strong> <code>neocarta[performance]</code> swaps in neo4j-rust-ext for 60 to 90 percent faster bulk loads. Requires Python 3.11 or higher.</div>

<!--
Four components, one pattern, repeated for every source.

The extractor talks to the source. For BigQuery that means reading
INFORMATION_SCHEMA tables. For Dataplex it means the catalog API.

The transformer validates with Pydantic and converts to the shared graph
model. This is where the contract is enforced.

The loader writes indexed nodes and relationships.

And the connector class wraps all three, so from the outside you construct
one object and call ingest.

If you are loading a large schema, the performance extra is worth it. It
replaces the pure-Python serialization layer in the Neo4j driver with a
compiled Rust extension.
-->

---

## The Connector Contract

```bash
# List connectors and their detected kind
make connectors-list

# Scaffold a new source connector plus a conformance test
make connector-new NAME=glue

# Verify a connector against the contract
make connector-verify NAME=glue
```

- **New platforms contribute metadata** without changing agent behavior
- **Conformance test** ships with the scaffold, not after the fact
- **Static checks plus pytest** enforce the shared model

<!--
This is the part that makes the connector list a starting point rather
than a ceiling.

There is a scaffold command. It generates a connector package with the
extractor, transformer, and loader stubs, and a conformance test.

Then there is a verify command that runs static checks plus the
conformance pytest against the contract.

Why this matters for the audience: if your platform is not on the list,
the cost of adding it is a connector, not a fork. And because the contract
enforces the shared graph model, a new connector inherits every existing
retrieval tool. The MCP server does not know or care where the metadata
came from.

That is the argument for the shared model paying for itself.
-->

---
<!-- _class: section -->

# Retrieval, Reuse, and Adoption

## What the agent receives, what the system can retain, and how to start

<!--
This section follows retrieved context into a concrete result, shows how
query history can become reusable process knowledge, and closes with a
practical adoption path.
-->

---

## What a Retrieval Result Contains

```text
Table: ecommerce.orders
  Columns:
    order_id       INT64    PK    examples: 1001, 1002
    customer_id    INT64    FK -> customers.id
    total_amount   NUMERIC        examples: 49.99, 128.50
    status         STRING         examples: shipped, cancelled
```

- **Types** let the agent cast and compare correctly
- **Example values** stop the agent guessing at enum spellings
- **Foreign keys** are the difference between a list and a query plan

<!--
This is what comes back, and every part of it earns its place.

The table and its columns, obviously. Types, so the agent writes valid
comparisons instead of casting a string to a date and hoping.

Example values. This is underrated. An agent writing a filter on status
needs to know the value is 'cancelled', lowercase, not 'CANCELLED' or
'Cancelled'. Sample values turn a guess into a fact.

And the foreign key reference. This is the one that changes the outcome.
Without it the agent has two tables and no idea how they relate, so it
either guesses a join key or asks the user. With it, the join is
determined.

Compare this to what a vector search over table descriptions returns: a
ranked list of table names. That is a starting point. This is a query plan.
-->

---

## From Query Logs to Process Paths

<div class="cols">
<div>

**Ships today**

```text
(Query) -[:USES_TABLE]->  (Table)
(Query) -[:USES_COLUMN]-> (Column)
```

Which assets a query touched.

</div>
<div>

**The next step**

```text
(Question)
  -> selected concepts
  -> source choice
  -> generated query
  -> evidence
  -> result
```

The whole path, connected.

</div>
</div>

<div class="callout"><strong>The shift:</strong> Query logs record what happened. A process path records why, so a later agent can reuse the reasoning rather than rediscover it.</div>

<!--
Query log ingestion already gives you the foundation on the left. Parse
the SQL, record the tables and columns it used.

The direction on the right is to store the whole path. Not just the SQL
that ran, but the question that prompted it, the concepts the agent
selected, why it chose that source, the evidence it retrieved, and the
result.

The difference is reusability. A query log tells a later agent that
somebody once joined orders to customers. A process path tells it that
this specific question was answered by these concepts, this source, and
this query, and that the answer was accepted.

To be clear about status: the left side ships. The right side is direction.
-->

---

## Reuse and Its Boundary

- **Find similar requests** and start from a path that worked
- **Attach signals:** quality, latency, cost, and user feedback
- **Preserve rejected paths** with the reason they were rejected
- **The boundary:** a reused path is a starting point, not an answer

<div class="callout"><strong>Why keep failures:</strong> A path that was rejected for a stated reason stops the next agent repeating the mistake. Deleting it guarantees the mistake recurs.</div>

<!--
Three things make a stored path useful and one keeps it honest.

Similarity search over stored questions lets a later agent find a
comparable request and start from a path that already worked.

Signals let you rank. A path that was fast, cheap, and accepted beats one
that was slow and corrected.

Keeping rejected paths is the part people skip. If an agent tried a join
that produced a wrong answer and you delete that record, the next agent
tries the same join. Keep it with the reason.

And the boundary. A reused path is a hypothesis. The data may have moved,
the schema may have changed, the question may differ in a way that matters.
The agent still has to check its work. Reuse cuts the search space. It
does not remove the need to be right.
-->

---
## Start With One Governed Question

1. **Choose** one business question that spans several related tables
2. **Connect** source schema, glossary terms, and representative query history
3. **Map** the highest-value links between business terms and physical assets
4. **Serve** focused context through the Neocarta MCP server
5. **Execute** through one governed query tool with real access controls
6. **Measure** retrieval relevance, SQL correctness, answer quality, cost
7. **Expand** once the first workflow has proven itself

<div class="callout"><strong>Why one question:</strong> A whole-catalog ingest produces a large graph and no evidence. One question end to end produces a working path and a number you can defend.</div>

<!--
The first motion, and the reason it is one question rather than one catalog.

The temptation with a metadata graph is to load everything. That gets you a
large graph, a slide with an impressive node count, and no evidence that
any of it helps an agent.

Instead: pick one question that genuinely needs discovery across several
tables. Load the schema for those tables, the glossary terms that describe
them, and enough query history to show real access paths.

Validate the mappings by hand. There will not be many, and getting them
right is what makes retrieval work.

Serve it over MCP, wire up one query tool with actual access controls, and
measure. Retrieval relevance, whether the SQL is correct, whether the
answer is right, what it cost.

Then expand. Every source and mapping you add after that is justified by a
workflow that already works, which is a much easier conversation than
asking for budget to build a catalog.
-->
