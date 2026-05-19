# AWS Bedrock AgentCore Starter Kit

This repository is primarily focused on **deploying the Neo4j MCP server to AWS Bedrock AgentCore** and demonstrating various approaches to calling that agent. Beyond basic deployment, the samples explore advanced AgentCore patterns including agent orchestration, observability, and production deployment strategies.

The core workflow centers on:
1. **Deploying an MCP server** (Neo4j graph database tools) to AgentCore Runtime
2. **Connecting AI agents** to the deployed MCP server via AgentCore Gateway
3. **Building GraphRAG on Bedrock** with the [`neo4j-graphrag`](https://neo4j.com/docs/neo4j-graphrag-python/current/) libraries: Bedrock-backed embeddings, LLM entity extraction, and vector retrieval over a Neo4j knowledge graph
4. **Exploring advanced patterns** like multi-agent orchestration, memory management, and cloud-native agent deployment

📊 **[View the presentation slides](https://neo4j-partners.github.io/aws-starter/)**: a seven-part deck covering the aircraft graph data model, dual data architecture, GraphRAG, graph-enriched search, Neo4j Aura and agents, the Neo4j MCP server, and the AWS AgentCore architecture.

For a detailed explanation of how all the pieces fit together, see the **[Architecture Documentation](./docs/ARCHITECTURE.md)** which includes Mermaid diagrams, component descriptions, and end-to-end request flows.

---

## Project Overview

### 🚀 **Neo4j MCP Server**

*   **[`neo4j-agentcore-mcp-server`](./neo4j-agentcore-mcp-server/)**
    *   **Description:** Deploys the official Neo4j MCP server to Amazon Bedrock AgentCore behind an AgentCore Gateway, so AI agents query a Neo4j graph through Model Context Protocol tools over one OAuth2-secured HTTPS endpoint. Neo4j credentials live in container environment variables, which avoids the `Authorization` header conflict between AgentCore and the Neo4j server.
    *   **Key Features:** Neo4j MCP server on AgentCore Runtime, AgentCore Gateway with Cognito M2M OAuth2, CDK infrastructure-as-code, ARM64 Docker packaging, dynamic Neo4j tool discovery (`get-schema`, `read-cypher`).
    *   **Use Case:** A shared Neo4j graph database exposed to Bedrock-hosted agents as MCP tools.

---

### 🤖 **AgentCore Neo4j MCP Agent**

*   **[`neo4j-agentcore-agents`](./neo4j-agentcore-agents/)**
    *   **Description:** Two ReAct agents that answer natural language questions about a Neo4j graph and deploy to AgentCore Runtime with the `BedrockAgentCoreApp` pattern and the AgentCore CLI. Each reaches Neo4j through the MCP server over an AgentCore Gateway with OAuth2 auth, reasons with Claude on Bedrock, and runs as managed infrastructure with CloudWatch observability.
    *   **Key Features:** AgentCore Runtime deployment, Neo4j over an AgentCore Gateway with OAuth2 token refresh, Claude on Bedrock, CloudWatch observability and auto-scaling, multi-agent supervisor routing.
    *   **Use Case:** A production-shaped path for serving Neo4j-backed Bedrock agents with managed scaling, observability, and supervisor/worker orchestration.
    *   **Includes:**
        *   **[`finance-agent/`](./neo4j-agentcore-agents/finance-agent/)**: Neo4j SEC-filings agent. Simplest to deploy, no Docker. One `common/` core wired to both LangGraph and Strands; the Strands variant adds Neo4j-backed semantic memory.
        *   **[`orchestrator-agent/`](./neo4j-agentcore-agents/orchestrator-agent/)**: multi-agent supervisor over an aviation fleet graph. Classifies intent and routes to Maintenance or Operations specialists, then synthesizes cross-domain answers.

---

### 🛩️ **Fleet Agent Demo** (`fleet-agent-demo/`)

*   **[`fleet-agent-demo`](./fleet-agent-demo/)**
    *   **Description:** A self-contained, end-to-end GraphRAG demo on Bedrock and Neo4j over an Aircraft Digital Twin fleet. Point both projects at the same Neo4j instance with a matching embedder and they work with no code changes.
    *   **[`pipeline/`](./fleet-agent-demo/pipeline/):** builds an operational graph in Neo4j from synthetic fleet data, then enriches it from maintenance manuals with `neo4j-graphrag` using Bedrock Titan embeddings and Bedrock Claude entity extraction, fusing the structured and extracted graphs into one Neo4j knowledge graph.
    *   **[`agent/`](./fleet-agent-demo/agent/):** a Strands ReAct agent that answers questions over that graph, connecting directly to Neo4j with the driver and combining Text2Cypher with Bedrock-embedded vector search over the maintenance chunks.
    *   **Key Features:** `pipeline/setup.sh` one-command five-stage Neo4j ingest, Bedrock structured-output extraction via forced `toolChoice`, structured plus unstructured graph fusion in Neo4j, direct-to-Neo4j Strands agent with live-schema caching, Text2Cypher plus Bedrock vector search, AgentCore Runtime deployment via `agent/agent.sh`.
    *   **Use Case:** A reference for building GraphRAG ingest on Bedrock and running an agent over the result, runnable top to bottom from one walkthrough.
    *   **Docs:** Start with the **[`fleet-agent-demo/README.md`](./fleet-agent-demo/README.md)** quickstart, then see **[`fleet-agent-demo/pipeline/README.md`](./fleet-agent-demo/pipeline/README.md)** and **[`fleet-agent-demo/agent/README.md`](./fleet-agent-demo/agent/README.md)** for details.

---

### 🤖 **LangGraph MCP Agent**

*   **[`neo4j-agentcore-agents/langgraph-mcp-agent`](./neo4j-agentcore-agents/langgraph-mcp-agent/)**
    *   **Description:** A standalone LangGraph ReAct agent that answers natural language questions about a Neo4j graph. It reaches Neo4j through the deployed MCP server over an AgentCore Gateway, discovers the graph's MCP tools at runtime, and reasons with Claude on Bedrock to explore the schema and generate Cypher.
    *   **Key Features:** Neo4j over MCP (`get-schema`, `read-cypher`), AgentCore Gateway with auto-refreshed Cognito OAuth2 token, Claude on Bedrock via the Converse API, automatic tool discovery via `langchain-mcp-adapters`, SageMaker Unified Studio inference-profile helper.
    *   **Use Case:** A self-contained example of querying Neo4j from a Bedrock agent through the Gateway, runnable locally or in SageMaker Studio.

---

### 📦 **Infra Samples** (`infra-samples/`)

> Supporting samples for connecting Neo4j to AWS-hosted agents and securing the Gateway. The `simple-oauth-gateway` sample is adapted from the official [Amazon Bedrock AgentCore Samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples) repository, simplified with shell-script wrappers.

*   **[`infra-samples/aura-agents`](./infra-samples/aura-agents/)**
    *   **Description:** A Python client for calling Neo4j Aura Agents over the REST API. Aura Agents are built and grounded in AuraDB through the Neo4j console, then exposed as an external endpoint; this client handles OAuth2 against `api.neo4j.io` and invokes the agent from code, a CLI, or an interactive chat. It is the managed-Neo4j counterpart to the self-hosted AgentCore agents in this repo.
    *   **Key Features:** Neo4j Aura Agent REST invocation, OAuth2 with cached auto-refreshed tokens, sync and async clients, Pydantic-typed responses with thinking and token usage, CLI and interactive chat.
    *   **Use Case:** Calling a graph-grounded agent that Neo4j Aura hosts for you, with no AWS infrastructure to deploy.

*   **[`infra-samples/databrick-samples`](./infra-samples/databrick-samples/)**
    *   **Description:** Connects Databricks workspaces to the Neo4j MCP server on AgentCore. A Unity Catalog HTTP connection with OAuth2 M2M auth proxies MCP requests from Databricks notebooks and LangGraph agents to the AgentCore Gateway, with Databricks handling token refresh. The official Neo4j MCP server is a compiled Go binary that Databricks Apps cannot host, so fronting it through AgentCore is the recommended pattern.
    *   **Key Features:** Unity Catalog HTTP connection to the AgentCore Gateway, OAuth2 M2M via Cognito, LangGraph agent with MLflow deployment, automatic token management, read-only Neo4j access.
    *   **Use Case:** Databricks teams querying Neo4j graph data in natural language, or deploying agents that combine Spark processing with the graph.

*   **[`infra-samples/simple-oauth-gateway`](./infra-samples/simple-oauth-gateway/)**
    *   **Description:** An OAuth2 Gateway demo with role-based access control and a Lambda Interceptor. Shows how to secure MCP server access with Cognito authentication and enforce per-group authorization at the AgentCore Gateway, the same Gateway layer that fronts the Neo4j MCP server.
    *   **Key Features:** Cognito User Pool integration, M2M and user OAuth flows, Lambda Interceptor for JWT claim extraction and authorization, RBAC via `cognito:groups`, identity header injection to downstream tools.
    *   **Use Case:** Securing Gateway access to MCP tools with authentication, multi-tenant access, and enterprise compliance.

---


## Documentation

*   [CLAUDE.md](CLAUDE.md) - detailed commands for Claude Code / Developers.
*   [fleet-agent-demo/README.md](fleet-agent-demo/README.md) - end-to-end walkthrough: build a GraphRAG ingest pipeline on Bedrock, load the Aircraft Digital Twin graph into Neo4j, and run an agent over it.
