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

section.knowledge-slide {
  padding: 40px 56px;
}

section.knowledge-slide h2 {
  margin-bottom: 8px;
}

section.knowledge-slide .overview {
  color: #475569;
  font-size: 23px;
  margin: 0 0 12px;
}

section.knowledge-slide .cols {
  align-items: center;
  gap: 24px;
  grid-template-columns: 0.95fr 1.05fr;
}

section.knowledge-slide ul {
  font-size: 21px;
  margin: 4px 0 0;
  padding-left: 24px;
}

section.knowledge-slide li {
  margin: 9px 0;
}

section.knowledge-slide img {
  display: block;
  margin: 0 auto;
}

section.knowledge-slide pre {
  background: #f8fafc;
  border: 2px solid #cbd5e1;
  border-radius: 14px;
  padding: 18px;
}

li {
  opacity: 1 !important;
  visibility: visible !important;
}
</style>

<!-- _class: lead -->

# AWS + Neo4j: Connected Context for Grounded Enterprise AI

## Place Neo4j graph, knowledge, and memory beside AWS data and agent services

<div class="promise">A field guide for architecture conversations, connected investigations, and co-sell motions</div>

---

## AWS provides the foundation for governed enterprise AI

![w:1160](./aws-neo4j-layer-map.svg#aws)

---

## Neo4j adds connected context across the AWS platform

![w:1160](./aws-neo4j-layer-map.svg#neo4j)

---

## AWS provides cloud-scale services; Neo4j provides connected context

| AWS | Neo4j |
| --- | --- |
| **Store:** Keep authoritative records, documents, tables, and operational history. | **Connect:** Represent important entities, relationships, and investigation context. |
| **Govern:** Control access through catalogs, policies, identities, and platform services. | **Explain:** Link data to business terms, policies, typologies, and prior decisions. |
| **Analyze:** Use SQL, Spark, streaming, and ML for activity at scale. | **Traverse:** Find paths, communities, shared identifiers, and network patterns. |
| **Run AI:** Supply models, agent runtimes, gateways, and application infrastructure. | **Ground AI:** Give agents connected facts, semantic routing, tools, and memory. |

---

## Neo4j connection patterns for AWS

| Integration path | AWS home | Description |
| --- | --- | --- |
| **Neo4j Spark Connector** | Amazon EMR | Exchange data between Spark DataFrames and Neo4j graphs. |
| **Neo4j Connector for AWS Glue** | AWS Glue | Load data from AWS sources into Neo4j with managed ETL jobs. |
| **Neo4j Connector for Kafka** | Amazon MSK | Stream events into Neo4j and publish graph changes to Kafka. |
| **Neo4j drivers** | Lambda, ECS, EKS, EC2 | Connect new or existing AWS applications to Neo4j. |
| **Neo4j MCP tools** | AgentCore and Strands | Connect AWS-hosted agents to Neo4j graph retrieval tools. |

<small>Sources: [Neo4j Spark Connector](https://neo4j.com/docs/spark/current/), [Kafka Connector](https://neo4j.com/docs/kafka/current/), [connectors and drivers](https://neo4j.com/docs/connectors/), and [Neo4j MCP](https://neo4j.com/developer/genai-ecosystem/model-context-protocol-mcp/)</small>

---

![bg contain](./neo4j%20in%20aws.svg)

---

<!-- _class: lead -->

# Enterprise Knowledge Layer

---

<!-- _class: knowledge-slide -->

## A shared Knowledge Layer makes connected context reusable

<p class="overview">Keep meaning in one governed layer so every agent uses consistent definitions and rules.</p>

<div class="cols">
<div>

- **Knowledge Layer:** Provides one governed place for enterprise knowledge.
- **Business meaning:** Defines shared terms, relationships, and rules.
- **Connected context:** Links concepts to data, policies, owners, and processes.
- **Lighter agents:** Query the shared layer when they need context.

</div>
<div>

![h:430](./knowledge-layer-lighter-agents-compact.svg)

</div>
</div>

<!-- Source: /Users/ryanknight/projects/cloud-integration/knowledge-layer/reference/knowledge-layer-official.md -->

---

<!-- _class: knowledge-slide -->

## Three parts ground every answer

<p class="overview">Combine business meaning, enterprise data, and past experience.</p>

<div class="cols">
<div>

- **Knowledge Layer ontology:** Connects business concepts to systems, processes, policies, and owners.
- **Enterprise data:** Supplies governed facts from authoritative systems.
- **Memory:** Stores previous actions, decisions, and results.
- **Decision trace:** Records the evidence and reasoning behind each result.

</div>
<div>

![h:430](./knowledge-layer-three-parts-compact.svg)

</div>
</div>

<!-- Source: /Users/ryanknight/projects/cloud-integration/knowledge-layer/reference/knowledge-layer-official.md -->

---

<!-- _class: knowledge-slide -->

## The Knowledge Layer turns each request into a governed action plan

<p class="overview">The layer grounds the request. The agent or application executes the plan.</p>

<div class="cols">
<div>

- **Interpret intent:** Resolve the business meaning of the request.
- **Select sources and tools:** Choose authoritative systems and generate their queries.
- **Apply policy:** Limit the plan to permitted data and actions.
- **Explain result:** Return the sources, evidence, and decision path.
- **Update memory:** Store useful outcomes for future requests.

</div>
<div>

![h:430](./knowledge-layer-request-flow-compact.svg)

</div>
</div>

<!-- Source: /Users/ryanknight/projects/cloud-integration/knowledge-layer/reference/knowledge-layer-official.md -->

---

<!-- _class: knowledge-slide -->

## Start with meaning, then add data and memory

<p class="overview">Begin with shared meaning and mappings. Add graph data and memory when the use case needs them.</p>

<div class="cols">
<div>

- **Ontology-Based Semantic Layer:** Defines concepts, maps sources, and routes tools.
- **Query in place:** Keeps AWS data in its source system.
- **Materialized data:** Stores repeated or graph-heavy data in Neo4j when speed matters.
- **Memory:** Uses prior decisions to improve future actions.

</div>
<div>

```text
Ontology-Based Semantic Layer
  meaning + mappings + tools
              ↓
   query external data in place
              ↓
   add graph data when useful
              ↓
     add memory over time
              ↓
    full Knowledge Layer
```

</div>
</div>

<!-- Source: /Users/ryanknight/projects/cloud-integration/knowledge-layer/reference/knowledge-layer-official.md -->

---

## Policy and prior decisions make each result explainable

```text
Finding → business meaning → policy → prior decision → evidence
```

- **Explain the result:** Link each finding to its meaning, policy, and evidence.
- **Reuse prior work:** Find similar decisions, evidence, and outcomes.
- **Keep the path inspectable:** Let reviewers trace each answer back to governed sources.

| Adjacent AWS capability | What Neo4j adds |
| --- | --- |
| **Amazon Bedrock Knowledge Bases** retrieves relevant passages from documents. | **Enterprise Knowledge Layer** queries connected business concepts, relationships, provenance, and prior decisions. |

---

<!-- _class: lead -->

# Agent Memory

## Make facts, relationships, decisions, and evidence reusable across agent interactions

---

## Agent Memory preserves facts, context, and reasoning

![w:760](./neo4j-agent-memory-diagram.svg)

<div class="callout"><strong>Long-term model:</strong> POLE+O represents Person, Object, Location, Event, and Organization. Temporal validity records when a fact was true.</div>

<!-- Source: https://github.com/neo4j-labs/agent-memory -->

---

## Neo4j Agent Memory

The [Neo4j Labs agent-memory](https://neo4j.com/labs/agent-memory/) library backs agent memory with a graph.

- **Three memory types:** Short-term conversations, long-term knowledge using the [POLE+O model](https://neo4j.com/labs/agent-memory/explanation/poleo-model), and reasoning traces.
- **Entity resolution:** Extracts and deduplicates entities instead of accumulating append-only blobs.
- **Per-user scoping:** The core API's `user_identifier=` isolates memory for each user across sessions.
- **Pluggable:** Integrates with Strands, LangChain, other frameworks, and an MCP server.

<!-- Source: docs/slides/archive/aws-in-depth/01-neo4j-for-agentic-ai-slides.md -->

---

## Example: The Finance Agent

`neo4j-agentcore-agents/finance-agent` wires memory into a Strands agent as tools.

- **`core/memory.py`:** Provides a user-scoped wrapper around the library's context-graph tools.
- **Four tools:** `search_context`, `add_memory`, `get_user_preferences`, and `get_entity_graph`.
- **Per-user isolation:** Every write links a `:User` node; recall stays scoped to that user across sessions.
- **Graph through MCP:** Reaches Neo4j through the MCP server and AgentCore Gateway with OAuth 2.0 and an automatically refreshed token.
- **One graph stack:** Memory lives in Neo4j alongside the domain knowledge graph.

<!-- Source: docs/slides/archive/aws-in-depth/01-neo4j-for-agentic-ai-slides.md -->

---

## Graph memory makes each result inspectable and reusable

- **Short-term memory:** Keep the active conversation and investigation session.
- **Long-term memory:** Store entities, facts, relationships, and temporal context.
- **Reasoning memory:** Record tool calls, evidence, decision traces, and feedback.
- **Reusable outcomes:** Connect a confirmed result to the policies, patterns, and evidence that supported it.

| Adjacent AWS capability | What Neo4j adds |
| --- | --- |
| **AgentCore Memory** provides managed short-term and long-term memory for AWS agents. | **Neo4j Agent Memory** makes entities, relationships, temporal facts, and reasoning traces directly traversable. |

<div class="callout"><strong>Integration:</strong> Use the Strands Agents SDK integration to add graph-native memory to an AWS agent.</div>

---

## These capabilities meet inside an AWS-hosted agent workflow

![w:1160](./aws-hosted-agent-knowledge-layer-workflow.svg)

<div class="callout"><strong>Security boundary:</strong> AgentCore Gateway manages tool access and OAuth 2.0. Each source service enforces data access.</div>

---

<!-- _class: lead -->

# Virtual Graph

## Query connected views of governed AWS data without moving every record into Neo4j

---

![bg contain](./virtual-graph.png)

---

## Virtual Graph will extend Cypher to governed AWS tables in place

```text
Cypher question
      ↓
Virtual graph model
      ↓ translates traversal into SQL
      ↓
S3 Tables with Apache Iceberg + AWS Glue Data Catalog
      ↓
Connected result without a full data copy
```

- **Athena and Redshift Spectrum:** Use SQL to query data in external sources.
- **Virtual Graph:** Presents a graph model, accepts Cypher, and translates the traversal into SQL against the source tables.
- **Governance:** Keeps AWS tables and catalog controls in the query path.

<div class="callout"><span class="status-preview">Available in public preview:</span> Snowflake, Databricks, and Google BigQuery. <span class="status-roadmap">In build for AWS:</span> S3 Tables and Glue Data Catalog support.</div>

<!-- Source: https://neo4j.com/blog/auradb/neo4j-virtual-graph-is-now-in-public-preview/ -->

---

## Virtual Graph fits inside a multi-tool knowledge layer

| Retrieval need | Route | Best fit |
| --- | --- | --- |
| **Fast connected context** | Cypher over the persisted Neo4j graph | Repeated traversal, graph patterns, and selected operational context |
| **AWS data in place**<br><span class="status-roadmap">Planned</span> | Cypher through Virtual Graph, translated to SQL | Connected questions over governed S3 Tables without a full copy |
| **Aggregate evidence** | SQL through Athena | Totals, trends, rankings, and time-window analysis |
| **Policy text** | Document retrieval | Passages from policies, playbooks, and regulatory guidance |
| **Operational action** | Enterprise API | Case updates, alerts, approvals, and workflow steps |

<div class="callout"><strong>Design rule:</strong> The knowledge layer selects the right path. Each source remains responsible for execution and access control.</div>

---

## Neo4j supports managed and self-managed AWS deployment

- **AuraDB on AWS:** Use Neo4j's managed graph database in an AWS region that fits the workload.
- **AWS Marketplace:** Purchase eligible Aura plans through AWS billing and marketplace terms.
- **Private connectivity:** Use AWS PrivateLink with supported Aura enterprise configurations.
- **Self-managed:** Deploy Neo4j on Amazon EKS or Amazon EC2 when the customer manages the runtime.
- **AgentCore regions:** AgentCore is generally available in nine AWS Regions, including `us-east-1` and `us-west-2`. Confirm feature-level availability for the target region.

<div class="callout"><strong>Field choice:</strong> Start with the customer's operating model, procurement path, networking controls, and region requirements.</div>

<small>Sources: [Aura through cloud marketplaces](https://neo4j.com/docs/aura/cloud-providers/), [Aura secure connections](https://neo4j.com/docs/aura/security/secure-connections/), and [AgentCore supported regions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html)</small>

---

## Start with one governed question that needs both views

1. **Find the question:** Choose one investigation that needs AWS transaction evidence and connected Neo4j context.
2. **Map the sources:** Identify the S3 tables, catalogs, graph entities, policies, and systems involved.
3. **Prove both paths:** Use Athena for activity and Cypher for connections in one evidence-backed answer.
4. **Review the result:** Add automated checks, investigator feedback, and policy review.
5. **Expand with evidence:** Reuse the proven pattern for the next valuable question.

<div class="callout"><strong>First customer motion:</strong> Ask, “Which governed investigation is slow today because transaction evidence and connected context live in separate places?”</div>

---

## Together, connected knowledge grounds the AWS agent stack

![w:1160](./aws-neo4j-layer-map.svg#complete)
