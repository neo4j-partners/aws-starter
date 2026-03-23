# Neo4j + AWS Integration Research Report

> **Date**: February 2026
> **Scope**: AWS Bedrock AgentCore, Neo4j agent-memory, neo4j-graphrag-python, MCP servers, Context Graphs, and innovative integration patterns

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Integration Point 1: Bedrock Knowledge Bases GraphRAG](#integration-point-1-bedrock-knowledge-bases-graphrag)
3. [Integration Point 2: Strands Agents SDK](#integration-point-2-strands-agents-sdk)
4. [Integration Point 3: Aura Agent with Amazon Bedrock Embeddings](#integration-point-3-aura-agent-with-amazon-bedrock-embeddings)
5. [Integration Point 4: Neo4j Agent Memory](#integration-point-4-neo4j-agent-memory)
6. [Integration Point 5: Neo4j GraphRAG Library](#integration-point-5-neo4j-graphrag-library)
7. [Integration Point 6: Neo4j MCP Server on AgentCore](#integration-point-6-neo4j-mcp-server-on-agentcore)
8. [Integration Point 7: Context Graphs for Agentic AI](#integration-point-7-context-graphs-for-agentic-ai)
9. [Integration Point 8: AgentCore Memory + Neo4j Hybrid](#integration-point-8-agentcore-memory--neo4j-hybrid)
10. [Integration Point 9: Multi-Agent Orchestration](#integration-point-9-multi-agent-orchestration)
11. [Integration Point 10: SageMaker Unified Studio](#integration-point-10-sagemaker-unified-studio)
12. [Appendix: AWS Bedrock AgentCore Platform Overview](#appendix-aws-bedrock-agentcore-platform-overview)
13. [Innovative Ideas & Future Directions](#innovative-ideas--future-directions)
14. [Integration Matrix](#integration-matrix)
15. [References](#references)

---

## Executive Summary

Neo4j has deep and expanding integration potential with AWS, particularly through Amazon Bedrock AgentCore. This report identifies **10 concrete integration points** spanning MCP servers, agent memory, GraphRAG pipelines, multi-agent orchestration, and managed infrastructure. The combination of Neo4j's graph-native capabilities with AWS's agentic AI platform creates a compelling stack for building production-grade AI agents that reason over connected data.

Key findings:

- **Neo4j Agent Memory** already has native AWS integrations: an AgentCore-compatible memory provider, Strands Agents tools, and Amazon Bedrock embeddings
- **Neo4j GraphRAG** provides the retrieval layer with 6 retriever strategies that can power Amazon Bedrock-based agents
- **The Neo4j MCP server** deployed on AgentCore Runtime provides agents with direct graph database access via the AgentCore Gateway (currently blocked by MCP spec compatibility issues)
- **Context Graphs** — Neo4j's graph-structured memory that tracks entities, relationships, and reasoning traces — complement and extend AgentCore's native memory
- **AgentCore's native GraphRAG** (via Amazon Neptune Analytics) is limited to Amazon S3 data sources and Neptune only — Neo4j offers a more flexible, feature-rich alternative

---

## Integration Point 1: Bedrock Knowledge Bases GraphRAG

**AWS Services**: Amazon Bedrock Knowledge Bases, Amazon Neptune Analytics, Amazon S3

### AWS Native GraphRAG (Neptune Analytics)

Amazon Bedrock Knowledge Bases GraphRAG went generally available in March 2025:
- Uses **Amazon Neptune Analytics** as the combined graph and vector store
- Automatically creates vector embeddings AND an entity/relationship graph from source documents
- Combines vector similarity with graph traversal for retrieval
- **Limitation**: Only supports Amazon S3 data sources and Neptune Analytics (not Neo4j or any other graph database)

### Measured Improvements: GraphRAG vs. Vector-Only RAG

Graph-enhanced RAG addresses fundamental limitations of pure vector search:
- Integrating graph structures improves answer precision by **up to 35%** vs. vector-only retrieval
- Benchmarks show improvement from approximately 50% to **80%+ correctness** using hybrid GraphRAG
- Multi-hop reasoning connects disparate facts that vector similarity alone cannot link
- Explainability through traceable graph paths rather than opaque similarity scores

### Neo4j as Alternative GraphRAG Backend

Neo4j provides a more feature-rich GraphRAG alternative to the native Bedrock offering:

| Capability | Neptune Analytics GraphRAG | Neo4j GraphRAG |
|-----------|---------------------------|----------------|
| Data sources | Amazon S3 only | Any source (text, PDF, API, custom loaders) |
| Graph store | Amazon Neptune Analytics only | Neo4j Aura, self-hosted, or any Neo4j deployment |
| Schema control | Automatic only | Automatic, unconstrained, or explicitly defined |
| Retrieval strategies | Vector + graph (single strategy) | 6 strategies (vector, hybrid, text-to-cypher, tools router, and more) |
| Entity resolution | Basic | Advanced (exact, fuzzy, semantic, and composite matching) |
| Custom pipelines | No | Fully configurable DAG pipeline builder |
| LLM flexibility | Amazon Bedrock models only | 7 providers plus custom implementations |
| Graph query access | No direct query interface | Full Cypher access via MCP or direct API |
| Visualization | No | Neo4j Browser, Neo4j Bloom |

### Integration Value

For teams already using Neo4j or needing more control than Neptune Analytics provides, Neo4j GraphRAG with Amazon Bedrock models is a powerful combination. The knowledge graph construction pipeline can build from any data source, and the 6 retrieval strategies provide far more flexibility than the native Bedrock Knowledge Bases approach.

---

## Integration Point 2: Strands Agents SDK

**AWS Services**: AWS Strands Agents SDK, Amazon Bedrock (LLMs and embeddings), Amazon Bedrock AgentCore

**Strands Agents** is AWS's open-source agent framework, designed for tight integration with Amazon Bedrock and AgentCore.

### Neo4j Context Graph Tools for Strands

The neo4j-agent-memory library provides four pre-built tools that can be added to any Strands agent with a single function call. The tools connect to Neo4j using Amazon Bedrock for embeddings by default, making setup zero-configuration in AWS environments:

| Tool | Description |
|------|-------------|
| **Search Context** | Hybrid vector and graph search across messages, entities, and preferences — returns relevant context from all memory types |
| **Get Entity Graph** | Traverses the relationship graph around a named entity, returning connected nodes and edges with configurable depth and relationship type filters |
| **Add Memory** | Stores new memories with automatic entity extraction — the agent can save important information for future reference |
| **Get User Preferences** | Retrieves a user's stored preferences, optionally filtered by category (e.g., "food", "travel", "communication") |

### Integration Value

This is the fastest path to a Neo4j-powered AWS agent. The drop-in tools provide graph-native memory and knowledge graph capabilities to any Strands agent. Amazon Bedrock embeddings are the default, and the tools handle connection management, async execution, and error handling internally.

---

## Integration Point 3: Aura Agent with Amazon Bedrock Embeddings

**Status**: Proposed (Gap)

### Current Limitation

[Neo4j Aura Agent](https://neo4j.com/developer/genai-ecosystem/aura-agent/) is a GA agent-creation platform that auto-generates AI agents grounded by AuraDB data. It provides agentic GraphRAG with vector search, query templates, and text-to-query capabilities, deployable as MCP or REST endpoints with a single click.

However, Aura Agent currently only supports **OpenAI embeddings** for its vector search and semantic retrieval. This creates a dependency on OpenAI for AWS-native customers who otherwise run their entire AI stack on Amazon Bedrock.

### Proposed Integration

Add support for **`amazon.titan-embed-text-v2:0`** (1,024 dimensions, 100+ languages, $0.20/1M tokens) as an embedding provider in Aura Agent. This would allow AWS customers to:

- Use Aura Agent's automated agent creation and agentic GraphRAG without an OpenAI dependency
- Keep all API traffic within AWS (Bedrock) for compliance and data residency requirements
- Leverage existing Bedrock model access and billing rather than managing separate OpenAI API keys
- Align with the embedding model already supported by `neo4j-agent-memory`'s `BedrockEmbedder`

### Integration Value

Removes the last external dependency for teams building a fully AWS-native Neo4j agent stack: AgentCore (compute) + Bedrock (LLM + embeddings) + Aura Agent (graph-powered agents). This is a straightforward but high-impact enablement for AWS customers evaluating Aura Agent.

---

## Integration Point 4: Neo4j Agent Memory

**Project**: neo4j-agent-memory (neo4j-labs/agent-memory)
**Status**: Experimental (Neo4j Labs), available on PyPI

**AWS Services**: Amazon Bedrock (embeddings), Amazon Bedrock AgentCore Memory, AWS Strands Agents SDK

### What It Does

A graph-native memory system for AI agents with three memory layers:

| Layer | Purpose | How It Works |
|-------|---------|-------------|
| **Short-Term** | Conversations and messages | Stores messages as linked nodes in Neo4j, enabling sequential traversal and semantic search across conversation history |
| **Long-Term** | Entities, preferences, facts | Uses the POLE+O model (Person, Object, Location, Event, Organization) to store structured entities with typed relationships and confidence scores |
| **Reasoning** | Reasoning traces and tool usage | Captures how tasks were solved — recording tool calls, their results, and outcomes — so agents can learn from past reasoning patterns |

### POLE+O Data Model

The long-term memory uses a configurable entity schema based on intelligence analysis best practices:

- **PERSON**: Individuals, aliases, personas
- **OBJECT**: Physical or digital items (vehicles, phones, documents, devices)
- **LOCATION**: Geographic areas, addresses, places
- **EVENT**: Incidents, meetings, transactions
- **ORGANIZATION**: Companies, non-profits, government agencies

Each type supports subtypes for finer classification (e.g., an Object can be further typed as a Vehicle or a Document). Entities are linked via typed relationships with confidence scores and deduplicated via same-as relationships.

### AWS-Specific Integrations Already Built

#### 1. AgentCore HybridMemoryProvider

The library includes a ready-made memory provider that is compatible with Amazon Bedrock AgentCore. It implements an AgentCore-compatible interface backed by Neo4j Context Graphs, and intelligently routes queries to the appropriate memory backend based on the nature of the question:

- Questions about recent conversations ("what did we discuss earlier?") route to short-term message search
- Questions about entities ("who is Alice?", "what organization?") route to entity graph traversal
- Questions about preferences ("what's the user's favorite?") route to preference search
- Questions about connections ("how is John related to the Acme project?") route to graph traversal with relationship enrichment

Five routing strategies are available: automatic (keyword-based detection), explicit (caller specifies memory type), all (searches every backend), short-term-first (with long-term fallback), and long-term-first (with short-term fallback).

#### 2. AWS Strands Agents Integration

The library provides four drop-in tools for AWS Strands Agents, AWS's open-source agent framework:

| Tool | Description |
|------|-------------|
| **Search Context** | Hybrid vector and graph search across messages, entities, and preferences |
| **Get Entity Graph** | Traverses the relationship graph around a named entity with configurable depth and relationship type filters |
| **Add Memory** | Stores memories with automatic entity extraction from the content |
| **Get User Preferences** | Retrieves a user's preference subgraph filtered by category |

These tools use Amazon Bedrock for embeddings by default, making them zero-configuration for AWS environments.

#### 3. Amazon Bedrock Embeddings

The library includes a native Amazon Bedrock embedding provider that supports:

- Amazon Titan Embed Text V2 (1024 dimensions, recommended)
- Amazon Titan Embed Text V1 (1536 dimensions)
- Cohere Embed English V3 via Bedrock (1024 dimensions)
- Cohere Embed Multilingual V3 via Bedrock (1024 dimensions)

The embedder uses the Amazon Bedrock Runtime API and supports standard AWS credential chains (IAM roles, profiles, environment variables).

#### 4. MCP Server

The agent-memory package includes its own MCP server with 6 memory-specific tools:

| Tool | Description |
|------|-------------|
| **Memory Search** | Hybrid vector and graph search across all memory types |
| **Memory Store** | Store messages, facts (subject-predicate-object triples), and preferences |
| **Entity Lookup** | Look up an entity and retrieve its relationships and neighbors |
| **Conversation History** | Retrieve the full conversation history for a session |
| **Graph Query** | Execute read-only Cypher queries against the knowledge graph |
| **Add Reasoning Trace** | Store procedural memory capturing how a task was solved |

This MCP server can be deployed on AgentCore Runtime alongside or instead of the standard Neo4j MCP server, providing memory-specific tools rather than raw database access.

### Additional Framework Integrations

Beyond AWS, the agent-memory package also supports LangChain, Pydantic AI, LlamaIndex, CrewAI, Google ADK, OpenAI Agents SDK, and Microsoft Agent Framework.

---

## Integration Point 5: Neo4j GraphRAG Library

**Project**: neo4j-graphrag (neo4j/neo4j-graphrag-python)
**Status**: Official Neo4j package, production-ready

**AWS Services**: Amazon Bedrock (Claude, Titan models via LangChain adapter), Amazon Bedrock AgentCore

### What It Does

The official Neo4j GraphRAG package handles both sides of the GraphRAG pipeline:
1. **Knowledge Graph Construction** — Builds knowledge graphs from unstructured text and PDFs
2. **Retrieval** — Multiple strategies for getting graph-enriched context to LLMs
3. **Generation** — Complete RAG pipeline with context injection and answer synthesis

### 6 Retrieval Strategies

| Retriever | How It Works | Best For |
|-----------|-------------|----------|
| **Vector Retriever** | Similarity search on Neo4j's native vector index | Standard semantic search |
| **Vector + Cypher Retriever** | Vector match followed by graph traversal to pull in connected information | Semantic search enriched with entity relationships |
| **Hybrid Retriever** | Combines vector similarity with fulltext keyword search using a configurable weight | Balancing conceptual similarity with exact terminology |
| **Hybrid + Cypher Retriever** | Hybrid search followed by graph traversal | Most comprehensive retrieval — semantic, keyword, and graph context combined |
| **Text-to-Cypher Retriever** | An LLM translates the natural language question into a Cypher database query | Precise structured queries ("which companies did Alice work for between 2015 and 2020?") |
| **Tools Retriever** | An LLM acts as a router, automatically selecting the best retriever for each question | Automatic strategy selection when query types vary |

### Knowledge Graph Construction

Two approaches are available:

- **Simple Pipeline** — A single-call construction process that loads a document, splits it into chunks, generates embeddings, extracts entities and relationships using an LLM, validates the extracted graph against a schema, writes everything to Neo4j, and resolves duplicate entities
- **Advanced Pipeline** — A fully configurable directed acyclic graph (DAG) where each processing step can be customized, reordered, swapped out, or extended

Schema can be discovered automatically by the LLM, left unconstrained, or defined explicitly with node types, relationship types, allowed patterns, and typed properties.

### LLM Provider Support

The library natively supports OpenAI, Anthropic (Claude), Google Vertex AI, Cohere, Mistral AI, Ollama, and Azure OpenAI. All providers include built-in rate limit handling with configurable retry and exponential backoff.

**Notable gap**: There is no native Amazon Bedrock LLM class in the library. However, Bedrock models are accessible through the Anthropic provider (Claude models on Bedrock via the Anthropic SDK's Bedrock mode) and through LangChain's Bedrock adapter (as demonstrated in this repository's LangGraph agent).

### Integration Value

Provides the retrieval intelligence layer for any Amazon Bedrock-powered agent. The Tools Retriever is particularly powerful — it lets an LLM dynamically choose between vector, hybrid, text-to-cypher, and graph traversal strategies per query, maximizing retrieval quality without manual configuration.

---

## Integration Point 6: Neo4j MCP Server on AgentCore

**Status**: Implemented in this repository

> **Blocked**: The Neo4j MCP server and AgentCore have different design approaches to authentication. The Neo4j MCP server uses a single-layer model where client credentials are passed through to the database on each request, while AgentCore uses a two-layer model where client-to-gateway auth and server-to-database auth are separate. Aligning these two approaches requires the Neo4j MCP server to add support for an environment-credential mode where it uses its own server-level database credentials independently of client authentication. This is an active area of discussion.

**AWS Services**: Amazon Bedrock AgentCore Runtime, AgentCore Gateway, Amazon Cognito, Amazon ECR, AWS CDK, AWS Lambda, AWS IAM

### Architecture

The Neo4j MCP server is containerized and deployed to AgentCore Runtime. The request flow works as follows: an AI agent first authenticates with Amazon Cognito using machine-to-machine credentials to obtain a JWT token. The agent then sends requests to the AgentCore Gateway, which validates the token, exchanges it for a Runtime-level OAuth token via a credential provider, and forwards the request to the MCP server running inside an isolated microVM. The MCP server executes the query against Neo4j Aura and returns results back through the same chain.

### MCP Tools Exposed

The server exposes two tools through the AgentCore Gateway:

| Tool | Description |
|------|-------------|
| **Get Schema** | Retrieves the Neo4j database schema (node labels, relationship types, properties) |
| **Read Cypher** | Executes read-only Cypher queries against the Neo4j database |

When accessed through the Gateway, tool names are automatically prefixed with the target name (e.g., "neo4j-mcp-server-target___read-cypher") to support multi-target routing.

### Key Implementation Details

- **Read-only mode**: Write operations are disabled at the server level, enforcing safety for agent access
- **MicroVM isolation**: Each agent session runs in a dedicated microVM with sanitized memory on termination — stronger isolation than shared container services like Amazon ECS/Fargate
- **Gateway-only access**: Direct Runtime access is blocked via a JWT authorizer — all requests must route through the AgentCore Gateway
- **Machine-to-machine authentication**: Uses Amazon Cognito's client credentials flow with 12-hour token validity
- **Infrastructure as Code**: The entire stack is defined in AWS CDK, including Amazon Cognito user pools, AWS IAM roles, AWS Lambda health check functions, and OAuth provider management

### Integration Value

Gives any Amazon Bedrock agent the ability to query a Neo4j knowledge graph using natural language translated to Cypher. The AgentCore Gateway's semantic tool selection means agents with hundreds of tools can discover and use Neo4j tools automatically without explicit configuration.

---

## Integration Point 7: Context Graphs for Agentic AI

**AWS Services**: Amazon Bedrock AgentCore Memory (complementary), AgentCore Runtime (hosting)

### What Is a Context Graph?

A **Context Graph** is a structured representation of **decision traces** — the reasoning behind decisions — captured from real workflows. The term was popularized by [Foundation Capital](https://foundationcapital.com/why-are-context-graphs-are-the-missing-layer-for-ai/), who argue that the bottleneck for production AI agents isn't intelligence (models are "good enough") but **context**: agents can read data and take action, but they don't capture *why* decisions were made. That reasoning is scattered across tools like Slack, email, and support tickets, or never recorded at all.

A context graph records not just *what* happened, but *why* it happened and *how entities relate to each other*. It maintains:

1. **Entities** with types, properties, and descriptions
2. **Relationships** between entities with types and confidence scores
3. **Decision traces** — the reasoning behind actions (why an incident was escalated, why a customer got an exception)
4. **Temporal context** — when things were learned, when they happened
5. **Provenance** — which conversation, document, or interaction produced each fact
6. **Multi-hop paths** — the ability to traverse from one entity through several relationships to discover non-obvious connections

The key insight is that decisions are cross-functional (spanning sales, SRE, support, engineering) but systems of record are siloed by function. Context graphs bridge this gap by capturing decision traces *implicitly* — as a byproduct of delivering value — rather than requiring explicit data entry. Companies that structure these traces into context graphs will create compounding flywheels that become durable moats.

> For a detailed analysis of context graphs as an industry concept, see [CONTEXT_GRAPH.md](./CONTEXT_GRAPH.md).

### Context Graph vs. AgentCore Memory

| Capability | AgentCore Memory | Neo4j Context Graph |
|-----------|-----------------|-------------------|
| Store conversation turns | Yes (events) | Yes (message nodes) |
| Extract facts | Yes (SEMANTIC strategy) | Yes (LLM + NER extraction) |
| Extract preferences | Yes (USER_PREFERENCE) | Yes (preference nodes) |
| Entity resolution | Basic | Advanced (exact, fuzzy, semantic, and composite matching) |
| Relationship traversal | No | Yes (multi-hop graph queries) |
| Cross-session entity linking | Limited | Full graph connectivity |
| Reasoning traces | No (except EPISODIC) | Yes (reasoning traces, steps, and tool calls) |
| Custom schema (POLE+O) | No | Yes (configurable entity types and subtypes) |
| Graph visualization | No | Yes (Neo4j Browser, Neo4j Bloom) |
| Direct query access | No | Yes (read-only Cypher via MCP) |

### How Context Graphs Work in Practice

When a user asks "What's happening with the Acme deal?", an agent backed by a context graph performs multiple operations: it searches short-term memory for recent messages mentioning Acme, looks up Acme as an Organization entity in the graph, then traverses relationships to discover that Acme has a deal managed by Sarah, is located in San Francisco, and that the deal involves Product X. All of this connected context is combined and provided to the LLM, which generates an informed response with full relationship context — something impossible with flat memory stores.

### Integration Value

Context Graphs give agents the ability to reason about relationships between entities, discover non-obvious connections, and maintain a persistent, queryable knowledge structure that grows with every interaction. This is fundamentally different from — and complementary to — flat memory stores.

---

## Integration Point 8: AgentCore Memory + Neo4j Hybrid

**AWS Services**: Amazon Bedrock AgentCore Memory, AgentCore Runtime, Amazon Bedrock (embeddings)

### The Hybrid Architecture

The most powerful integration pattern combines AgentCore's managed memory with Neo4j's graph capabilities. The architecture has three tiers:

- **AgentCore Short-Term Memory** handles turn-by-turn conversational state as managed events
- **AgentCore Long-Term Memory** stores extracted facts, summaries, and preferences using its native SEMANTIC and EPISODIC strategies
- **Neo4j Context Graph** (accessed via MCP or direct API) provides the entity relationship layer — storing entities, relationships between them, and reasoning traces with full graph traversal capabilities

The AI agent, running on AgentCore Runtime, queries all three tiers as needed. The routing between them is handled by the HybridMemoryProvider.

### How the HybridMemoryProvider Works

The HybridMemoryProvider from the neo4j-agent-memory library implements this three-tier pattern. When content is stored, the provider automatically extracts entities from the text and creates them as graph nodes with relationships. For example, storing the message "Alice from Acme Corp mentioned the Q3 deadline for Project Atlas" would automatically extract Alice as a Person, Acme Corp as an Organization, and Project Atlas as an Event, then create relationships between them (Alice works at Acme Corp, Acme Corp has Project Atlas).

When searching, the provider analyzes the query and routes it to the appropriate backend. A query like "Who is involved in Project Atlas?" would be routed to the entity graph, where a relationship traversal returns all connected people, organizations, and events.

### Routing Strategies

| Strategy | Behavior |
|----------|----------|
| **Automatic** | Keyword analysis determines whether to search short-term messages, entity graph, or preferences |
| **Explicit** | The caller specifies which memory types to search |
| **All** | Searches every backend for every query |
| **Short-term first** | Tries short-term memory first, falls back to long-term if no results |
| **Long-term first** | Tries long-term entity and preference stores first, falls back to short-term if no results |

### Integration Value

This is arguably the most valuable integration — it lets teams use AgentCore's managed infrastructure for simple session memory while leveraging Neo4j's graph power for entity relationships, knowledge graphs, and multi-hop reasoning. The routing logic is transparent to the agent.

---

## Integration Point 9: Multi-Agent Orchestration

**AWS Services**: Amazon Bedrock AgentCore Gateway, AgentCore Runtime, AgentCore Policy (Cedar), Amazon CloudWatch

### Pattern: Shared Knowledge Graph as Multi-Agent State

In multi-agent systems, Neo4j serves as the shared state layer that all agents read from and write to. The AgentCore Gateway sits at the top, providing semantic tool routing. Below it, multiple specialized agents (e.g., a Research Agent, an Operations Agent, and a Maintenance Agent) each connect to the same Neo4j knowledge graph through the Gateway. The graph accumulates entities, relationships, memory, and reasoning traces from all agents.

### Implementation in This Repository

This repository demonstrates this pattern with an orchestrator agent that routes requests to specialized domain agents:
- An **Orchestrator Agent** analyzes incoming requests and routes them to the appropriate specialist
- A **Basic Agent** handles direct Neo4j queries via MCP
- All agents share access to the same Neo4j graph via the AgentCore Gateway

### Multi-Agent Benefits of Graph State

1. **Shared entity resolution** — When one agent learns about "Alice", all other agents can reference the same entity with its full context
2. **Cross-agent reasoning traces** — One agent's tool calls and outcomes are visible to other agents, enabling learning from each other
3. **Conflict detection** — Graph constraints prevent conflicting facts from being introduced by different agents
4. **Audit trail** — Every entity, relationship, and fact has provenance tracking (which agent created it, in which session)
5. **Collaborative knowledge building** — Each agent interaction enriches the shared knowledge graph for all agents

### AgentCore Gateway Integration

The AgentCore Gateway enables multi-agent Neo4j access with several enterprise capabilities:
- **Semantic tool selection** — Agents automatically discover Neo4j tools from a catalog of potentially hundreds of available tools
- **Policy enforcement** — AgentCore Policy uses Cedar rules to restrict which agents can read vs. write to Neo4j
- **Gateway interceptors** — Provide fine-grained control over which tools are visible to which agents
- **Credential management** — The Gateway handles Neo4j authentication centrally for all agents

---

## Integration Point 10: SageMaker Unified Studio

**AWS Services**: Amazon SageMaker Unified Studio, Amazon Bedrock (inference profiles), Amazon S3

### Current Integration (This Repository)

This repository includes SageMaker notebook integration. SageMaker Unified Studio's permissions boundary blocks direct Amazon Bedrock model access, so the project uses tagged inference profiles that satisfy the permissions check. Setup scripts create these profiles for Claude Haiku and Claude Sonnet models.

### Integration Patterns

1. **SageMaker Notebooks** — Run Neo4j GraphRAG pipelines in JupyterLab notebooks for interactive data exploration and knowledge graph construction
2. **SageMaker Processing** — Run large-scale knowledge graph construction jobs on managed compute
3. **SageMaker Endpoints** — Deploy Neo4j-powered RAG pipelines as real-time inference endpoints accessible to other AWS services
4. **SageMaker Feature Store** — Export graph embeddings (generated by Neo4j Graph Data Science) as features for traditional ML models

### Integration Value

Amazon SageMaker provides the compute and experiment tracking infrastructure, while Neo4j provides the knowledge graph layer. This combination is ideal for teams building graph-enhanced ML pipelines that need both traditional ML and generative AI capabilities.

---

## Appendix: AWS Bedrock AgentCore Platform Overview

AgentCore is AWS's modular platform for deploying AI agents at enterprise scale. Understanding its components is essential for mapping Neo4j integration points.

### Core Components

| Component | Purpose | Neo4j Relevance |
|-----------|---------|-----------------|
| **AgentCore Runtime** | Deploy agents and MCP servers in isolated microVMs | Hosts Neo4j MCP server and Neo4j-powered agents |
| **AgentCore Gateway** | Centralized tool server with MCP support and semantic routing | Routes agent requests to Neo4j tools with authentication |
| **AgentCore Identity** | Agent identity, OAuth2, token vault via Amazon Cognito | Secures agent-to-Neo4j authentication |
| **AgentCore Memory** | Managed short-term and long-term memory | Neo4j can extend or replace with graph-native memory |
| **AgentCore Policy** (Preview) | Cedar-based deterministic access control | Controls which agents can read or write to Neo4j |
| **AgentCore Evaluations** (Preview) | Continuous quality scoring via Amazon CloudWatch | Measures quality of graph-augmented responses |

### AgentCore Memory Strategies

AgentCore provides 5 native memory strategies:

1. **SEMANTIC** — Extracts facts and contextual knowledge into a persistent knowledge base
2. **SUMMARIZATION** — Generates conversation summaries
3. **USER_PREFERENCE** — Captures user preferences
4. **EPISODIC** — Structures interactions as episodes with reflections (scenarios, intents, actions, outcomes)
5. **CUSTOM** — Fully custom extraction and consolidation logic

**Key insight**: AgentCore's memory is flat and document-oriented. Neo4j's graph-native memory adds relationship traversal, entity linking, and multi-hop reasoning that AgentCore's native memory cannot provide.

---

## Innovative Ideas & Future Directions

### 1. Agent Memory MCP Server on AgentCore

**AWS Services**: Amazon Bedrock AgentCore Runtime, AgentCore Gateway

Deploy the neo4j-agent-memory MCP server (with its 6 memory-specific tools) on AgentCore Runtime alongside the standard Neo4j MCP server. This gives agents two complementary tool sets: the Neo4j MCP server for raw graph access (schema inspection and Cypher queries), and the Agent Memory MCP server for higher-level memory operations (search, store, entity lookup, and reasoning traces). The AgentCore Gateway's semantic tool selection would automatically route each request to the appropriate server based on the query.

### 2. Context Graph as Agent Episodic Memory

**AWS Services**: Amazon Bedrock AgentCore Memory (EPISODIC strategy)

Combine AgentCore's EPISODIC memory strategy with Neo4j's reasoning trace storage. AgentCore extracts structured episodes from conversations (capturing the scenario, intent, actions taken, and outcome). These episodes are then stored in the Neo4j Context Graph as connected nodes — episodes link to the tool calls they involved, the tools that were used, and the outcomes they produced. Cross-episode similarity relationships enable agents to find past episodes similar to their current task, identify which tool chains led to successful outcomes, and avoid approaches that previously failed.

### 3. Dynamic Schema Evolution via Agent Learning

**AWS Services**: Amazon Bedrock AgentCore Runtime

As agents interact with users and discover new entity types, the POLE+O schema in Neo4j can evolve dynamically. For example, if an agent encounters API endpoints in conversation, it can create a new "API_ENDPOINT" subtype under the Object entity type, storing properties like HTTP method, path, and owning service. The graph schema grows organically as agents learn, unlike fixed-schema memory stores that require upfront definition of all possible types.

### 4. Graph-Enhanced RAG with Bedrock Knowledge Bases

**AWS Services**: Amazon Bedrock Knowledge Bases, Amazon S3, Amazon Neptune Analytics

Use Neo4j as a secondary retrieval layer alongside Amazon Bedrock Knowledge Bases. A user query flows to both systems in parallel: Bedrock Knowledge Bases performs vector retrieval over documents stored in Amazon S3, while Neo4j GraphRAG performs graph-enriched retrieval over the knowledge graph. Both sets of results are combined and provided to the LLM for answer generation. This "best of both worlds" approach uses Bedrock for document-level retrieval and Neo4j for entity and relationship-level context.

### 5. Cedar Policy Integration for Graph Access Control

**AWS Services**: Amazon Bedrock AgentCore Policy (Cedar)

Use AgentCore Policy to enforce fine-grained access control on Neo4j queries. Cedar rules can permit specific agents to use read-only tools while blocking write access, restrict which agents can access which tools, and enforce conditions based on user identity and tool parameters. For example, a research agent could be permitted to read from Neo4j but forbidden from writing, while an admin agent gets full access. All policy enforcement happens deterministically outside the LLM reasoning loop, ensuring consistent security.

### 6. Graph-Powered Agent Evaluation

**AWS Services**: Amazon Bedrock AgentCore Evaluations, Amazon CloudWatch

Use Neo4j to store and analyze agent evaluation data. By storing episodes, tool calls, and outcomes as a graph, teams can run graph queries to identify which tool chains lead to successful outcomes, which agents perform best on which types of tasks, and where failure patterns cluster. This enables data-driven optimization of agent behavior based on graph analysis of past performance, complementing AgentCore Evaluations' built-in scoring with deeper structural analysis.

### 7. Cross-Agent Knowledge Sharing via Graph Federation

**AWS Services**: Amazon Bedrock AgentCore Gateway, AgentCore Runtime

Multiple specialized agents build different parts of a shared knowledge graph: a Research Agent adds entities and facts from web research, a Customer Agent adds customer interactions and preferences, and an Operations Agent adds system status and incident data. All agents can then query the unified graph for cross-domain insights that no single agent could produce on its own. The AgentCore Gateway manages tool routing and access control for all agents.

### 8. Real-Time Graph Streaming for Agent Notifications

**AWS Services**: Amazon EventBridge, AWS Lambda, Amazon Bedrock AgentCore Runtime

Use Neo4j's change data capture capability to trigger agent actions when the graph changes. Graph changes flow through Amazon EventBridge to an AWS Lambda function, which notifies the appropriate agent running on AgentCore Runtime. When a critical entity is updated (e.g., a customer's risk status changes or a deal closes), agents are proactively notified and can take immediate action without waiting for a user query.

### 9. Graph-Enhanced Bedrock Guardrails

**AWS Services**: Amazon Bedrock Guardrails, AgentCore Gateway

Use Neo4j to maintain a knowledge graph of allowed and disallowed topics, entities, and relationships. Agents consult this graph before responding, providing domain-specific guardrails beyond Amazon Bedrock's built-in content filters. For example, a financial services agent could check the graph to confirm that a customer is approved to discuss certain investment products before providing advice.

### 10. Neo4j as AgentCore CUSTOM Memory Backend

**AWS Services**: Amazon Bedrock AgentCore Memory (CUSTOM strategy)

Implement AgentCore's CUSTOM memory strategy backed entirely by Neo4j. The custom strategy would use neo4j-agent-memory's multi-stage extraction pipeline (combining spaCy NER, GLiNER zero-shot extraction, and LLM-based extraction) for the extract phase, and neo4j-agent-memory's composite entity resolver (chaining exact, fuzzy, and semantic matching) for the consolidation phase. This would make Neo4j a first-class memory backend for AgentCore while using the managed memory API.

---

## Integration Matrix

| Integration | Maturity | Complexity | Value | AWS Services |
|------------|----------|-----------|-------|-------------|
| Bedrock Knowledge Bases GraphRAG | **Pattern exists** | Medium | Very High | Amazon Bedrock Knowledge Bases, Amazon Neptune Analytics |
| Strands Agent Tools | **Built** | Low | High | Strands Agents SDK, Amazon Bedrock |
| Aura Agent + Bedrock Embeddings | **Proposed** (Gap) | Low | High | Amazon Bedrock (Titan Embeddings), Neo4j Aura Agent |
| Agent Memory HybridMemoryProvider | **Built** | Low | Very High | AgentCore Memory, Amazon Bedrock |
| GraphRAG with Bedrock LLMs | **Pattern exists** | Medium | Very High | Amazon Bedrock (Claude, Titan) |
| Neo4j MCP on AgentCore Runtime | **Blocked** (MCP spec compat) | Medium | High | AgentCore Runtime, AgentCore Gateway, Amazon Cognito, Amazon ECR |
| Bedrock Embeddings | **Built** | Low | Medium | Amazon Bedrock Runtime |
| Multi-Agent Orchestration | **Implemented** | High | Very High | AgentCore Gateway, AgentCore Policy |
| SageMaker Notebooks | **Implemented** | Medium | Medium | Amazon SageMaker Unified Studio, Amazon Bedrock |
| Agent Memory MCP on AgentCore | **Proposed** | Medium | Very High | AgentCore Runtime, AgentCore Gateway |
| Context Graph + Episodic Memory | **Proposed** | High | Very High | AgentCore Memory (EPISODIC) |
| Cedar Policy for Graph Access | **Proposed** | Medium | High | AgentCore Policy (Cedar) |
| Graph-Enhanced Evaluations | **Proposed** | Medium | Medium | AgentCore Evaluations, Amazon CloudWatch |
| Custom Memory Strategy | **Proposed** | High | Very High | AgentCore Memory (CUSTOM) |

---

## References

### AWS Documentation
- [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/)
- [AgentCore Runtime - MCP Servers](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html)
- [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
- [AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html)
- [AgentCore Memory Strategies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-strategies.html)
- [AgentCore Episodic Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/episodic-memory-strategy.html)
- [AgentCore Identity](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-overview.html)
- [AgentCore Policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html)
- [Bedrock Knowledge Bases GraphRAG](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-build-graphs.html)

### AWS Reference Architectures
- [Knowledge Graphs and GraphRAG with Neo4j (AWS Architecture)](https://docs.aws.amazon.com/architecture-diagrams/latest/knowledge-graphs-and-graphrag-with-neo4j/knowledge-graphs-and-graphrag-with-neo4j.html)

### AWS Blog Posts
- [Introducing AgentCore Gateway](https://aws.amazon.com/blogs/machine-learning/introducing-amazon-bedrock-agentcore-gateway-transforming-enterprise-ai-agent-tool-development/)
- [Building Context-Aware Agents with AgentCore Memory](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-memory-building-context-aware-agents/)
- [AgentCore Long-Term Memory Deep Dive](https://aws.amazon.com/blogs/machine-learning/building-smarter-ai-agents-agentcore-long-term-memory-deep-dive/)
- [Episodic Memory for Agents](https://aws.amazon.com/blogs/machine-learning/build-agents-to-learn-from-experiences-using-amazon-bedrock-agentcore-episodic-memory/)
- [Securing Agents with AgentCore Identity](https://aws.amazon.com/blogs/security/securing-ai-agents-with-amazon-bedrock-agentcore-identity/)
- [Fine-Grained Access Control with Gateway Interceptors](https://aws.amazon.com/blogs/machine-learning/apply-fine-grained-access-control-with-bedrock-agentcore-gateway-interceptors/)
- [Build GraphRAG with Bedrock Knowledge Bases](https://aws.amazon.com/blogs/machine-learning/build-graphrag-applications-using-amazon-bedrock-knowledge-bases/)
- [Leveraging Neo4j and Amazon Bedrock](https://aws.amazon.com/blogs/apn/leveraging-neo4j-and-amazon-bedrock-for-an-explainable-secure-and-connected-generative-ai-solution/)

### Neo4j Resources
- [Neo4j GraphRAG Python Package](https://neo4j.com/docs/neo4j-graphrag-python/)
- [Neo4j Agent Memory (GitHub)](https://github.com/neo4j-labs/agent-memory)
- [Neo4j MCP Server (GitHub)](https://github.com/neo4j/mcp)
- [Neo4j MCP Integrations](https://neo4j.com/developer/genai-ecosystem/model-context-protocol-mcp/)
- [Neo4j-AWS Strategic Collaboration](https://neo4j.com/press-releases/neo4j-aws-bedrock-integration/)
- [Neo4j GenAI Ecosystem](https://neo4j.com/labs/genai-ecosystem/)
- [GraphRAG Manifesto](https://neo4j.com/blog/graphrag-manifesto/)
- [Build Context-Aware GraphRAG Agent](https://neo4j.com/blog/genai/build-context-aware-graphrag-agent/)
- [Neo4j Aura Agent (Developer)](https://neo4j.com/developer/genai-ecosystem/aura-agent/)
- [Neo4j Aura Agent Launch](https://neo4j.com/blog/agentic-ai/neo4j-launches-aura-agent/)
- [Hands-on with Context Graphs](https://medium.com/neo4j/hands-on-with-context-graphs-and-neo4j-8b4b8fdc16dd)
- [Modeling Agent Memory](https://medium.com/neo4j/modeling-agent-memory-d3b6bc3bb9c4)

### AWS Partner / Integration Resources
- [Graph Feature Engineering with Neo4j and SageMaker](https://aws.amazon.com/blogs/apn/graph-feature-engineering-with-neo4j-and-amazon-sagemaker/)
- [Improving RAG Accuracy with GraphRAG](https://aws.amazon.com/blogs/machine-learning/improving-retrieval-augmented-generation-accuracy-with-graphrag/)
- [Hands-on Lab: Neo4j and Bedrock](https://github.com/neo4j-partners/hands-on-lab-neo4j-and-bedrock)
- [Neo4j Generative AI AWS Demo](https://github.com/neo4j-partners/neo4j-generative-ai-aws)

### This Repository
- [Architecture Documentation](./docs/ARCHITECTURE.md)
- [Neo4j MCP Server Deployment](./neo4j-agentcore-mcp-server/)
- [LangGraph Agent](./langgraph-neo4j-mcp-agent/)
- [AgentCore Agents (Basic + Orchestrator)](./agentcore-neo4j-mcp-agent/)
- [Foundation Samples](./foundation_samples/)
