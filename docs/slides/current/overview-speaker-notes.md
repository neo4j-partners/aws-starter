# Speaker Notes: Neo4j + AWS

## Neo4j + AWS

This talk shows how Neo4j and AWS work together for finance and fraud use cases.

- **Why graphs:** Connected data answers questions that separate tables cannot.
- **How they fit:** Neo4j adds relationship context to the AWS data and agent services.
- **Integration patterns:** Data connectors, agent tools, memory, and GraphRAG.
- **Source material:** The AWS Agentic AI Conference deck and the Neo4j hotel booking workshop, rewritten for a finance and fraud audience.

## Neo4j Graph Intelligence Platform

This section explains what a graph database is and why it fits fraud work.

- **First:** The basic building blocks of a graph.
- **Then:** What those blocks give a fraud investigator.

## What Is a Graph Database

A graph has three building blocks. Neo4j adds a query language on top.

- **Node:** A thing, such as a person, an account, or a merchant.
- **Relationship:** A named link from one node to another.
- **Property:** A value stored on a node or a relationship.
- **Cypher:** The query language. It matches paths in the graph, where SQL joins tables.
- **Why it is fast:** Neo4j stores each relationship. Following one is a single hop, so the cost does not grow with the size of the data.

## Fraud Ring as a Property Graph

This diagram shows a small fraud ring as a property graph.

- **Accounts:** ACC-1001 and ACC-2047 each carry properties such as owner, status, and open date.
- **Transfers:** TRANSFERRED_TO relationships link the two accounts. One is a $4,200 wire. The other is a $3,800 ACH.
- **Address:** Both accounts register at the same address through REGISTERED_AT relationships.
- **Point:** The ring is one traversal. It is not a chain of joins.

## Why a Knowledge Graph Fits Fraud Investigations

A graph shows investigators how things connect. Isolated transactions hide that.

- **Full network:** Customers, accounts, devices, addresses, merchants, alerts, and cases sit in one view.
- **Hidden links:** Shared identifiers reveal indirect connections.
- **Follow the money:** A traversal follows transfers across any number of accounts. You do not need to know the chain length first.
- **Explain why:** Suspicious activity links to fraud typologies, policies, KYC documents, and prior cases.
- **Adapt:** New entities and connections need no rebuild of a fixed schema.

## The Five Roles of Neo4j in Enterprise AI Agents

One graph stack plays five roles for enterprise AI agents on Bedrock and AgentCore.

- **Knowledge layer:** GraphRAG and multi-hop reasoning over extracted entities.
- **Agent brain:** A graph of goals, actions, dependencies, and outcomes.
- **Context layer:** Session and cross-session memory that connects entities.
- **Semantic layer:** A bridge from natural language to systems such as Redshift, S3, SAP, and Salesforce.
- **Reasoning and data layer:** Graph Data Science algorithms exposed as agent tools.

## AWS + Neo4j: Connected Context for Grounded Enterprise AI

This section shows where Neo4j fits in the AWS platform.

- **Customers:** Many companies already run both.
- **Layers:** AWS holds the data, models, and agents. Neo4j adds connected context.

## Select Neo4j and AWS Customers

Many large companies use Neo4j and AWS together.

- **Range:** The list spans media, pharma, automotive, telecom, finance, and aerospace.
- **Point:** The pairing is proven in production across industries.

## AWS Provides the Foundation for Governed Enterprise AI

This slide shows the AWS layers first, before Neo4j.

- **Storage:** Amazon S3 and S3 Tables with Apache Iceberg.
- **Catalog and governance:** Glue Data Catalog, SageMaker Catalog, and Lake Formation.
- **Analytics and processing:** Athena, EMR, Glue, MSK, and SageMaker AI.
- **Models:** Amazon Bedrock.
- **Applications and agents:** AgentCore Runtime, AgentCore Gateway, and Strands Agents.

## Neo4j Adds Connected Context Across the AWS Platform

Neo4j adds a connected layer next to the AWS layers.

- **Cypher, drivers, and MCP:** Connected tools for AWS agents.
- **Context for Bedrock:** Connected facts and policies for the model.
- **Graph analytics:** Traversal, patterns, and communities.
- **Knowledge layer:** The NeoCarta semantic map.
- **Database:** Neo4j AuraDB or self-managed.
- **Authority:** Governed AWS data stays the source of truth.

## Neo4j Connection Patterns for AWS

These are five separate ways to connect. You do not need all of them. Pick the one that matches your job.

- **EMR:** Use it for large Spark workloads.
- **Glue:** Use it for managed ETL jobs.
- **MSK:** Use it for event streams.
- **Driver:** Use it when an application sends requests straight to Neo4j.
- **MCP:** Use it when an agent needs graph tools.

## Spark on Amazon EMR: A Two-Way Bridge to Neo4j

The Spark connector moves data between Spark and Neo4j in both directions.

- **Best use:** Large batch loads from S3 or Iceberg into the graph. It also pulls graph results back into Spark for analytics.
- **Batching:** The connector writes in batches. Each batch commits in its own transaction.
- **Custom Cypher:** Use it for reads and writes when the label and key options are too limited.
- **Version check:** Match the connector to the Spark version on your EMR release. Connector 5.x targets Spark 3.4 and 3.5. Connector 6.x targets Spark 4.

## AWS Glue Stays Tabular While Neo4j Receives Cypher

Glue lets your team keep working with tables. The connector turns SQL into Cypher for you.

- **Setup:** Upload the connector JAR to S3. Create a Glue custom connector with the driver class org.neo4j.jdbc.Neo4jDriver.
- **JDBC URL:** Add enableSQLTranslation=true so the driver translates SQL.
- **Credentials:** Store the Neo4j login in Secrets Manager.
- **Limit:** The driver translates only the SQL constructs it supports.
- **When to pick Glue:** Use it for managed, visual ETL.
- **When to pick EMR:** Use Spark on EMR for custom Cypher or very large batches.

## Neo4j in AWS

This diagram shows where Neo4j runs inside AWS.

- **Next slide:** It lists the deployment options, managed and self-managed.

## Neo4j Supports Managed and Self-Managed AWS Deployment

You can run Neo4j managed or self-managed on AWS.

- **AuraDB:** Neo4j's managed database, in an AWS region that fits the workload.
- **Marketplace:** Buy eligible Aura plans through AWS billing.
- **PrivateLink:** Private connectivity works with supported Aura enterprise configurations.
- **Self-managed:** Run Neo4j on EKS or EC2 when you manage the runtime.

## A Combined Architecture: Graph Plus Lakehouse

This pattern is for teams that already have a lakehouse. The graph sits next to it.

- **Lakehouse:** It keeps the high-volume tables and answers counting questions.
- **Graph:** It adds relationships, rules, and provenance, which tables model poorly.
- **Link:** Shared identifiers tie the two stores together.

## Dual Data Architecture: Lakehouse + Graph

Two stores sit side by side. Each answers the questions it handles best.

- **Lakehouse:** S3 Tables and Athena hold high-volume Iceberg tables. They answer totals, trends, and forecasts. Glue Data Catalog and Lake Formation govern them.
- **Graph:** Neo4j Aura holds accounts, transactions, alerts, policies, cases, customers, and devices. It answers multi-hop questions.
- **Pipeline:** Glue ETL or application services move entities and relationships into the graph. Graph results and features flow back.
- **Link:** Shared stable IDs tie the two sides together.

## Decision Table: SQL vs. Cypher

Use this table to decide where a question should run.

- **Hops:** One or two fixed joins stay in SQL. Three or more, or a variable depth, move to Cypher.
- **Query shape:** Known at design time fits SQL. Shape that depends on the data fits Cypher.
- **Result:** Numbers fit SQL. Paths and subgraphs fit Cypher.
- **Latency:** Batch fits SQL. Sub-second interactive work fits Cypher.
- **Volume:** Millions of rows scanned fit SQL. Thousands of entities traversed fit Cypher.
- **Rule:** Counting stays in SQL. Following connections moves to the graph.

## Virtual Graph for AWS

Virtual Graph lets you query tables as a graph without copying them.

- **Status:** The AWS version is planned.
- **Next:** The product overview, then the planned AWS query path.

## Virtual Graph: Query Your Data Lakehouse as a Graph

Virtual Graph translates Cypher to SQL and pushes the query down to your data lakehouse.

- **No ETL:** Data stays where it is.
- **Schema map:** It maps a graph model over your tables.
- **Composite queries:** One Cypher statement can combine lakehouse data with native Neo4j graphs.
- **Pushdown:** The computation runs where the data lives.
- **Protocols:** Bolt and JDBC work, so existing tools stay the same.
- **Governance:** Your existing security policies apply.
- **Sources today:** Databricks, Snowflake, and others.

## Planned AWS Query Path: Cypher Through Athena to S3 Tables

This is the planned AWS path for a Cypher query.

- **Steps:** Cypher goes to Virtual Graph, then Athena, then S3 Tables.
- **Benefit:** The query reads current data. Neo4j holds no second copy.
- **Next slide:** What each component does.

## What Each Component Does in the Virtual Graph Path

Virtual Graph lets you query S3 Tables with Cypher. The data stays in S3.

- **Status:** The AWS path is planned. Public preview covers Snowflake, Databricks, and Google BigQuery today.
- **Flow:** Cypher becomes SQL, Athena runs it, and the rows come back as a Cypher result.

Sources: https://neo4j.com/blog/auradb/neo4j-virtual-graph-is-now-in-public-preview/,
https://docs.aws.amazon.com/athena/latest/ug/gdc-register-s3-table-bucket-cat.html,
and https://docs.aws.amazon.com/glue/latest/dg/enable-s3-tables-catalog-integration.html

## Choose the Execution Path That Fits the Workload

Pick the path that matches the workload.

- **Current data, no copy:** Use Virtual Graph. Athena runs the query. This path is planned.
- **Frequent, low-latency traversals or graph algorithms:** Load the selected data into Neo4j. Neo4j runs Cypher on the stored graph.

## Connecting Amazon Quick and Neo4j with MCP

This section connects Neo4j to Amazon Quick through MCP.

- **Order:** What MCP is, the Neo4j tools, how the server is hosted, then Quick itself.

## Model Context Protocol (MCP)

MCP is an open standard. It gives agents one way to find and use tools.

- **Client:** The assistant or agent asks the server which tools it has.
- **MCP server:** It translates between the protocol and the native API.
- **Data source:** Neo4j, a REST API, or a file system.
- **Benefit:** Any MCP client works with any MCP server.

## Neo4j MCP Server Tools

The server runs in read-only mode and offers two tools.

- **get_neo4j_schema:** Returns labels, relationship types, and properties in a format that uses few tokens.
- **read_neo4j_cypher:** Runs a read-only Cypher query. It runs EXPLAIN first and rejects writes such as CREATE, MERGE, DELETE, and SET.
- **Discovery:** The client finds both tools through MCP. It reads the schema before it writes Cypher.

## Gateway Request Flow

The client never holds Neo4j credentials. It only talks to the Gateway.

- **Cognito:** It trades a client ID and secret for a JWT.
- **Gateway:** It checks the JWT and sends each tool call to the runtime. It also gets its own OAuth token for the runtime, so callers see one endpoint.
- **Runtime:** It hosts the read-only Neo4j MCP Server over Streamable HTTP.
- **Secrets Manager:** It stores the Neo4j password. The runtime receives it at deploy time.
- **Deploy:** ./deploy.py builds the ARM64 image, pushes it to ECR, and deploys the CDK stack. The code is in neo4j-mcp-server/.
- **Credentials:** ./deploy.py credentials writes the Gateway URL, client ID, client secret, and token URL. The Quick connection slide uses them.

## What Amazon Quick Is

Business users already ask their questions in Quick. That makes it the natural front door for graph context.

- **Naming:** Amazon Quick is the new name for Amazon Q Business. Quick Sight is the BI part of Quick.
- **Amazon Q Developer:** It is a separate product. This rename does not change it.
- **MCP:** It is the door that Neo4j comes through.

## Registering Neo4j MCP in Amazon Quick

The Neo4j MCP server from the deployment slide works in Quick without changes.

- **Setup:** Point Quick at the AgentCore Gateway URL. Do this in the console. This repository does not script it.
- **Credentials:** The file from ./deploy.py credentials holds the client ID, client secret, and token URL that Quick asks for.

Limits to plan for:
- **Subscription:** MCP integration needs Quick Enterprise.
- **Servers:** Quick supports remote servers only. Use Streamable HTTP instead of SSE.
- **Timeout:** Each MCP operation stops after 60 seconds. Keep Cypher tools bounded.
- **Tool count:** Quick registers up to 100 tools per MCP server.
- **Headers:** Quick sends no custom HTTP headers. Authentication must use OAuth.
- **New tools:** Custom connectors do not pick up new tools by themselves. The owner chooses Sync after the server changes.

## One Fraud Investigation in Amazon Quick

This example ties back to the SQL versus Cypher slide.

- **Counting:** Athena and Quick Sight count the activity.
- **Connections:** The Neo4j MCP tools follow the links between accounts.
- **Analyst view:** The analyst stays in Quick. The Gateway and MCP server own database access, so the analyst needs no Neo4j credentials.

Source: demos/fraud-amazon-quick/README.md.

## Building GraphRAG Agents on AWS

This section shows how to give an agent graph-based retrieval.

- **Problem:** Plain RAG adds noise to the context.
- **Fix:** GraphRAG patterns, built as agent tools.
- **After that:** Memory.

## Context Rot: More Context, Worse Answers

More context can make answers worse.

- **Similar is not relevant:** RAG retrieves chunks that look alike, and some of them do not help.
- **Noise:** Those chunks fill the context window with loosely related text.
- **Effect:** The model gets confused or misled, so the answer quality drops.
- **Next slide:** GraphRAG follows connections to related facts instead of adding more look-alike text.

## The Shift to GraphRAG

GraphRAG adds one step after vector search. It follows links to connected facts.

- **Traversal:** The graph walks from the matched text to related facts.
- **Stored links:** The graph records how facts connect, such as which account a transaction belongs to.
- **Verifiable:** The graph holds facts you can check.
- **Traceable:** Every answer walks back to its source document.
- **Fewer tokens:** The agent gets the facts it needs and nothing else.

## Three Ways Neo4j GraphRAG Helps Agents

The graph helps an agent in three ways.

- **Grounded retrieval:** A request such as "find the account at 742 Evergreen Terrace" matches a chunk of text. The graph resolves it to the verified account node ACC-1001.
- **Connected reasoning:** One query follows stored relationships from the account to its alert and its escalation policy.
- **Right-sized context:** The graph returns only the slice the question needs. In this example that is 4 nodes and 4 relationships.
- **Agent:** A Strands agent on Claude in Bedrock calls a GraphRAG retrieval tool backed by Neo4j.

## GraphRAG Patterns

Four patterns cover most GraphRAG builds. All four use the same graph.

- **Vector search:** Find passages close in meaning to the question. Narrow them with graph and metadata filters.
- **Hybrid search:** Combine vector search with full-text keyword search.
- **Query generation:** The system writes Cypher on the fly. This is also called text-to-Cypher.
- **Graph enrichment:** Add community summaries, graph embeddings, and PageRank scores.
- **Next slide:** A walk through the vector plus Cypher flow.

## How Vector Cypher Retrieval Enriches Fraud Investigation

Vector similarity finds the text. Reviewed Cypher adds the connected facts.

1. **Ask:** A Strands agent sends a question, such as which accounts share an address with ACC-1001 and which policy governs escalation.
2. **Embed:** Amazon Nova 2 Multimodal Embeddings on Bedrock embeds the question. It uses the same embedding contract as the stored chunks.
3. **Retrieve:** VectorCypherRetriever finds a Chunk. Reviewed Cypher expands it through fixed paths and returns fixed fields.
4. **Enrich:** The result holds the account, alerts, policy, source filename, and matched text. Provenance shows where each fact came from.
5. **Answer:** Claude on Bedrock answers from the returned facts.

## GraphRAG Becomes a Strands Agent Tool

The audience already knows Strands. Each GraphRAG pattern becomes one tool.

- **Tool examples:** Vector search plus traversal, text-to-Cypher, or a GDS-backed query.
- **Focused results:** The tool returns a small result. This keeps the context clean and answers the context rot problem from the start of the section.

## Agent Memory with Neo4j

Tools answer the current question. Memory keeps context across turns and sessions.

- **Next:** The context graph, what memory stores, and why a graph fits.

## A Context Graph Is Persistent Connected Memory for Agents

Most agents forget everything between sessions until you design memory on purpose.

- **Short-term state:** It lets the agent answer "what's the current balance?" after you already named an account.
- **Long-term knowledge:** It holds facts and preferences that outlive one conversation. It also records what changed and when.
- **Reasoning memory:** It keeps the tool calls, decisions, and outcomes. This is evidence for debugging and review.

Sources: https://neo4j.com/blog/agentic-ai/what-is-context-graph/,
https://neo4j.com/blog/agentic-ai/context-graph-ai-agent-memory/, and
https://neo4j.com/blog/agentic-ai/hands-on-with-context-graphs-and-neo4j/

## Context Graph: Three Kinds of Memory

The context graph is persistent, shared, and queryable. It holds three kinds of memory.

- **Long-term knowledge:** What the enterprise knows. Entities, relations, meaning, policy, and authoritative facts.
- **Short-term state:** What is happening now. The conversation, the user, the task, the workflow, and tool observations.
- **Reasoning memory:** Why decisions were made. Situation, action, rationale, outcome, precedents, and traces.
- **Selection:** The user, task, and workflow decide which context is relevant for each request.

## Agent Memory Preserves Facts, Context, and Reasoning

The agent memory library stores facts, context, and reasoning in the graph.

- **POLE+O:** The long-term model. It covers Person, Object, Location, Event, and Organization.
- **Temporal validity:** The graph records when a fact was true.

Source: https://github.com/neo4j-labs/agent-memory

## Why Graphs for Agent Memory

A graph suits agent memory because memory is full of links.

- **Relationships:** A conversation, a preference, and a transaction can point to the same real-world record.
- **Multi-hop:** One query combines memory with domain facts. The application does not join separate stores.
- **Provenance:** A memory points back to the source that produced it.
- **One record:** A single canonical record collects facts, conversations, preferences, and actions.
- **Per-user scope:** Each user's memory stays isolated across sessions.
- **History:** New memory supersedes old memory. The correction path stays.
- **Store deliberately:** Entity extraction finds what a turn is about. Policy or confirmation decides what becomes durable.

## Example: The Fraud Memory Agent

This demo captures memory. It does not feed recalled memory back into prompts.

- **Why:** A shared NAMS workspace stays safe during synthetic multi-user load runs.
- **Recall:** The library supports recall. This demo does not show it.

Source: demos/fraud-amazon-quick/fraud-memory-agent/README.md and
server/runtime_app.py.

## These Capabilities Meet Inside an AWS-Hosted Agent Workflow

This slide puts the pieces together in one agent workflow.

- **Gateway:** It protects tool traffic with OAuth 2.0.
- **Targets:** They enforce data access.

Sources: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html
and https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html

## Together, Connected Knowledge Grounds the AWS Agent Stack

This is the full stack from the start of the talk, now with every piece explained.

- **AWS:** It stores, governs, and analyzes the data. It also hosts the models and agents.
- **Neo4j:** It adds MCP tools, connected facts, graph analytics, and agent memory.
- **Result:** Agents answer from connected, governed knowledge.

## Takeaways

Four points to remember.

- **Connect:** AWS stores, governs, and analyzes the data. Neo4j follows the relationships in it.
- **Context rot:** Vector search finds the starting point. A reviewed traversal returns only the connected facts.
- **Agent tool:** Strands agents on Bedrock call GraphRAG directly or through Neo4j MCP on AgentCore Gateway.
- **Memory:** Conversations, entities, and reasoning traces stay connected across sessions.
