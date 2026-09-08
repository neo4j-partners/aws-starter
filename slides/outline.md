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
