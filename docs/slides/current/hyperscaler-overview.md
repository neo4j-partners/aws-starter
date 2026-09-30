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

# Cloud Data and AI Stacks

AWS, Databricks, Google Cloud, IBM, and Microsoft

<!--
Overview talk. The arc runs from the stack all five vendors now sell, through
where the vendors differ, into the shifts that show up across all of them in
2026, and ends with where Neo4j fits.

Product names and status were checked against vendor pages on September 27,
2026. Names changed often in 2025 and 2026, so check again before reuse.

Source material: cloud-integration/hyperscaler.md.
-->

---

## The Shared Stack

Five vendors, one stack shape, different product names.

---

## Five Vendors Sell the Same Stack

- **Same layers:** Every vendor sells infrastructure, a lakehouse, operational data, context, agents, and apps.
- **Different names:** The product names differ, and many changed in 2025 and 2026.
- **Real differences:** The vendors differ most in table format, catalog, model choice, and where their products run.
- **Not only clouds:** Databricks runs on other vendors' clouds. IBM runs on its own cloud, other clouds, and on premises.

<!--
Databricks and IBM are not hyperscalers in the strict sense, but they follow
the same stack shape, so the comparison includes them.
-->

---

![bg contain](./images/hyperscaler-overview/cloud-ai-stack.svg)

<!--
Six layers in two groups. The three data layers store and run the company's
data. The three AI layers turn that data into answers and actions. Agent
governance runs across every layer.

Vendors now also build agents into their own services, such as an agent that
finds the cause of an outage. Each built-in agent belongs to the layer of the
service it runs in, so the stack keeps its six layers.
-->

---

## Data Layers Store and Run the Company's Data

- **Infrastructure:** Custom chips and NVIDIA GPUs train and run the models.
- **Lakehouse:** Open tables in object storage hold the data once. Many query engines read the same tables.
- **Operational data:** Databases and streams hold the present. The lakehouse holds the history.

<!--
An operational database stores the current state that an app changes many
times per second, such as an order or an agent session. A stream carries
events as they happen.
-->

---

## AI Layers Turn Data into Answers and Actions

- **Context:** The context layer stores what data means: metrics, business terms, and relationships.
- **Agents and models:** The agent platform hosts models and connects agents to tools and memory.
- **Apps:** Enterprise chat, coding assistants, and app builders put agents in front of people.
- **Agent governance:** Identity, registry, gateway, and policy span every layer.

<!--
Agents read the context layer before they query, so they pick the right table
and the right meaning. Vendors call it a context graph, an ontology, or a
semantic layer. Vendors call the governance pieces an agent control plane.
-->

---

## Four Questions Place Any Vendor on the Stack

1. **Find the data:** Where does the data live, and in which table format?
2. **Find the meaning:** Where do business definitions and relationships live?
3. **Find the agents:** Where are agents built, and which product governs them?
4. **Find the people:** Which tool do employees open every day?

<!--
Ask them in order. For the last question, the usual answers are Office, Slack,
a browser, or an IDE.
-->

---

## Where the Vendors Differ

Same layers, different defaults.

---

![bg contain](./images/hyperscaler-overview/vendor-differences.svg)

<!--
Walk the rows top to bottom.

- Table format: AWS, Google Cloud, and IBM default to Apache Iceberg.
  Microsoft defaults to Delta Lake and translates the metadata for outside
  Iceberg readers. Databricks manages both as equals.
- Catalog: Unity Catalog is the only one that governs data, models, agents,
  and MCP tools in one place. Google's Knowledge Catalog can federate to AWS
  Glue, Unity Catalog, and Snowflake, in Preview.
- Where it runs: AWS, Google Cloud, and Microsoft run on their own cloud.
  Databricks is multi-cloud. IBM is the only vendor here with an on-premises
  lakehouse edition.
- Models: Microsoft Foundry lists more than 10,000 models. Google Model
  Garden lists more than 200.
- Chat: Microsoft 365 Copilot lives inside the Office apps most companies
  already use. Gemini Enterprise also connects to Microsoft 365. watsonx
  Orchestrate targets IT leaders more than end users.
-->

---

## Table Format Matters Less, the Catalog Matters More

- **Iceberg first:** AWS, Google Cloud, and IBM store data in Apache Iceberg by default.
- **Delta first:** Microsoft stores data in Delta Lake and translates metadata for Iceberg readers.
- **Converging:** Databricks is moving Delta Lake 5.0 onto Iceberg's metadata design.
- **Common ground:** Every vendor now reads Iceberg, so format choice locks customers in less.

**The catalog now decides** who can write and govern the tables.

<!--
The last point is our inference from the vendor pages. Delta Lake 5.0 was
presented at Data + AI Summit 2026. It adopts the Iceberg v4 metadata tree,
so Delta and Iceberg clients will read and write one on-disk format. It has
not shipped yet: the Databricks Iceberg docs still list Iceberg v1 to v3.

OneLake translation limits: it writes Iceberg V2 only, handles Parquet only,
and skips tables with 5,000 or more commits.
-->

---

## Shifts Across All Five Vendors

The same moves show up at every vendor in 2026.

---

![bg contain](./images/hyperscaler-overview/shift-status.svg)

<!--
One view of where each shift stands. The next slides cover the shifts that
matter most for connected data: context graphs, control planes, MCP, and
memory.

"Announced" means the vendor announced the product, but the source does not
state a release status. Google rebuilt Gemini Cloud Assist around proactive
agents at Next '26 on April 22, 2026. IBM announced IBM Concert on May 5,
2026.
-->

---

## Every Vendor Is Building a Context Graph

- **Problem:** Agents give wrong answers when they pick the wrong table or meaning.
- **AWS:** AWS Context maps existing data into a knowledge graph for agents.
- **Databricks:** Genie Ontology is a "living context graph" behind Genie One and Genie Code.
- **Google Cloud:** Knowledge Catalog builds a "dynamic context graph" from all data.
- **Microsoft:** Fabric IQ holds an ontology of entities, relationships, and rules.
- **IBM:** Context in watsonx.data is a federated context layer.

<!--
An example of a wrong meaning is the term "revenue." AWS, Databricks, Google
Cloud, and Microsoft all describe their context layer as a graph.

- AWS Context is coming soon. Pieces available now: Glue Data Catalog
  business context is in preview, and S3 annotations are GA.
- Genie Ontology is in Public Preview and on by default since August 6, 2026.
- Knowledge Catalog is GA. Its Context API is in preview. BigQuery Graph is in
  preview.
- The Fabric IQ workload is GA. The ontology item is in preview. Work IQ and
  Foundry IQ round out Microsoft's context layer.
- Context in watsonx.data entered private preview on May 5, 2026.
- Snowflake Horizon Context competes for the same layer.
-->

---

## Context Graphs Share Four Traits

- **Written and learned:** Teams write some definitions by hand. The layer learns others by watching queries.
- **Permissions:** The layer answers with the caller's own permissions.
- **MCP access:** Agents reach the layer through MCP tools.
- **Open standard:** Apache Ossie specifies semantic layers and ontologies.

**Each context graph lives inside its vendor's platform.** A customer on two clouds builds two.

<!--
AWS Context learns join paths from agent queries. Genie Ontology ranks
snippets partly by how often they are used. AWS Context inherits IAM and Lake
Formation permissions. Genie Ontology gates every snippet by Unity Catalog
permissions.

MCP entry points: AWS Context MCP tools, the Genie One MCP server, and the
Foundry IQ MCP server.

Apache Ossie was called Open Semantic Interchange until it entered the Apache
Incubator. Snowflake founded it, and AWS and Databricks joined.

The platform-bound point is our inference from the vendor pages.
-->

---

## Agents Get a Control Plane

- **Identity:** Each agent gets its own identity.
- **Registry:** A registry lists every agent, MCP server, and tool.
- **Gateway:** A gateway routes all agent traffic.
- **Policy:** A policy check runs on every tool call.
- **Cross-cloud reach:** Microsoft and IBM control planes now discover agents on other clouds.

**The control plane holder** sees every agent and every tool call.

<!--
- AWS: AgentCore Identity, AgentCore Gateway, Policy in AgentCore, and AWS
  Agent Registry are all GA.
- Databricks: Unity Gateway reached GA on August 4, 2026.
- Google Cloud: Agent Identity, Agent Registry, and Agent Gateway are GA.
- IBM: The watsonx Orchestrate Agentic Control Plane is in private preview.
- Microsoft: Microsoft Agent 365 reached GA on May 1, 2026. Entra Agent ID
  gives each agent an Entra identity.

Microsoft Agent 365 syncs registries with Amazon Bedrock and Google Cloud in
public preview. watsonx Orchestrate discovers agents in Google's agent
platform and Microsoft Foundry.
-->

---

## MCP and A2A Connect Agents Across Platforms

- **MCP:** The Model Context Protocol lets an agent call an outside tool through one interface.
- **A2A:** The Agent2Agent protocol lets one agent call another, even on another platform.
- **MCP support:** All five vendors support MCP.
- **A2A support:** AWS, Google Cloud, IBM, and Microsoft support A2A.

**One MCP server** plugs into all five agent platforms.

<!--
AgentCore Gateway turns APIs and Lambda functions into MCP tools. Databricks
offers managed MCP servers and a GA Genie One MCP server. Google runs managed
MCP servers for its own services. watsonx Orchestrate and Foundry agents both
call MCP servers.

Google supports A2A 1.0, and IBM supports 0.3.0. Databricks documents A2A in
a community blog post.
-->

---

## Memory and Evaluation Become Managed Services

- **Agent memory:** Memory stores what an agent learned across sessions.
- **Memory status:** AWS and Google Cloud memory are GA. The other three are in Beta or preview.
- **Evaluation:** Evaluation scores agent answers against test cases before and after release.
- **Evaluation status:** AWS, Google Cloud, and Microsoft evaluation is GA.

**The memory layer is still open** at three of five vendors.

<!--
Memory examples: user preferences and past decisions. AgentCore Memory has
been GA since October 2025. Databricks managed agent memory is in Beta and
stores long-term memory in Lakebase. Google Memory Bank features reached GA
in June and July 2026.

Databricks evaluates agents with MLflow 3. IBM monitors agents with
watsonx.governance.
-->

---

## Operational Data Moves Next to the Lakehouse

- **Why:** Agents and AI apps need a database they can write to many times per second.
- **Postgres:** Databricks, AWS, Google Cloud, and Microsoft each offer managed Postgres.
- **Vectors:** Every vendor's operational database now adds vector search.
- **Streams:** Streams now feed the context layer as well as the lakehouse.

**Vector search alone** no longer sets a product apart.

<!--
Postgres products: Databricks Lakebase, Amazon Aurora DSQL and Aurora
PostgreSQL, AlloyDB for PostgreSQL, and Azure HorizonDB. IBM offers Db2 with
DiskANN vector indexing and DataStax Astra DB.

IBM completed its purchase of Confluent on March 17, 2026. IBM pairs the
Confluent Real-Time Context Engine with Context in watsonx.data.

The vector point is our inference from the vendor pages.
-->

---

## Agents Now Run Inside the Services

- **First wave:** Built-in agents handle incidents, failed pipelines, and cost spikes.
- **Turned on, not built:** The customer turns the agent on instead of building one.
- **Examples:** AWS DevOps Agent, Azure SRE Agent, Gemini Cloud Assist, Genie ZeroOps, and IBM Concert.
- **Needs a map:** Each agent needs a map of how services, code, and deployments connect.

**AWS DevOps Agent** builds an application topology. **Genie ZeroOps** reads Unity Catalog lineage.

<!--
AWS DevOps Agent reached GA on March 31, 2026. It covers AWS, Azure, and
on-premises systems, and reaches on-premises tools through MCP. Azure SRE
Agent reached GA in March 2026 and can restart, scale, or roll back within
policy guardrails. Genie ZeroOps is in private preview and tests a fix in a
sandbox before a human applies it.

Built-in agents will likely spread from operations to other routine tasks.
That point is our inference from the vendor pages.
-->

---

## App Builders and Custom Chips Round Out the Stack

- **App builders:** Business users describe an app, and the platform builds it on company data.
- **App builder status:** Apps in Amazon Quick is GA. The others are in Beta or preview.
- **Custom chips:** AWS, Google Cloud, Microsoft, and IBM build their own chips.
- **NVIDIA too:** The same four also rent NVIDIA GPUs next to their own chips.

<!--
Apps in Amazon Quick reached GA on September 1, 2026. Genie App Builder is in
Beta. Google's Agent Studio app builder and Apps in Copilot Studio are in
preview. IBM's closest product is IBM Bob, which targets developers.

Chips: Trainium3, Inferentia2, and Graviton5 at AWS. Ironwood TPU and Axion at
Google, with TPU 8t and 8i coming soon. Maia 200 and Cobalt 200 at Microsoft.
Telum II and the Spyre Accelerator at IBM. Databricks runs on the hardware of
its host clouds.
-->

---

## Where Neo4j Fits

A graph adds connected context to each layer.

---

## Neo4j Adds a Context Graph the Customer Owns

- **Context layer:** Neo4j adds a context graph that works across all five clouds.
- **Lakehouse:** Neo4j builds a graph from lakehouse tables and adds the links between them.
- **Agents:** The Neo4j MCP Server gives graph queries to any agent platform with MCP.
- **Agent memory:** The Neo4j Agent Memory library stores agent memory as a graph.
- **Chat and coding:** Chat tools and coding assistants reach the graph through MCP.

<!--
Each vendor builds a context graph inside its own platform. Neo4j adds one
that the customer owns, queries with Cypher, and uses across every cloud.

The lakehouse keeps the tables. The graph adds the relationships that link
them, so an agent can follow a chain of links in one query.

AgentCore Gateway, Databricks Agent Bricks, and IBM watsonx Orchestrate all
connect to MCP servers. The Neo4j Agent Memory library ships an integration
for Amazon Bedrock AgentCore.
-->

---

## Takeaways

- **One stack, five vendors:** The layers match. The names, formats, and catalogs differ.
- **Iceberg is common ground:** Format locks customers in less. The catalog decides more.
- **Context graphs are platform-bound:** Each vendor's graph lives inside its own platform.
- **MCP is the shared interface:** One MCP server reaches every agent platform.
- **Neo4j spans the clouds:** A customer-owned graph serves agents on any vendor.
