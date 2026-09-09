## Purpose and direction

**Deck purpose:** This deck explains Neocarta and positions it against Rosetta SDL. It shows what Neocarta builds in Neo4j, how agents use that semantic map, and why Neocarta and Rosetta SDL reach the same runtime shape from opposite directions.

**Audience:** The audience is technical. This includes solutions architects, data architects, data engineers, and AI engineers who evaluate semantic-layer options and will ask pointed questions about scope and execution boundaries.

**Narrative:** Enterprise metadata is scattered across catalogs, glossaries, semantic models, and query logs. Neocarta connects that metadata in Neo4j and serves it to agents over MCP, so an agent understands the data landscape before it writes a query. Rosetta SDL solves the same discovery problem inside a complete AWS application. The two projects agree on architecture and differ on scope.

**Emphasis:** The core talk carries the Neocarta overview and the Rosetta SDL comparison. Every deeper mechanism lives in a droppable module, so the deck fits the time available without losing its argument or its close.

### Key goals

1. **Explain what Neocarta is:** The audience should leave knowing Neocarta is a Python library, a CLI, and an MCP server that build and serve a semantic map in Neo4j.
2. **Draw the execution boundary:** Neocarta supplies context. A separate database tool runs the query. State this early and hold it.
3. **Position against Rosetta SDL honestly:** Both projects use Neo4j to link technical metadata to business meaning. Rosetta SDL is a complete AWS application. Neocarta is a reusable cross-platform library.
4. **Show that the two compose:** Rosetta SDL's plan mode returns SQL without executing it. That is the boundary Neocarta enforces by design. This is the strongest point in the comparison.
5. **Survive a shortened slot:** The presenter must be able to drop modules from the back and still land the close.

### Timing model

The deck is three blocks: a fixed core, a modular middle, and a fixed close.

```text
CORE     10 slides    ~17 min    always runs
MODULES   7 modules   3-6 min    drop from the back
CLOSE     1 slide     ~2 min     always runs
```

| Slot | Run |
| --- | --- |
| 15 min | Core, then close |
| 30 min | Core, then B1, B2, B3, then close |
| 45 min | Core, then B1 through B5, then close |
| 60 min | Everything |

**Why the close is fixed:** In the previous outline the call to action was the last slide in a flat run, so it died whenever the presenter ran short. Pulling it out of the module pool means every version of the talk ends the same way.

**Why modules are value-ordered:** B1 through B7 descend in value, so the presenter drops from the back. No module depends on a later module, and no slide numbering changes when one is cut.

---

## Recommended presentation flow

Core is 10 slides, one of which is a section divider. Modules total 17 slides. Close is 1 slide. Full run is 28 slides.

### Section A: Core (10 slides)

1. **Presentation promise:** Introduce Neocarta as an experimental Neo4j Labs Python library that builds a semantic layer in Neo4j and serves it to agents over MCP. State the data boundary. Only metadata crosses into Neo4j, and source data stays in its platform.
2. **The problem:** Explain why schema access alone is not enough. Metadata is split across systems, technical names do not match business language, joins and lineage are missing, and loading every schema into a prompt is expensive and unfocused.
3. **What Neocarta is, in three surfaces:** Establish the shape of the project before any mechanism. The Python library holds the connectors, the CLI drives ingestion and mirrors every retrieval tool, and the MCP server serves the graph to agents.
   - *Note:* This slide replaces three separate mechanism slides in the previous outline. The mechanisms move to modules B2 and B3.
4. **The architecture, diagram only:** Show where the semantic layer sits between the data sources and the agent. No bullets, no callout. Let the presenter narrate the picture while the audience looks at it.
   - *Artwork:* `neocarta.svg`, or a new graph-model SVG. See the artwork inventory.
   - *Note:* This slide carries no text on purpose. The audience cannot read bullets and follow a diagram walkthrough at the same time.
5. **How a business term resolves to a real column:** Trace one path from a business term to a column, table, schema, and database, including the foreign key that makes the join. Separate what the map is built from at ingestion time from what the traversal hands back at query time. Close on candidates versus a query plan, since embedding search ranks table names while the traversal returns the column, the join, and the reason it was chosen.
6. **A grounded text-to-query flow, who does what:** Walk one request end to end with an actor on every step. The agent makes one retrieval call, Neocarta returns the orders and customers tables along with the foreign key between them, the agent's LLM writes the SQL, a separate query tool runs it, and the agent answers with its sources cited.
   - *Note:* Label each step with the actor. Without that the diagram reads as a pipeline where the foreign key looks like a second lookup and nobody appears to write the SQL. Say out loud that `REFERENCES` is already in the graph, so the join arrives inside the first result, and that Neocarta never generates or runs SQL.
7. **Divider, Neocarta and Rosetta SDL:** Mark the turn from "what Neocarta is" to the comparison, and introduce Rosetta SDL before the audience meets the word "both" in a slide title. Subtitle: the same architecture, reached from opposite directions. Neocarta grew outward from a library across platforms, Rosetta SDL worked inward from a complete AWS application, and the presenter names the three slides that follow.
   - *Note:* Without this slide the deck jumps into a comparison against a project the audience has not been told about. The `section` class carries no readable body text on its dark background, so the introduction of Rosetta SDL lives in the speaker notes here and as a lead-in line on the next slide.
8. **Building a semantic map is the core feature of both:** State that building the map is what each project is for, then list the shared functionality in a table. Both build a semantic map in Neo4j linking technical metadata to business meaning, both offer catalog discovery, both expose it over MCP, both combine traversal with keyword and embedding search, and both keep source data in place.
   - *Note:* Table only, no callout. The slide establishes shared ground and nothing else. The differences follow on slide 9.
   - *Correction:* The previous outline titled this "Rosetta SDL approach Neocarta will adopt" and then listed five things Neocarta already ships. Present them as shared functionality, not as adoption.
9. **Where the two diverge:** Four dimensions only. Product shape, platform scope, query execution, and safety controls.
   - *Note:* The previous outline had eight paired contrasts on one slide. The remaining four move to module B6 and the appendix.
10. **Plan and execute: why they compose:** Rosetta SDL's `plan_query` returns SQL and search parameters without executing them, so an agent can hand the SQL to an external Athena MCP server. Neocarta occupies that same position by design. The two projects arrive at one runtime shape from opposite directions.
   - *Note:* This slide is new. It turns the comparison from a feature scorecard into an argument.

### Section B: Deep dive modules

Each module is self-contained and carries its own divider slide naming the module and its time cost.

#### Module B1: The graph model in depth (3 slides, ~5 min)

11. **The core model:** Show `Database`, `Schema`, `Table`, `Column`, and `Value`, with `HAS_SCHEMA`, `HAS_TABLE`, `HAS_COLUMN`, `HAS_VALUE`, and `REFERENCES`. Every connector converts its source metadata into this shape, which is what makes the MCP server work against any of them.
12. **The glossary extension:** Show `Glossary`, `Category`, and `BusinessTerm`, linked to tables and columns through `TAGGED_WITH`. This is the bridge from business language to physical assets, and it is what the business-term retrieval tools traverse.
13. **Query logs and semantic models:** Show `Query` and `CTE` nodes with `USES_TABLE` and `USES_COLUMN`, then the OSI subgraph of `OsiSemanticModel`, `OsiTable`, `OsiColumn`, `Metric`, `Expression`, `Join`, and `OsiAiContext`. Usage history and governed metric definitions extend the same core model.

#### Module B2: Connectors and the connector contract (3 slides, ~5 min)

14. **Extract, transform, load:** Every connector decomposes the same way. Extractors read source metadata, transformers validate and convert it with Pydantic, loaders write indexed nodes and relationships, and the connector class orchestrates the three.
15. **Current connector inventory:** Cover BigQuery schema, BigQuery logs, Dataplex schema, Dataplex glossary, Snowflake, Databricks, Unity Catalog, JDBC, CSV, query logs, and OSI. Note that OSI is bidirectional, since it both ingests a YAML spec and exports a semantic model subgraph back to YAML.
    - *Verify before presenting:* Snowflake, Databricks, Unity Catalog, and JDBC packages exist in the tree but are not documented in the README at the depth of the others. Confirm maturity before naming all eleven to a customer audience.
16. **The connector contract:** New platforms contribute metadata without changing agent behavior. The repo ships a scaffold command that generates a connector package with a conformance test, and a verify command that checks a connector against the contract.

#### Module B3: Retrieval in depth (3 slides, ~5 min)

17. **Five ways to find a table:** Catalog browsing lists schemas and tables for orientation, full-text search matches exact names and description terms, vector search matches meaning, hybrid search combines both, and the glossary bridge reaches physical assets through business terms.
18. **The MCP server adapts to the graph it finds:** The server probes the target database at startup and registers, per label, the highest-priority retrieval tool whose indexes are present. Priority runs business-term hybrid, then hybrid, then vector or full-text alone. An agent never sees a tool the graph cannot serve.
19. **What a result actually contains:** Retrieval returns a table with its columns, types, example values, and foreign-key references. The foreign keys are what let the agent build the join, which is the difference between a table list and a usable query plan.

#### Module B4: The AWS path (2 slides, ~4 min)

20. **AWS Glue Data Catalog as a Neocarta source:** This is the one genuinely open item from the Rosetta SDL comparison. Adding Glue and governed AWS table metadata as a connector puts Neocarta in front of an AWS data estate using the same graph model and the same MCP tools.
21. **Zero-copy and where the agent runs:** Business data stays in the AWS system of record and the semantic map lives in Neo4j. Cover how an AWS-hosted agent reaches the map, since Rosetta SDL already ships a Bedrock AgentCore deployment path.

#### Module B5: Reusable query and process knowledge (2 slides, ~4 min)

22. **From query logs to process paths:** Query-log ingestion already records which tables and columns a query touches. The next step stores the question, the selected concepts, the source choice, the generated query, the evidence, and the result as one connected path.
23. **Reuse and its boundary:** Later agents find similar requests and start from successful paths. Attach quality, latency, cost, and feedback signals to each path. Preserve rejected paths with their reasons, so agents do not repeat known mistakes.

#### Module B6: Governance and the remaining differences (2 slides, ~4 min)

24. **Governance turns retrieval into trusted context:** Cover automated evaluation of retrieval quality and query validity, user approval and correction signals, data-steward review of mappings and metrics, traceability of context and tool calls, and expert-approved definitions for high-risk decisions.
25. **The remaining four differences:** These are the rows cut from core slide 9. Rosetta SDL compiles approved metrics into repeatable SQL with no LLM, validates SQL through a sqlglot firewall that fails closed, searches document chunks in S3 Vectors, and ships a FastAPI service with a React admin interface and Cognito authentication. Neocarta stores and retrieves metric definitions, does not act as the execution firewall, focuses on structured metadata, and ships as a package, a CLI, and an MCP server.

#### Module B7: Neocarta and virtual graphs (2 slides, ~3 min)

26. **Two different problems:** Neocarta helps an agent decide what data matters, what it means, and which source to use. A virtual graph translates Cypher into a source-native query and presents a unified graph interface. Both avoid copying all source data into Neo4j.
27. **The combined flow:** Use Neocarta for business context and routing, then use a virtual graph or a native query tool for retrieval. Answer this on the slide, because the audience will ask whether the two overlap.

### Close (1 slide)

28. **Start with one governed question:** Give the audience the first motion. Select one business question that needs discovery across several related tables, load the source schema with glossary terms and representative query history, validate the highest-value mappings, serve the context through the MCP server, connect one governed query tool, measure retrieval relevance and query correctness, then expand.

**Flow test:** Each block answers one question in order. What is Neocarta and why does an agent need it? How does it compare to Rosetta SDL, and do the two compete? How does each mechanism actually work? What does the audience do first?

---

### Content corrections from the previous outline

1. **Slide 10 overstated the gap.** It was titled "Rosetta SDL approach Neocarta will adopt" and listed physical catalog, business meaning, usage knowledge, MCP access, and hybrid discovery. Neocarta ships all five today. The core graph model carries `REFERENCES` for joins, the Dataplex connector brings `BusinessTerm` and `TAGGED_WITH`, the query-log connector brings `Query` with `USES_TABLE` and `USES_COLUMN`, and the MCP server already serves hybrid search bridged through business terms. Core slide 8 now presents them as shared functionality. The one open item is the AWS Glue connector, which moves to module B4.
2. **The plan and execute symmetry was missing.** It is the strongest available comparison point and it now has its own core slide.
3. **The differences slide was unreadable.** Eight paired contrasts became four in core slide 9, with the remainder in module B6.
4. **Connector claims need verification.** The previous outline named Snowflake, Databricks, Unity Catalog, and JDBC. The packages exist, but the README does not document them at the depth of the BigQuery, Dataplex, CSV, query-log, and OSI connectors. Module B2 carries the verification note.

### Artwork inventory

| Asset | Status | Used by |
| --- | --- | --- |
| `neocarta.svg` | Exists. Shows the knowledge-layer architecture from data sources through the semantic layer to the agent and retrieval layers. | Core slide 4, which is diagram only |
| Graph model diagram | Needed. Core model with one highlighted path from business term to column to table to schema to database. | Core slide 4, module B1 slide 11 |
| Glossary extension diagram | Needed. Can be a second state of the graph model diagram. | Module B1 slide 12 |
| Query log and OSI diagram | Needed. Can be a third state of the graph model diagram. | Module B1 slide 13 |
| Connector ETL diagram | Derivable from the connector architecture Mermaid diagrams in the Neocarta README. | Module B2 slide 14 |
| Text-to-query flow | ASCII in a `text` fence is sufficient. | Core slide 6 |
| Plan and execute flow | ASCII in a `text` fence. Derivable from the plan-mode diagram in the Rosetta SDL README. | Core slide 10 |

**Reusable diagram states:** Build the graph model as one SVG with three states, the way `aws-neo4j-layer-map.svg` carries the AWS layer map. Core slide 4 shows the core model on its own, and core slide 5 highlights one path across it. Module B1 adds the glossary, then the query logs and OSI subgraph. Reusing one skeleton is what makes the extensions land, and it keeps module B1 cheap to drop.

### Source repositories

| Project | Path | Shape |
| --- | --- | --- |
| Neocarta | `neo4j-field/neocarta` | Experimental Neo4j Labs Python library, CLI, and MCP server. Apache 2.0. |
| Rosetta SDL | `rosetta-sdl` | Complete AWS application with FastAPI, React admin UI, MCP server, and CDK deployment. MIT. |
