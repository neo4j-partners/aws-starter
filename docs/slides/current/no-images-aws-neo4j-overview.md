---
marp: true
theme: default
paginate: true
---

<style>
section {
  --marp-auto-scaling-code: false;
}

li {
  opacity: 1 !important;
  animation: none !important;
  visibility: visible !important;
}

/* Disable all fragment animations */
.marp-fragment {
  opacity: 1 !important;
  visibility: visible !important;
}

ul > li,
ol > li {
  opacity: 1 !important;
}
</style>

# Neo4j + AWS

Grounding Generative AI in Graph Data

---

## Neo4j Graph Intelligence Platform

What Neo4j is, and why connected data matters.

---

## What Is a Graph Database

Three structures, and that is the whole model:

- **Node:** a thing, such as a person, an account, a merchant, or a document.
- **Relationship:** a named, directed connection between two nodes.
- **Property:** a named value stored on a node or on a relationship.
- **Cypher:** Neo4j's query language for these patterns. Think of it like SQL, but built to match connected paths instead of joining separate tables.

The relationship is stored, not computed. Following one is a direct hop, not a join, so the cost of a hop does not grow with the size of the data on the other side.

---

## Why a Knowledge Graph Fits Fraud Investigations

- **See the full network:** connect customers, accounts, devices, addresses, merchants, alerts, and cases in one view.
- **Find hidden relationships:** reveal shared identifiers and indirect connections that isolated transactions do not show.
- **Follow the money:** trace transfers across any number of accounts without knowing the chain length in advance.
- **Explain why a pattern matters:** link suspicious activity to known fraud typologies, policies, KYC documents, and prior cases.
- **Adapt as schemes change:** add new entities and connections without rebuilding a rigid relational model.

**Investigator value:** move from isolated transactions to an evidence-backed view of who is connected, how money moved, and why the pattern matters.

---

## From Silos to Connected Context

Separate systems each hold one piece of the picture. A graph connects them, so hidden context becomes visible.

- **Employees:** talent development, career management, and knowing who is who in the organization.
- **Network & security:** identity and access management, identity resolution, reputation scoring, and threat detection.
- **Suppliers:** route planning, real-time supply chain visibility, and risk analysis.
- **Process, product, transactions, and customers:** the same connected approach applies to process improvement, product recommendations, fraud detection, and customer loyalty.

---

## Graph Makes It Easy to Explore Hidden Patterns

A graph lets you ask three kinds of questions directly against connected data.

- **What's important:** find the most central or influential node in a network, such as the most connected account.
- **What's unusual:** spot outliers, such as one address linked to multiple accounts and identifiers that other customers do not share.
- **What's next:** predict a likely new connection, such as flagging a transfer path that matches a known fraud typology.

---

## AWS + Neo4j: Connected Context for Grounded Enterprise AI

Neo4j graph, knowledge, and memory integrated with AWS data and agent services

---

## Select Neo4j and AWS Customers

Companies that use Neo4j and AWS together include Adobe, Financial Times, Meredith, AstraZeneca, Novo Nordisk, Volvo, Lyft, Verizon, Novartis, LendingClub, Lockheed Martin, Comcast, Cisco, Airbus, DB, Levi Strauss & Co., Caterpillar, and TAG IMF.

---

## AWS Provides the Foundation for Governed Enterprise AI

---

## Neo4j Adds Connected Context Across the AWS Platform

---

<style scoped>
table { font-size: 21px; }
</style>

## AWS Provides Scale, Neo4j Provides Connected Context

| AWS | Neo4j |
| --- | --- |
| **Store:** Keep authoritative records, documents, tables, and operational history. | **Connect:** Represent important entities, relationships, and investigation context. |
| **Govern:** Control access through catalogs, policies, identities, and platform services. | **Explain:** Link data to business terms, policies, typologies, and prior decisions. |
| **Analyze:** Use SQL, Spark, streaming, and ML for activity at scale. | **Traverse:** Find paths, communities, shared identifiers, and network patterns. |
| **Run AI:** Supply models, agent runtimes, gateways, and application infrastructure. | **Ground AI:** Give agents connected facts, semantic routing, tools, and memory. |

---

<style scoped>
table { font-size: 21px; }
small { font-size: 16px; }
</style>

## Neo4j Connection Patterns for AWS

| Integration path | AWS home | Description |
| --- | --- | --- |
| **Neo4j Spark Connector** | Amazon EMR | Exchange data between Spark DataFrames and Neo4j graphs. |
| **Neo4j Connector for AWS Glue** | AWS Glue | Load data from AWS sources into Neo4j with managed ETL jobs. |
| **Neo4j Connector for Kafka** | Amazon MSK | Stream events into Neo4j and publish graph changes to Kafka. |
| **Neo4j drivers** | Lambda, ECS, EKS, EC2 | Connect new or existing AWS applications to Neo4j. |
| **Neo4j MCP tools** | Amazon Bedrock AgentCore and Strands Agents | Connect AWS-hosted agents to Neo4j graph retrieval tools. |

<small>Sources: [Neo4j Spark Connector](https://neo4j.com/docs/spark/current/), [Kafka Connector](https://neo4j.com/docs/kafka/current/), [connectors and drivers](https://neo4j.com/docs/connectors/), and [Neo4j MCP](https://neo4j.com/developer/genai-ecosystem/model-context-protocol-mcp/)</small>

---

## A Combined Architecture: Graph Plus Lakehouse

- **Amazon S3 Tables, Amazon Athena, and AWS Glue Data Catalog** hold and query high-volume analytic data as open Iceberg tables. AWS Lake Formation can govern access.
- **Neo4j Aura** holds the connected domain, GraphRAG paths, rules, provenance, and agent memory.
- **Stable identifiers connect both sides**, through an ETL pipeline or application services.
- **Each store does the job it's good at:** Athena scans and totals rows. Neo4j follows relationships and returns focused context.

---

## Decision Table: SQL vs. Cypher

| Signal | Stay in SQL | Move to Cypher |
|--------|-------------|----------------|
| Number of hops | 1 to 2 fixed joins | 3+ or variable depth |
| Query shape | Known at design time | Depends on the data encountered |
| Result type | Aggregated numbers | Paths, subgraphs, connected components |
| Latency requirement | Batch is fine | Sub-second for interactive investigation |
| Data volume per query | Millions of rows scanned | Thousands of entities traversed |

- **Athena in SQL:** aggregates transaction activity, computes P95 thresholds, and ranks the accounts generating the most alerts.
- **Cypher in Neo4j:** follows funds across accounts and devices, finds circular transfers, and reaches everything downstream of a compromised account.

**The rule of thumb:** if you are counting things, stay in SQL. If you are following connections, move to the graph.

---

## One Investigation Uses Both Data Paths

1. **Detect in AWS:** SQL in Athena flags unusual transactions, accounts, or merchants in governed S3 data.
2. **Expand in Neo4j:** the investigation starts from those identifiers and traverses the connected network.
3. **Find the pattern:** Cypher detects shared identities, circular transfers, and exposed entities, such as the ACC-1001 ⇄ ACC-2047 ring from earlier.
4. **Explain the finding:** policies, fraud typologies, KYC documents, and prior cases establish significance.
5. **Return the result:** graph findings flow back to AWS for analytics, reporting, and case workflows.

**Combined outcome:** AWS supplies authoritative activity. Neo4j supplies the connected context needed to investigate it.

---

## Building GraphRAG Agents on AWS

---

## Context Rot: More Context, Worse Answers

Too much irrelevant context **degrades** LLM performance.

- RAG retrieves chunks that are *similar*, not *relevant*.
- The context window fills with tangential noise.
- The model gets distracted or misled.

"Context rot": retrieval of tangents that rots response quality. This is the problem GraphRAG's traversal step is built to avoid.

---

## The Shift to GraphRAG

- **One step past vector search:** a graph traversal follows the matched text to the facts connected to it.
- **Stored links:** the graph records how facts connect, such as which account a transaction belongs to.
- **Connected, verifiable facts:** the graph stores facts you can check, not just pattern-matched chunks of text.
- **Traceable:** every answer can walk back to the document behind it.
- **Fewer tokens:** the agent receives the facts an answer needs, not everything that looked similar.

The agent answers from evidence the graph can defend.

---

## How Graph-Enriched Retrieval Works

One retrieval call, two steps:

- **Step 1, search:** the question is matched against stored text to find the closest starting point.
- **Step 2, traversal:** a reviewed query follows relationships out from that starting point to connected facts.
- **Two decisions, two owners:** search decides where the answer starts. The traversal decides what comes back with it.

---

## GraphRAG Patterns

Four patterns for building GraphRAG, all built around one graph.

- **Vector search:** the system finds the passages closest in meaning to the question, then narrows them with graph and metadata filters.
- **Hybrid search:** the system combines vector search with full-text keyword search.
- **Query generation:** the system writes Cypher queries dynamically, also called text-to-Cypher.
- **Graph enrichment:** the system adds community summaries, graph embeddings, and PageRank scores to improve results.

---

## GraphRAG Becomes a Strands Agent Tool

- **GraphRAG patterns fit as tools:** Each GraphRAG pattern can be wrapped as a Strands tool. The agent calls it to pull connected context into the conversation.
- **Deploy to AgentCore:** A finished Strands agent deploys to AgentCore Runtime. AgentCore Gateway can expose Neo4j MCP tools to it.
- **The model picks, the tool governs:** The model decides when to call the tool. The tool's reviewed Cypher decides what data comes back.
- **Focused results:** The tool returns a small, bounded result, so the agent's context stays clean.

---

## Agent Memory with Neo4j

Tools answer the current question. Memory carries context across turns and sessions.

---

## Three Layers of Agent Memory

- **Short-term memory:** conversation history, session state, and the entities mentioned in each turn. This is what lets an agent resolve "what's the current balance?" after an account was already named.
- **Long-term memory:** durable facts and preferences that should outlive one conversation, plus a record of what changed and when.
- **Reasoning memory:** the tool calls, decisions, and outcomes an agent produced. This is evidence for debugging and review.

Most agents are stateless until memory is designed on purpose.

---

## Agent Memory Preserves Facts, Context, and Reasoning

**Long-term model:** POLE+O represents Person, Object, Location, Event, and Organization. Temporal validity records when a fact was true.

---

## Why Graphs for Agent Memory

- **Relationships are first-class.** A conversation, a preference, and a transaction can all point to the same real-world record.
- **Multi-hop queries combine memory with domain facts** without joining separate data stores in application code.
- **Provenance stays traversable.** A stored memory can point back to the exact source that produced it.
- **Graph identity prevents copies.** One canonical record accumulates facts, conversations, preferences, and actions instead of scattering them.
- **Memory is scoped to individual users.** Each user's memory stays isolated across sessions.

---

## Example: The Fraud Memory Agent

The agent uses **NAMS**, the Neo4j Hosted Agent Memory Service.

- **Every turn is captured:** The agent records each user and assistant message in NAMS, tagged with the user and session.
- **Entities are extracted:** NAMS extracts entities from each message on the server side.
- **Tool calls become reasoning traces:** Each MCP tool call is saved as a step in a reasoning trace.
- **Graph and memory stay separate:** The Neo4j MCP server owns access to the fraud graph, and NAMS owns memory storage. The agent holds no Neo4j credentials.

---

## Takeaways

- **Neo4j connects what AWS stores:** AWS stores, governs, and analyzes the data. Neo4j follows the relationships in it.
- **GraphRAG counters context rot:** Vector search finds the starting point. A reviewed traversal returns only the connected facts.
- **GraphRAG is an agent tool:** Strands agents on Bedrock call it directly or through Neo4j MCP on AgentCore Gateway.
- **Graph memory persists:** Conversations, entities, and reasoning traces stay connected and inspectable across sessions.
