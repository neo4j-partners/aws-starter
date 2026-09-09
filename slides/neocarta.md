# Proposed Neocarta Presentation Outline

## Brief overview

Neocarta builds a semantic layer in Neo4j. It connects technical metadata to business meaning and gives AI agents focused context through MCP. The presentation should show what Neocarta does today, how it supports a broader enterprise knowledge layer, and how it can adopt the semantic mapping layer approach used by Rosetta SDL while remaining a reusable, cross-platform library.

## Core narrative

**Problem:** Enterprise data is spread across databases, catalogs, glossaries, semantic models, and query logs.

**Approach:** Neocarta creates a connected map of that metadata in Neo4j while source data stays in its system of record.

**Agent value:** Agents use the map to find relevant data, understand business meaning, follow joins, and select the correct query tool.

**Direction:** Neocarta can grow from a metadata graph into a governed part of the enterprise knowledge layer, with stronger semantic mappings, reusable query knowledge, and AWS catalog support.

## Slide outline

### 1. Neocarta: A semantic map for enterprise data

**Purpose:** Introduce Neocarta and state the presentation promise.

- **Neocarta:** An experimental Neo4j Labs Python library for building a semantic layer in Neo4j.
- **Semantic map:** A connected view of where data lives, how it is structured, what it means, and how it joins.
- **Presentation promise:** Show how Neocarta gives agents the context required to discover data and create grounded queries.
- **Data boundary:** Store metadata and semantic links in Neo4j while source data stays in its existing platform.

### 2. The problem: Agents see fragments instead of a data landscape

**Purpose:** Explain why schema access alone does not give an agent enough context.

- **Distributed metadata:** Schemas, glossary terms, metrics, and query history live in separate systems.
- **Technical names:** Tables and columns often use names that do not match the language in a business question.
- **Missing relationships:** Agents need foreign keys, joins, lineage, and source location before they can form a reliable query.
- **Large prompts:** Loading every schema and rule into each prompt increases cost and reduces relevance.

### 3. Neocarta within the enterprise knowledge layer

**Purpose:** Connect Neocarta to the broader knowledge-layer architecture.

- **Enterprise knowledge layer:** A governed connection between business concepts, data assets, policies, prior decisions, and agent tools.
- **Neocarta role:** Build the catalog-driven semantic map that links business language to technical data assets.
- **Agent role:** Traverse the map, retrieve focused context, and choose the correct database or API tool.
- **Source role:** Execute the native SQL or API request and return current business data.

### 4. The metadata that becomes connected context

**Purpose:** Show the inputs that Neocarta brings together.

- **Schema metadata:** Databases, schemas, tables, columns, types, keys, and sample values.
- **Business glossary:** Terms and categories linked to the tables and columns they describe.
- **Metrics:** Governed definitions, expressions, dimensions, and semantic-model context.
- **Query history:** Queries, common joins, and the tables and columns used in real work.
- **Governance tags:** Controlled terms and allowed values that classify schemas, tables, and columns.

### 5. The graph model makes meaning traversable

**Purpose:** Explain why Neo4j is useful for semantic mapping.

- **Technical hierarchy:** Connect each database to its schemas, tables, columns, and values.
- **Join paths:** Connect foreign-key columns so an agent can build valid joins.
- **Business links:** Connect tables and columns to glossary terms with explicit relationships.
- **Usage lineage:** Connect saved queries to the data assets they use.
- **Semantic models:** Represent OSI domains, datasets, metrics, joins, and AI context as a connected subgraph.

**Suggested visual:** Use the Neocarta metadata model and highlight one path from a business term to a column, table, schema, and database.

### 6. Connectors build one shared semantic graph

**Purpose:** Show how metadata enters Neo4j.

- **Extract:** Read metadata from a catalog, database, semantic-model file, query log, or CSV export.
- **Transform:** Convert each source into the shared Neocarta graph model.
- **Load:** Create indexed nodes and relationships in Neo4j.
- **Current connectors:** Support BigQuery, Dataplex, Snowflake, Databricks, Unity Catalog, JDBC, CSV, query logs, and OSI workflows.
- **Connector contract:** Give new platforms a consistent way to contribute metadata without changing agent behavior.

### 7. Search returns focused context instead of the full catalog

**Purpose:** Explain how Neocarta finds the most useful data assets for a question.

- **Catalog browsing:** List available schemas and tables when the agent needs orientation.
- **Full-text search:** Match exact names and description terms without requiring embeddings.
- **Vector search:** Match business questions to related tables and columns by meaning.
- **Hybrid search:** Combine exact and semantic matches for stronger retrieval.
- **Glossary bridge:** Use business terms to reach the technical assets that implement them.

### 8. MCP separates semantic discovery from query execution

**Purpose:** Show the runtime boundary between Neocarta and source systems.

- **Neocarta MCP:** Expose metadata discovery and context retrieval as agent tools.
- **Focused result:** Return tables, columns, types, sample values, and foreign-key references.
- **Query tool:** Use a separate database MCP server, driver, or API to run the final native query.
- **Clear responsibility:** Let Neocarta explain the data landscape and let the source platform execute against live data.

**Suggested visual:** Show the user, agent, model, Neocarta MCP, Neo4j metadata graph, database MCP, and source database.

### 9. A grounded text-to-query flow

**Purpose:** Walk through one complete agent request.

- **Question:** Ask which customers placed the largest orders last quarter.
- **Discover:** Search Neocarta for customer, order, amount, and date concepts.
- **Connect:** Follow the foreign key from orders to customers.
- **Generate:** Create native SQL from the retrieved schema and business context.
- **Execute:** Send the SQL through the source database tool.
- **Answer:** Return the result with the data sources and query path used.

### 10. Rosetta SDL approach Neocarta will adopt

**Purpose:** Explain the shared semantic mapping direction.

Neocarta will use the semantic mapping layer approach of Rosetta SDL.

- **Physical catalog:** Map databases, tables, columns, joins, and source locations.
- **Business meaning:** Link business terms, concepts, and governed metrics to physical data assets.
- **Usage knowledge:** Add query history and common access paths to improve discovery and planning.
- **Agent access:** Expose the connected context through MCP tools.
- **Hybrid discovery:** Combine graph traversal, keyword search, and embeddings.
- **AWS extension:** Add AWS Glue Data Catalog and governed AWS table metadata as Neocarta sources.
- **Zero-copy model:** Keep business data in AWS systems of record and store the semantic map in Neo4j.

### 11. Neocarta and Rosetta SDL serve different scopes

**Purpose:** Highlight the main differences after establishing the shared approach.

- **Product shape:** Rosetta SDL is a complete AWS application. Neocarta is a reusable Python library, CLI, graph model, and MCP server.
- **Platform scope:** Rosetta SDL focuses on AWS Glue, Athena, S3 Vectors, and Bedrock. Neocarta supports metadata from several cloud data platforms and open formats.
- **Query execution:** Rosetta SDL can plan, validate, and run Athena queries. Neocarta supplies context and relies on a separate tool to execute the source query.
- **Metric safety:** Rosetta SDL compiles approved metrics into repeatable SQL. Neocarta stores and retrieves metric definitions for an agent or query tool to use.
- **SQL controls:** Rosetta SDL validates SQL and limits allowed operations and tables. Neocarta does not act as the query execution firewall.
- **Documents:** Rosetta SDL includes document metadata and chunk search. Neocarta focuses on structured metadata, glossary content, semantic models, and query history.
- **User experience:** Rosetta SDL includes an API and web administration interface. Neocarta provides package, command-line, and MCP interfaces.
- **Deployment:** Rosetta SDL includes AWS infrastructure and authentication. Neocarta connects to an existing Neo4j database and source-platform clients.

### 12. Neocarta and virtual graphs solve different problems

**Purpose:** Clarify how semantic mapping and federated graph querying can work together.

- **Neocarta:** Helps an agent decide what data matters, what it means, and which source or query path to use.
- **Virtual graph:** Translates Cypher into a source-native query and provides a unified graph query interface.
- **Shared feature:** Both can represent source schemas without copying all source data into Neo4j.
- **Combined flow:** Use Neocarta for business context and routing, then use a virtual graph or native query tool for retrieval.

### 13. Extend the map with reusable query and process knowledge

**Purpose:** Connect the current project to the shared-memory direction in the enterprise knowledge layer.

- **Current foundation:** Query-log ingestion records which tables and columns a query uses.
- **Next step:** Store the question, selected concepts, source choice, generated query, evidence, and result as a process path.
- **Reuse:** Let later agents find similar requests and start from successful paths.
- **Improvement:** Attach quality, latency, cost, and feedback signals to each path.
- **Learning boundary:** Preserve rejected paths with clear reasons so agents do not repeat known mistakes.

### 14. Governance turns retrieval into trusted context

**Purpose:** Show how teams can control and improve agent behavior.

- **Automated evaluation:** Check retrieval quality, query validity, evidence use, and performance.
- **User feedback:** Capture approval, correction, and task outcome signals.
- **Expert review:** Let data stewards validate mappings, metrics, policies, and preferred query paths.
- **Traceability:** Keep the selected context, tool calls, queries, evidence, and result available for review.
- **Authority:** Use expert-approved definitions and controls for high-risk business decisions.

### 15. Start with one governed question

**Purpose:** Close with a practical implementation sequence.

- **Choose:** Select one business question that requires data discovery across several related tables.
- **Connect:** Load the source schema, glossary terms, metrics, and representative query history.
- **Map:** Validate the highest-value links between business terms and physical assets.
- **Serve:** Expose focused context through the Neocarta MCP server.
- **Execute:** Connect one governed source-query tool with clear access controls.
- **Measure:** Track retrieval relevance, SQL correctness, answer quality, latency, and cost.
- **Expand:** Add sources, mappings, and reusable paths after the first workflow proves value.

## Flow test

**Question 1:** Why do agents need more than raw schema metadata?

**Question 2:** What information does Neocarta connect in Neo4j?

**Question 3:** How does an agent use Neocarta to discover and query data?

**Question 4:** Which Rosetta SDL ideas will Neocarta adopt, and where will the projects remain different?

**Question 5:** How can the semantic map become a governed and reusable part of the enterprise knowledge layer?
