## Purpose and direction

**Deck purpose:** This deck tells the AWS and Neo4j integration story. It shows AWS field teams where Neo4j fits inside an AWS architecture, which AWS services it complements, and how the two platforms combine to ground enterprise AI agents.

**Audience:** The audience is AWS field. This includes solutions architects, partner solutions architects, and specialists who position architectures with customers and run co-sell motions.

**Narrative:** AWS provides the governed data, analytics, AI, and application platform. Neo4j provides the connected context needed to understand relationships, patterns, and business meaning. Together, they turn distributed enterprise data into grounded knowledge for investigators, applications, and AI agents.

**Emphasis:** The platform integration story carries the deck. Financial fraud investigation appears only as a worked example that makes the architecture concrete.

### Key goals

1. **Place Neo4j on the AWS platform:** AWS field should leave with a clear picture of which AWS layer Neo4j sits in and what it adds to that layer.
2. **Name the adjacent AWS service for every Neo4j capability:** Every Neo4j capability in the deck states the AWS service it sits next to, and whether it complements that service or overlaps with it.
3. **Show how data moves and how queries reach across:** AWS field should know the supported integration paths and the Virtual Graph approach that queries AWS data in place.
4. **Separate what ships today from what is in build:** AWS field needs to know what they can position now and what is roadmap.
5. **Give AWS field a repeatable customer conversation:** The deck ends with a first customer motion that AWS field can run.

### Reusable layer map

**Layer map:** The layer map is a single diagram of the AWS platform stack. It appears first with AWS services only, then with Neo4j placed into it, and again fully populated in the close.

The map names five layers:

```text
Applications and agents   -> AgentCore Runtime, Strands Agents
Models                    -> Amazon Bedrock
Analytics and processing  -> Athena, EMR, Glue, MSK, SageMaker
Catalog and governance    -> Glue Data Catalog, SageMaker Catalog, Lake Formation
Storage                   -> Amazon S3, S3 Tables with Apache Iceberg
```

**Why it repeats:** Reusing one picture three times is what makes the Neo4j placement land. Slide 2 shows AWS only. Slide 3 adds Neo4j. Slide 17 shows the complete architecture on the same skeleton.

**Artwork:** Build one new SVG for this map with three states. Derive the layout from `semantic-reference-architecture.svg`, which already shows the populated end state.

---

## Recommended presentation flow

Total slide count is 20.

### 1. Introduce the two platforms (4 slides)

1. **Presentation promise:** Show how AWS and Neo4j work better together for enterprise AI and connected investigations.
2. **AWS layer map:** Show the five AWS layers with their services. This is the shared map the rest of the deck references.
   - *Artwork:* Layer map, state 1.
3. **Neo4j on the layer map:** Place the graph database, Cypher, graph analytics, and knowledge graph capabilities into the same five layers. Neo4j sits across storage, catalog, and application layers rather than replacing any one of them.
   - *Artwork:* Layer map, state 2.
4. **Division of labor:** Establish the split. AWS stores and analyzes activity. Neo4j reveals connections and business meaning.
   - *AWS adjacency:* Neo4j complements Athena and Redshift for aggregate analysis. It does not replace the system of record.

### 2. Show how AWS and Neo4j connect (2 slides)

5. **Integration paths:** Introduce the Spark connector on Amazon EMR, the AWS Glue connector, the Kafka connector on Amazon MSK, Neo4j drivers for Lambda, ECS, EKS, and EC2, and MCP tools for AWS agents.
   - *AWS adjacency:* Each path uses an existing AWS service. Nothing here asks the customer to adopt new infrastructure.
6. **Virtual graph:** Explain how a graph query reaches governed AWS data without copying all source data into Neo4j. Current integration plans cover Amazon S3 Tables using Apache Iceberg and the AWS Glue Data Catalog.
   - *AWS adjacency:* AWS field will compare this to Athena federated query and Redshift Spectrum. State the difference. Those push SQL to remote sources. Virtual Graph translates a graph traversal into SQL against Iceberg tables.
   - *Status:* Virtual Graph is in public preview for Snowflake, Databricks, and Google BigQuery. AWS support is in build.

### 3. Worked example (2 slides)

7. **Investigation scenario:** Use a fraud-ring question to show why both tabular activity and connected context are required. Keep this to one scenario and move on.
   - *Artwork:* Reuse the ASCII pattern from `aws-neo4j-grounded-enterprise-ai.md`, which shows a shared device and a circular payment chain.
8. **Data model and placement in one view:** Show customers, accounts, transactions, devices, merchants, alerts, cases, and policies, and show where each lives in the same picture.
   - **AWS:** Raw transactions, time-series activity, source records, documents, tables, operational history, and large-scale analytical data stay in AWS.
   - **Neo4j:** Important entities and relationships, fraud patterns, semantic mappings, policies, investigation context, and selected graph-optimized data live in Neo4j.
   - *Artwork:* `dual-data-architecture-aws.svg`.
   - *AWS adjacency:* Athena queries the S3 tables. Cypher traverses the graph. One question uses both.

### 4. Neo4j capabilities on AWS (8 slides)

9. **Enterprise Knowledge Layer, what it is:** Explain how shared business meaning connects enterprise data, policies, ontology, semantic mappings, and prior decisions into one governed layer.
   - *Artwork:* `exec-knowledge-layer.svg`.
10. **Enterprise Knowledge Layer, what it adds:** Show the layer answering the fraud question by linking an alert to the policy, typology, and prior investigation that explain it.
    - *AWS adjacency:* AWS field will ask how this relates to Amazon Bedrock Knowledge Bases. Knowledge Bases retrieve passages from documents. The Enterprise Knowledge Layer holds governed business concepts, relationships, and prior decisions that an agent queries directly.
11. **NeoCarta, what it is:** Explain how catalog metadata, business-glossary terms, and query-usage lineage become an embedded Neo4j semantic graph exposed through MCP.
    - *Artwork:* `neocarta.svg`.
12. **NeoCarta, what it adds:** Show an agent using the semantic map for data discovery, query routing, and text-to-SQL.
    - *AWS adjacency:* Planned AWS catalog support will read metadata from the AWS Glue Data Catalog and SageMaker Catalog. Those catalogs remain authoritative. NeoCarta links business terms to physical data assets before an agent generates a query.
    - *Status:* NeoCarta is an experimental Neo4j Labs library. Glue Data Catalog support is planned.
13. **Agent Memory, what it is:** Explain graph-backed short-term, long-term, and reasoning memory. The long-term POLE+O model covers Person, Object, Location, Event, and Organization, and it supports temporal validity.
    - *Artwork:* `neo4j-agent-memory-diagram.svg`.
14. **Agent Memory, what it adds:** Show entities, facts, and decision traces staying inspectable alongside the knowledge graph, so an investigation outcome becomes reusable.
    - *AWS adjacency:* AWS field will ask how this relates to AgentCore Memory. Answer it on the slide. Also note the Strands Agents SDK integration, since Strands is AWS's own agent SDK.
15. **Grounded agent workflow, the mechanics:** Show an AWS-hosted agent selecting graph, SQL, document, or API tools and returning evidence-backed answers.
    - *AWS adjacency:* The agent runs on AgentCore Runtime. AgentCore Gateway handles tool access and OAuth2. Amazon Bedrock provides the model. Neo4j is reached through MCP.
16. **Grounded agent workflow, the callback:** Show where the Virtual Graph fits as one retrieval option inside the knowledge layer, alongside Cypher over the persisted graph and SQL over S3 Tables.

### 5. Close (4 slides)

17. **End-to-end architecture:** Bring AWS data and AI services, Neo4j graph capabilities, the Enterprise Knowledge Layer, NeoCarta, and Agent Memory into the layer map.
    - *Artwork:* Layer map, state 3. Use `semantic-reference-architecture.svg` as the source.
18. **Where Neo4j runs on AWS:** Cover AuraDB on AWS, the AWS Marketplace listing and consumption path, AWS PrivateLink, current AgentCore regional availability, including us-east-1 and us-west-2, and self-managed deployment on EKS and EC2.
19. **Shipping today, public preview, in build, planned:** Separate what AWS field can position now from preview and roadmap. Virtual Graph is in public preview for Snowflake, Databricks, and Google BigQuery. Virtual Graph for AWS is in build. NeoCarta Glue support is planned. The Enterprise Knowledge Layer pattern, Agent Memory, and the connector, driver, and MCP paths on slide 5 are available today.
20. **Start the customer conversation:** Give AWS field the first motion. Find one governed investigation that needs both transaction evidence from AWS and connected context from Neo4j, prove it, then expand from that use case.

**Flow test:** Each section answers one question in order. What does each platform provide, and where does Neo4j sit? How do they connect? What does this look like on a real problem? What does Neo4j add to an AWS agent stack? What can AWS field position today, and what do they say first?

### Artwork inventory

| Asset | Used on | Status |
| --- | --- | --- |
| `aws-neo4j-layer-map.svg`, three states | Slides 2, 3, 17 | Built and used in the deck |
| `dual-data-architecture-aws.svg` | Slide 8 | Used in the deck |
| `exec-knowledge-layer.svg` | Slide 9 | Used in the deck |
| `neocarta.svg` | Slide 11 | Used in the deck |
| `neo4j-agent-memory-diagram.svg` | Slide 13 | Used in the deck |
| `semantic-reference-architecture.svg` | Reference for slide 17 | Retained as a source reference |

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

  1.  Neo4j Virtual Graph: Neo4j Virtual Graph is in public preview for Snowflake, Databricks, and Google BigQuery, and is actively being built for AWS. An overview of how Neo4j's virtual graph approach translates graph queries into SQL and runs them against data lake storage without copying data into Neo4j. Current integration plans cover Amazon S3 Tables using Apache Iceberg and the AWS Glue Data Catalog.

  1.  Neo4j Agent Memory: An overview of neo4j-agent-memory<https://github.com/neo4j-labs/agent-memory>, an open-source library for graph-backed short-term, long-term, and reasoning memory. It keeps entities, facts, and decision traces inspectable alongside the knowledge graph. Its long-term POLE+O model (Person, Object, Location, Event, Organization) supports temporal validity, and it integrates with the Strands Agents SDK.
