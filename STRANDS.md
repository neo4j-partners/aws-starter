# Neo4j Agent Memory and Strands Agents

## Project Overview

Neo4j Agent Memory is a Python library from Neo4j Labs that gives AI agents persistent memory backed by a Neo4j graph database. Instead of agents forgetting everything between conversations, this library lets them remember past interactions, build up knowledge about people and things, and learn from their own reasoning patterns over time.

The library organizes memory into three layers:

- **Short-term memory** holds conversation history. Messages are stored per session so an agent can recall what was said earlier in a conversation and search across past sessions by meaning.

- **Long-term memory** stores facts, preferences, and entities. It uses a classification system called POLE+O (Person, Object, Location, Event, Organization) to categorize extracted information. When an agent learns that "Alice works at Acme Corp," it creates Person and Organization entities and links them with a relationship. It also handles deduplication so the same entity doesn't get stored multiple times under different names.

- **Reasoning memory** records how an agent solved problems — what tools it called, what it was thinking, and what results it got. This lets agents learn from past problem-solving approaches rather than starting from scratch each time.

All three layers live in Neo4j's graph structure, which means the connections between entities are first-class citizens rather than afterthoughts. Searching memory can combine traditional vector similarity (finding things that mean something similar) with graph traversal (following relationship chains).

## What Is Strands

Strands Agents is AWS's open-source Python SDK for building AI agents. It provides a framework for creating agents that can use tools, reason through multi-step problems, and interact with AWS services like Amazon Bedrock for LLM access. Strands handles the agent loop — the cycle of thinking, deciding which tool to call, executing it, and incorporating the result — while developers supply the tools and configuration.

## How They Integrate

Neo4j Agent Memory provides a dedicated Strands integration that exposes memory capabilities as four Strands-compatible tools. When these tools are registered with a Strands agent, the agent gains the ability to store and retrieve information from the graph memory system as part of its normal reasoning loop.

### The Four Tools

**Search Context** lets the agent search across all memory layers at once. Given a natural language query, it performs a semantic search against stored messages, entities, and preferences, returning the most relevant results with similarity scores. The agent uses this when it needs to recall something from a prior conversation or check what it already knows about a topic.

**Get Entity Graph** lets the agent explore relationships around a specific entity. If the agent knows about a person, it can traverse outward to see what organizations they belong to, what events they attended, or what locations they are connected to. The depth of traversal is configurable, and relationship types can be filtered. This is where the graph structure really pays off — following chains of connections is something a graph database does naturally.

**Add Memory** lets the agent store new information. When the agent learns something worth remembering, it calls this tool with the content. Behind the scenes, the system generates embeddings for semantic search, runs entity extraction to identify people, places, organizations and other entities mentioned in the content, and stores everything in the graph with appropriate relationships. The agent doesn't need to understand the extraction pipeline — it just passes in text and the system handles the rest.

**Get User Preferences** retrieves stored preferences for a specific user, optionally filtered by category. This gives agents quick access to things like communication preferences, topic interests, or configuration choices without searching through entire conversation histories.

### How It Works at Runtime

A developer installs the library with Strands support, configures a Neo4j connection and an embedding provider (typically Amazon Bedrock Titan for AWS deployments), and calls a factory function that returns all four tools ready to use. These tools are then passed to the Strands agent alongside any other tools it needs.

During a conversation, the Strands agent loop decides when to use memory tools just like it decides when to use any other tool. If a user asks "what did we discuss last week about the project timeline?", the agent recognizes it needs to search its memory and calls the search context tool. If a user shares new preferences, the agent stores them via the add memory tool. The agent treats memory as another capability it can reason about and invoke when appropriate.

The integration handles the mismatch between Strands' synchronous tool interface and the library's async internals, so the agent framework doesn't need to worry about async execution. It also caches the underlying Neo4j client connection so repeated tool calls don't create new database connections.

### Where AWS Services Fit In

The integration is designed for the AWS ecosystem. Amazon Bedrock provides both the LLM that powers the Strands agent (typically Claude) and the embedding model that powers semantic search within memory (typically Titan Embed). Neo4j runs as the graph database, either as Neo4j Aura (managed cloud) or self-hosted. The combination means agents deployed on AWS can maintain rich, relationship-aware memory without building custom storage infrastructure.

The library also has a separate integration with AWS Bedrock AgentCore for agents deployed to that runtime, but the Strands integration is the primary path for developers building agents with the Strands SDK directly.

### Practical Example

The project includes a financial services advisor example that demonstrates the Strands integration in a realistic setting. Multiple specialized agents (KYC verification, anti-money-laundering, relationship management, compliance) share a Neo4j memory graph. As agents process customer interactions, they build up entity graphs of customers, accounts, transactions, and risk assessments. Each agent can search context to understand a customer's full history, explore entity relationships to trace connections between accounts, and store new findings for other agents to discover. The shared graph memory becomes the connective tissue between independently operating agents.
