## Recommended presentation flow

**Narrative:** AWS provides the governed data, analytics, AI, and application platform. Neo4j provides the connected context needed to understand relationships, patterns, and business meaning. Together, they turn distributed enterprise data into grounded knowledge for investigators, applications, and AI agents.

### 1. Introduce the two platforms

1. **Presentation promise:** Show how AWS and Neo4j work better together for connected financial investigations and enterprise AI.
2. **AWS overview:** Explain the AWS services that store and process data, run analytics, provide foundation models, and operate agents and applications.
3. **Neo4j overview:** Explain the graph database, Cypher, graph analytics, connected context, and knowledge graph capabilities.
4. **Better together:** Establish the division of responsibility: AWS stores and analyzes activity; Neo4j reveals connections.

### 2. Show how AWS and Neo4j connect

5. **Integration paths:** Introduce the Spark connector on Amazon EMR, AWS Glue connector, Kafka connector on Amazon MSK, Neo4j drivers for AWS compute services, and MCP tools for AWS agents.
6. **Virtual graph:** Explain how a graph query can reach governed AWS data without copying all source data into Neo4j.

### 3. Explain the shared financial data model

7. **Investigation scenario:** Use a suspicious transaction or fraud-ring question to show why both tabular activity and connected context are required.
8. **Data model overview:** Show customers, accounts, transactions, devices, merchants, alerts, cases, policies, and their relationships.
9. **Data placement:** Show what remains in AWS systems of record and what is stored or represented in Neo4j.
   - **AWS:** Raw transactions, time-series activity, source records, documents, tables, operational history, and large-scale analytical data.
   - **Neo4j:** Important entities and relationships, fraud patterns, semantic mappings, policies, investigation context, and selected graph-optimized data.
10. **Query responsibilities:** Show how AWS SQL finds unusual activity over time while Neo4j Cypher finds patterns across many connections.

### 4. Build the enterprise knowledge and agent layer

11. **Enterprise Knowledge Layer:** Explain how shared business meaning connects enterprise data, policies, ontology, semantic mappings, and prior decisions.
12. **NeoCarta:** Show how catalog metadata, glossary terms, and query lineage create a semantic map that helps agents discover data and select the right source or query path.
13. **Agent Memory:** Show how Neo4j stores short-term context, durable facts, reasoning traces, feedback, and investigation outcomes for reuse.
14. **Grounded agent workflow:** Show an AWS-hosted agent using the knowledge layer to select graph, SQL, document, or API tools and return evidence-backed answers.

### 5. Close with the combined value

15. **End-to-end architecture:** Bring AWS data and AI services, Neo4j graph capabilities, the Enterprise Knowledge Layer, NeoCarta, and Agent Memory into one view.
16. **Starting point:** Recommend one governed investigation that needs both transaction evidence from AWS and connected context from Neo4j, then expand from that proven use case.

**Flow test:** Each section answers one question in order: What does each platform provide? How do they connect? What data model do they share? Where does each type of data belong? What new enterprise AI capabilities do they enable together?

Core writing style

Write in very, very plain and simple English. Start with a brief overview, then use short bullet points in this format: **Term:** definition.

- Lead each sentence with its purpose.
- Replace rhetorical phrases with concrete instructions.
- Use direct, positive statements instead of litotes.
- Shorten sentences and remove unnecessary contrasts.
- Explain technical cause and effect plainly.

Agenda – Neo4j key topics include:

  1.  Enterprise Knowledge Layer: An overview of Neo4j's shared, governed enterprise knowledge layer, which connects ontology, semantic mapping, enterprise data, and memory to ground agents and applications. It gives agents a continuously queryable model of business concepts, data assets, policies, and prior decisions. This will primarily discuss Jesús Barrasa's article, The knowledge layer for enterprise AI<https://neo4j.com/blog/agentic-ai/enterprise-knowledge-layer/>.

  1.  Catalog-driven semantic map with NeoCarta: NeoCarta is an experimental Neo4j Labs library that turns catalog metadata, business-glossary terms, and query-usage lineage into an embedded Neo4j semantic graph. Through MCP, it supports data discovery, query routing, and text-to-SQL agents. Planning is underway to extend it to AWS Glue Data Catalog metadata and governed table definitions, linking business terms to physical data assets before agents generate queries.

  1.  Neo4j Virtual Graph: Neo4j Virtual Graph is currently supported with Snowflake and Databricks, and is actively being built for AWS. An overview of how Neo4j's virtual graph approach translates graph queries into SQL and runs them against data lake storage without copying data into Neo4j. Current integration plans cover Amazon S3 Tables using Apache Iceberg and the AWS Glue Data Catalog.

  1.  Neo4j Agent Memory: An overview of neo4j-agent-memory<https://github.com/neo4j-labs/agent-memory>, an open-source library for graph-backed short-term, long-term, and reasoning memory. It keeps entities, facts, and decision traces inspectable alongside the knowledge graph. Its long-term POLE+O model (Person, Object, Location, Event, Organization) supports temporal validity, and it integrates with the Strands Agents SDK.
