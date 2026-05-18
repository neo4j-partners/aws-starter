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

# Neo4j Aura and Agentic GraphRAG

A managed cloud graph database, why graphs power AI, and the step from retrievers to agents.

---

# Neo4j Aura: Cloud Graph Database

---

## What is Neo4j Aura?

Neo4j Aura is a **fully managed cloud graph database service** that eliminates the operational overhead of running a graph database.

**Key Characteristics:**
- **Fully managed**: No infrastructure to maintain
- **Scalable**: Automatically scales with your data and queries
- **Secure**: Enterprise-grade security and compliance
- **Available everywhere**: Deploy in AWS, GCP, or Azure

---

## Why Use a Graph Database?

Traditional databases struggle with **connected data**:

| Scenario | Relational DB | Graph DB |
|----------|---------------|----------|
| "Find friends of friends" | Complex JOINs, slow | Natural traversal, fast |
| "What impacts what?" | Multiple queries | Single query |
| "How are these connected?" | Hard to express | Native pattern matching |

**Graphs excel at relationship-heavy queries** that would require dozens of JOINs in SQL.

---

## The Value of Aura for AI/GenAI

Neo4j Aura provides unique capabilities for building AI applications:

**GraphRAG Foundation:**
- Store knowledge graphs that power AI agents
- Vector search for semantic similarity
- Graph traversal for relationship reasoning

**Production-Ready:**
- Built-in vector indexes for embeddings
- Cypher query language for complex retrieval
- APIs for integration with LLM frameworks

---

<style scoped>
section { font-size: 22px; }
h2 { font-size: 32px; }
</style>

## Graph Analytics in Explore

The **Explore** tool includes built-in graph algorithms for visual analysis:

**Available in Explore:**
| Category | Algorithms |
|----------|------------|
| **Centrality** | Betweenness, Degree, Eigenvector, PageRank |
| **Community Detection** | Label Propagation, Louvain, Weakly Connected Components |

**Full Algorithm Library (65+):**
Neo4j Aura Graph Analytics provides the complete library via serverless compute with Zero ETL:

| Category | Additional Algorithms | Use Cases |
|----------|----------------------|-----------|
| **Similarity** | Node Similarity, K-Nearest Neighbors | Recommendations, duplicate detection |
| **Path Finding** | Dijkstra, A*, Yen's K-Shortest | Routing, supply chain optimization |
| **Link Prediction** | Common Neighbors, Adamic Adar | Predict future connections |
| **Node Embeddings** | FastRP, GraphSAGE, Node2Vec | ML feature generation |

---

<style scoped>
section { font-size: 22px; }
h2 { font-size: 32px; }
</style>

## Aura Tools: Query Workspace

The **Query Workspace** is a developer-friendly environment for Cypher:

**Core Features:**
- Write and execute Cypher queries against your database
- Syntax highlighting and auto-completion
- Save and organize query collections
- Export results in multiple formats

**Query Log Forwarding:**
- Send logs to your cloud logging service
- Better compliance, monitoring, and operational visibility
- Manage directly from Aura console

---

<style scoped>
section { font-size: 22px; }
h2 { font-size: 32px; }
</style>

## Aura Tools: Explore

**Explore** (powered by Neo4j Bloom) is a visual graph exploration tool:

**Visual Graph Scene:**
- Interactive canvas showing your graph data
- Click and drag nodes to arrange layouts
- Export as PNG, CSV, or shareable scenes

**Search-First Experience:**
- Natural language and pattern-based search
- "Show me a graph" sample queries
- Find nodes and relationships without Cypher

**AI-Powered Features:**
- GenAI Copilot for query assistance
- Find hidden connections automatically

---

<style scoped>
section { font-size: 22px; }
h2 { font-size: 32px; }
</style>

## Aura Tools: Dashboards

**Dashboards** in the Neo4j Console provide data visualization capabilities with low code / no code:

**Visualization Types:**
- Bar charts, line charts, pie charts, etc.
- Geographic maps
- **3D graph visualizations** (WebGL-powered)

**GenAI Copilot:**
- AI-powered dashboard creation
- Natural language to visualization

**Enterprise Ready:**
- SSO integration
- Role-based access

---

## Aura Agents: No-Code GraphRAG

Aura Agents let you build **AI-powered conversational interfaces** to your graph:

- **No code required**: Configure through a simple UI
- **Natural language queries**: Ask questions in plain English
- **Automatic Cypher generation**: LLM translates questions to graph queries
- **Knowledge graph reasoning**: Leverage relationships for better answers

**Why Agents matter:**
- Democratize access to graph insights
- Build chatbots that understand your domain
- Combine vector search + graph traversal automatically

---

# From Retrievers to Agents

---

## The Problem

You know three retrieval patterns:
- **Vector**: Semantic content search
- **Vector Cypher**: Content + relationships
- **Text2Cypher**: Precise facts

**But users don't know about retriever types.**

They just ask questions:
- "What is exhaust gas temperature?"
- "How many aircraft are in the fleet?"
- "Which aircraft have components with critical maintenance events?"

---

## What is an Agent?

In AI terms, an agent has **four components**:

| Component | What It Does |
|-----------|--------------|
| **Perception** | Receives input (questions, history, tool descriptions) |
| **Reasoning** | Analyzes the question and decides what to do |
| **Action** | Executes the selected tool(s) |
| **Response** | Returns output in natural language |

---

## Tools: How Agents Take Action

**Action** involves calling tools.

Tools are capabilities the agent can use: functions it can call to get information or perform tasks.

- During **Perception**, the agent sees what tools are available
- During **Reasoning**, it decides which tool fits the question
- During **Action**, it executes the tool

---

## How Agents Choose Tools

The agent matches questions to tool descriptions:

**Question:** "How many aircraft are there?"

**Tool descriptions:**
- `get_graph_schema`: "Get database structure..."
- `search_content`: "Search for content about topics..."
- `query_database`: "Get answers to factual questions, counts..."

**Agent reasons:** "How many" leads to count, leads to `query_database`

---

## Retrievers as Tools

Your retrievers become tools:

| Tool | Based On | When Agent Uses It |
|------|----------|-------------------|
| Schema Tool | Graph introspection | "What data exists?" |
| Semantic Search | Vector Retriever | "What is...", "Tell me about..." |
| Database Query | Text2Cypher | "How many...", "List all..." |

Each tool has a description that tells the agent when to use it.

---

## The ReAct Pattern

Agents follow **ReAct** (Reasoning + Acting):

```
1. Receive question: "How many maintenance events affect aircraft AC1001?"
2. Reason: "This asks for a count"
3. Act: Call Database Query Tool
4. Observe: Result = 12
5. Respond: "Aircraft AC1001 is affected by 12 maintenance events."
```

For complex questions, the agent may loop through multiple cycles.

---

## Multi-Tool Example

**Question:** "What are AC1001's main faults and which flights were delayed?"

**Agent process:**
1. **Reason:** Need fault content AND flight delay relationships
2. **Act:** Call Semantic Search for AC1001's faults
3. **Observe:** Fault descriptions
4. **Reason:** Now need delayed flights
5. **Act:** Call Database Query for AC1001's delayed flights
6. **Observe:** Delayed flight list
7. **Respond:** Combine both into comprehensive answer

---

## Why Agents Matter

**Without agents:**
- Build separate interfaces for each retriever
- Force users to choose which retriever to use
- Complex user experience

**With agents:**
- Users ask natural questions
- System figures out how to answer
- Conversational, intuitive experience

---

## An Example: The GraphRAG Agent

An example of an agent is a GraphRAG system that:

1. **Receives** a user question
2. **Analyzes** what kind of question it is
3. **Selects** and executes the appropriate tool(s)
4. **Synthesizes** results into a coherent answer

Your retrievers become **tools** the agent can use.

---

## Summary

Neo4j Aura and agentic GraphRAG provide:

- **Managed graph database**: Focus on your data, not infrastructure
- **AI/GenAI capabilities**: Vector indexes, GraphRAG support, integrated tools
- **Aura Agents**: No-code conversational AI over your graph
- **Agents** have four components: Perception, Reasoning, Action, Response
- **Tools**: Retrievers become capabilities, selected by semantic matching
- **ReAct pattern**: Reason, Act, Observe, Respond
- **Result**: Users ask naturally; agents figure out how to answer
