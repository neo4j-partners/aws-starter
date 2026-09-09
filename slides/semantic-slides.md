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

# Making Financial Data Easier to Investigate

## A connected knowledge layer links customers, accounts, transactions, fraud signals, and investigation guidance

---

## A Transaction Becomes Suspicious Because of Its Connections

One transfer may look ordinary. The surrounding pattern tells a different story.

```text
Customer A -> Account A -> Device X <- Account B <- Customer B

Account A -> Account B -> Account C -> Account A
```

- Two customers share a device even though their profiles appear unrelated
- Money moves through several accounts and returns to where it started
- The accounts also share phone numbers, addresses, or merchants

Fraud-ring detection is a connected-data problem, not only a transaction-scoring problem.

---

## AWS Stores and Analyzes Activity; Neo4j Reveals Connections

- **AWS SQL:** answers questions about numbers over time, such as transaction amounts, frequency, velocity, and risk scores.
- **Neo4j Cypher:** answers questions about connections, such as which customers, accounts, devices, merchants, and transfers form a suspicious pattern.
- **Together:** identify a connected pattern, then retrieve the transaction evidence needed to investigate it.

**Example:** Which accounts form a circular payment chain, and what activity makes that chain unusual?

---

## Neo4j Supplies Context; AWS Runs the AI Experience

| Platform | Role for generative AI |
| --- | --- |
| **Neo4j** | Keeps a connected picture of customers, accounts, fraud signals, investigation history, and the policies that explain them. |
| **Amazon Bedrock** | Provides managed access to foundation models that power an AI assistant's reasoning and responses. |
| **Strands Agents** | An open-source SDK for building and orchestrating AI assistants that use models and tools. |
| **Amazon Bedrock AgentCore** | Hosts and runs AI agents securely at scale, with isolated sessions and managed infrastructure. |

**Together:** Neo4j gives an AI assistant the right context. AWS provides the models and services that use it.

---

## Keep Transaction History and Connected Context in the Right Stores

![w:1150](./dual-data-architecture-aws.svg)

<!--
The architecture diagram shows financial data in Amazon S3 tables alongside a
Neo4j fraud knowledge graph. Policies, fraud typologies, and investigation guidance
give meaning to customers, accounts, identity signals, and suspicious relationships.
Selected graph findings can be written back to curated Amazon S3 results. The graph
complements, rather than replaces, systems of record.
-->

---

## AWS SQL Finds Unusual Financial Activity Over Time

- **Aggregation and trends:** calculates totals, counts, averages, and hourly or daily activity by customer, account, merchant, or channel.
- **Filtering and ranking:** finds accounts above velocity thresholds and merchants associated with the most flagged transactions.
- **Joins on keys:** connects customers, accounts, transactions, and merchants one relationship at a time.
- **Dashboards and reporting:** shows alert volumes, losses, review outcomes, and investigation workloads.

**Amazon Athena:** runs standard SQL against data in Amazon S3. **Amazon Timestream:** stores and analyzes data that changes over time.

<small>Sources: [Amazon Athena](https://docs.aws.amazon.com/athena/) and [Amazon Timestream for LiveAnalytics](https://docs.aws.amazon.com/timestream/latest/developerguide/what-is-timestream.html)</small>

---

## Neo4j Cypher Finds Patterns That Span Many Connections

- **Follow connections:** move from a customer to accounts, devices, phone numbers, addresses, merchants, and other customers.
- **Find a pattern:** identify circular transfers, shared identities, or coordinated activity across several accounts.
- **Understand reach:** show which other customers and accounts are connected to a suspicious signal.
- **Keep following:** explore as many relationships as an investigation requires without assembling a new chain of joins each time.
- **Use governed guidance:** link alerts and patterns to the policies, typologies, and investigation steps that explain them.

**Together:** AWS holds financial activity and operational records. Neo4j shows the connections and guidance that give those records meaning.

---

## The Knowledge Layer Maps Data to Its Meaning

It does not have to copy every raw transaction or source record.

| Graph concern | Examples |
| --- | --- |
| **Where data comes from** | Tables, payment systems, case tools, policies, and external data providers |
| **What the data means** | Customers, accounts, transactions, devices, merchants, alerts, cases, and rules |
| **How to find an answer** | Which sources to use and which questions each one can answer |
| **What past investigations taught us** | Evidence, quality checks, investigator feedback, outcomes, and proven steps |

The result connects an investigator's words to the data, policies, and tools that can answer the question.

---

## 1. Map the Financial Data Without Moving It

Create a map of where financial data lives and how it is organized while the source systems remain authoritative.

```text
S3 tables       -> customers / accounts / transactions / merchants
Identity system -> customer -> phone / address / device
Case platform   -> alert -> investigation -> outcome
Document set    -> policy -> fraud typology -> investigation playbook
```

- Keep the original systems as the trusted sources of data
- Capture how records relate to each other in the source data
- Add plain-language descriptions for account identifiers, transaction codes, channels, and risk flags

---

## 2. Give Fraud Data a Shared Vocabulary

Define the terms investigators use and show how those terms relate to data and policy.

It can be assembled from:

- Existing definitions for customers, accounts, transactions, alerts, cases, and fraud signals
- Fraud policies, regulatory guidance, typology libraries, investigation playbooks, query logs, and audit records
- Fraud-investigator and data-owner input where definitions or associations are unclear

Mapping the data and defining the shared vocabulary can happen independently.

---

## 3. Connect Each Question to Evidence and Guidance

Connect a fraud question to the data, rules, and investigation history that can answer it.

```text
Fraud pattern -> detection rule -> source system -> table / API / policy
```

One account can connect to several sources: its transactions, identity signals, device history, alerts, prior cases, and the policy that governs the investigation.

This makes financial data and investigation guidance discoverable in the language an investigator uses.

---

## 4. Give an AI Assistant Only the Context It Needs

For each new question, an AI assistant can:

1. Identify the relevant customers, accounts, transactions, fraud signals, and policies
2. Follow connections to related entities, data sources, guidance, and known investigations
3. Retrieve only the context needed for the investigation
4. Ask the selected source system for the required evidence
5. Construct a response that cites the returned evidence

Instead of giving the assistant every table and document, the knowledge layer supplies the information needed for that question.

---

## 5. Turn Each Investigation Into Reusable Knowledge

Each new question creates a record of how it was answered:

```text
Question: Which accounts may belong to the same fraud ring?
  -> relevant customers, accounts, and identity signals
  -> data sources and policies used
  -> transaction and graph evidence found
  -> response and investigator decision
  -> quality, timing, and outcome measures
```

Capture the evidence, decisions, feedback, elapsed time, and outcome at each step.

---

## Proven Investigations Make Future Answers Better

Later AI assistants can find similar questions and reuse the steps that worked.

- Reuse high-confidence ways of finding and checking evidence
- Skip redundant work and avoid approaches that produced poor results
- Improve a method when the evidence is incomplete or retrieval is too slow
- Give more weight to connections that repeatedly support confirmed outcomes

The connected knowledge layer becomes shared investigation memory, not a collection of isolated chat histories.

---

## Human Review Keeps Automated Assistance Accountable

| Feedback channel | What it contributes |
| --- | --- |
| **Automated quality check** | Tests whether an answer is supported, complete, and timely |
| **Investigator feedback** | Records whether the result was useful and what evidence was missing |
| **Fraud and compliance review** | Validates conclusions, adds context, and clarifies governed investigation guidance |

Keep rejected approaches with an explanation. They show what failed and why another method is preferred.

---

## Two Graph Approaches Solve Different Problems

Both approaches connect data, but they serve different purposes.

| Virtual graph: one view across existing data | Knowledge layer: helps people and AI investigate |
| --- | --- |
| Lets one query reach data that remains in several systems | Connects financial data, business meaning, policy, and instructions for finding evidence |
| Translates a graph query into the query each source system understands | Guides an AI assistant to use SQL, APIs, graph queries, or source-specific tools |
| Retrieves connected data without copying it first | Explains answers, selects sources, and learns from prior investigations |

A virtual graph can serve as one retrieval capability inside the knowledge layer.

---

## Keep Raw Transactions in Their Systems of Record

Start by mapping and linking records while transaction history remains in the systems designed to store and govern it.

Copy selected data into the graph only when an investigation needs:

- Repeated, fast traversal that querying the source systems cannot support
- Relationship analysis that is slow or difficult with tables and joins
- Connected features that support fraud detection, prioritization, or investigation

Copying data is a targeted performance choice, not a prerequisite for building the knowledge layer.

---

## Use Graph Analytics for Network-Level Fraud Signals

Keep community detection, centrality, similarity, and path analysis as dedicated graph analytics workloads.

```text
Persisted fraud graph
           -> In-memory view of a suspicious network
           -> Community, path, and influence analysis
           -> Ranked accounts and connections for review
```

The knowledge layer helps an AI assistant select an approved analysis, use validated parameters, explain the result, and reuse proven workflows.

---

## AWS and Neo4j Support Several Integration Paths

- **[Spark Connector on Amazon EMR](https://neo4j.com/docs/spark/current/):** moves Spark DataFrames into Neo4j and reads graph data back into Spark.
- **[AWS Glue Connector](https://neo4j.com/docs/connectors/):** builds managed ETL jobs from S3, RDS, Redshift, DynamoDB, and other Glue sources.
- **[Kafka Connector on Amazon MSK](https://neo4j.com/docs/kafka/current/):** streams transaction events into Neo4j and graph changes back to Kafka.
- **[Neo4j drivers](https://neo4j.com/docs/connectors/):** let Lambda, ECS, EKS, and EC2 services run Cypher queries.
- **[MCP for AWS agents](https://neo4j.com/developer/genai-ecosystem/model-context-protocol-mcp/):** lets Bedrock and AgentCore agents call graph tools.

---

## Start With One Investigation That Needs Both Views

1. Map the financial sources and how customers, accounts, transactions, and identity signals connect
2. Define the fraud signals, policies, and investigation outcomes in shared language
3. Start with one question: “Which accounts may belong to the same fraud ring, and what evidence connects them?”
4. Connect the graph pattern to transaction evidence in AWS
5. Add automated checks, investigator feedback, and compliance review
6. Reuse proven steps, and copy selected data into the graph only when performance requires it

Start with one governed fraud investigation, then expand the knowledge layer as more useful questions emerge.
