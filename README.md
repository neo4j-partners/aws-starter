# AWS Bedrock AgentCore Starter Kit

This repository is primarily focused on **deploying the Neo4j MCP server to AWS Bedrock AgentCore** and demonstrating various approaches to calling that agent. Beyond basic deployment, the samples explore advanced AgentCore patterns including agent orchestration, observability, and production deployment strategies.

The core workflow centers on:
1. **Deploying an MCP server** (Neo4j graph database tools) to AgentCore Runtime
2. **Connecting AI agents** to the deployed MCP server via AgentCore Gateway
3. **Building GraphRAG on Bedrock** with the [`neo4j-graphrag`](https://neo4j.com/docs/neo4j-graphrag-python/current/) libraries: Bedrock-backed embeddings, LLM entity extraction, and vector retrieval over a Neo4j knowledge graph
4. **Exploring advanced patterns** like multi-agent orchestration, memory management, and cloud-native agent deployment

🧠 **[View the AWS + Neo4j presentation gallery](https://neo4j-partners.github.io/aws-starter/)**: current decks on semantic data discovery and grounded enterprise AI.

For a detailed explanation of how all the pieces fit together, see the **[Architecture Documentation](./docs/ARCHITECTURE.md)** which includes Mermaid diagrams, component descriptions, and end-to-end request flows.

---

## Project Overview

### Sample Matrix

| Sample | Domain and dataset | How the data is loaded | How it reaches Neo4j | Needs the MCP server | MCP `--env` | Deploys to Runtime | Main AWS services |
|--------|--------------------|------------------------|----------------------|----------------------|-------------|--------------------|-------------------|
| [`neo4j-mcp-server/`](./neo4j-mcp-server/) | Any graph | Not applicable | It is the MCP server | Not applicable | Any | Yes, the MCP server | AgentCore Runtime, Gateway, Cognito, Secrets Manager |
| [`quickstart/`](./quickstart/) | Any graph the MCP server points at | Not applicable | MCP Gateway | Yes | Default | No | AgentCore Gateway, Bedrock, SageMaker Unified Studio |
| [`demos/aircraft-fleet/pipeline/`](./demos/aircraft-fleet/pipeline/) | Aviation fleet digital twin | `pipeline/setup.sh` | Neo4j Python driver | No | Not applicable | No | Bedrock Titan embeddings, Bedrock Claude |
| [`demos/aircraft-fleet/graphrag-agent/`](./demos/aircraft-fleet/graphrag-agent/) | Aviation fleet digital twin | `pipeline/` | Neo4j Python driver | No | Not applicable | Yes | AgentCore Runtime, Bedrock |
| [`demos/aircraft-fleet/supervisor-agent/`](./demos/aircraft-fleet/supervisor-agent/) | Aviation fleet digital twin | `pipeline/` | MCP Gateway | Yes | `fleet` | Yes | AgentCore Runtime, Gateway, Bedrock, CloudWatch |
| [`demos/fraud-amazon-quick/fraud-iceberg/`](./demos/fraud-amazon-quick/fraud-iceberg/) | Synthetic fraud rings | `fraud-iceberg/` | Does not reach Neo4j | No | Not applicable | No | S3 Tables, Glue, Athena |
| [`demos/fraud-amazon-quick/graph-loader/`](./demos/fraud-amazon-quick/graph-loader/) | Synthetic fraud rings | `graph-loader/` from `data/` | Neo4j Python driver | No | Not applicable | No | None |
| [`demos/fraud-amazon-quick/fraud-memory-agent/`](./demos/fraud-amazon-quick/fraud-memory-agent/) | Synthetic fraud rings | `graph-loader/` | MCP Gateway for the graph, Neo4j Agent Memory Service for memory | Yes | `finance` | Yes | AgentCore Runtime, Gateway, Bedrock, Amazon Quick |
| [`demos/sec-filings-graphrag/`](./demos/sec-filings-graphrag/) | SEC 10-K filings | The notebook | Neo4j Python driver | No | Not applicable | No | Bedrock |
| [`integrations/databricks/`](./integrations/databricks/) | Any graph the MCP server points at | Not applicable | MCP Gateway through a Unity Catalog HTTP connection | Yes | Default | No | AgentCore Gateway, Cognito |
| [`integrations/neo4j-aura-agents/`](./integrations/neo4j-aura-agents/) | Any AuraDB graph | The Neo4j Aura console | Neo4j Aura Agents REST API | No | Not applicable | No | None |
| [`patterns/gateway-rbac-interceptor/`](./patterns/gateway-rbac-interceptor/) | None | Not applicable | Does not reach Neo4j | No, it has its own MCP server | Not applicable | Yes, its own MCP server | AgentCore Gateway, Cognito, Lambda |

The MCP `--env` column names the MCP server deployment each sample expects. `./deploy.py --env fleet` reads `.env.fleet` and writes `.mcp-credentials.fleet.json`. [`scripts/sync-credentials.sh`](./scripts/sync-credentials.sh) copies each deployment's credentials to the samples that use it.

### Suggested Learning Path

Each step needs only what earlier steps set up.

1. [`neo4j-mcp-server/`](./neo4j-mcp-server/) deploys the foundation.
2. [`quickstart/`](./quickstart/) makes the first Gateway call against whatever graph the server points at.
3. [`demos/sec-filings-graphrag/`](./demos/sec-filings-graphrag/) introduces GraphRAG retrieval in one notebook.
4. [`demos/aircraft-fleet/`](./demos/aircraft-fleet/) loads the aviation graph and queries it with a direct-driver agent. It then deploys the MCP server with `--env fleet` and adds multi-agent routing with the supervisor.
5. [`demos/fraud-amazon-quick/`](./demos/fraud-amazon-quick/) combines Athena, Neo4j, agent memory, and Amazon Quick in one demo.

---

### 🚀 **Neo4j MCP Server**

*   **[`neo4j-mcp-server`](./neo4j-mcp-server/)**
    *   **Description:** Deploys the official Neo4j MCP server to Amazon Bedrock AgentCore behind an AgentCore Gateway, so AI agents query a Neo4j graph through Model Context Protocol tools over one OAuth2-secured HTTPS endpoint. Neo4j credentials live in container environment variables, which avoids the `Authorization` header conflict between AgentCore and the Neo4j server.
    *   **Key Features:** Neo4j MCP server on AgentCore Runtime, AgentCore Gateway with Cognito M2M OAuth2, CDK infrastructure-as-code, ARM64 Docker packaging, dynamic Neo4j tool discovery (`get-schema`, `read-cypher`).
    *   **Use Case:** A shared Neo4j graph database exposed to Bedrock-hosted agents as MCP tools.

---

### 🤖 **Quickstart: LangGraph MCP Agent**

*   **[`quickstart`](./quickstart/)**
    *   **Description:** A standalone LangGraph ReAct agent that answers natural language questions about a Neo4j graph. It reaches Neo4j through the deployed MCP server over an AgentCore Gateway, discovers the graph's MCP tools at runtime, and reasons with Claude on Bedrock to explore the schema and generate Cypher.
    *   **Key Features:** Neo4j over MCP (`get-schema`, `read-cypher`), AgentCore Gateway with auto-refreshed Cognito OAuth2 token, Claude on Bedrock via the Converse API, automatic tool discovery via `langchain-mcp-adapters`, SageMaker Unified Studio inference-profile helper.
    *   **Use Case:** A self-contained example of querying Neo4j from a Bedrock agent through the Gateway, runnable locally or in SageMaker Studio.

---

## Demos

### 🛩️ **Aircraft Fleet** (`demos/aircraft-fleet/`)

*   **[`demos/aircraft-fleet`](./demos/aircraft-fleet/)**
    *   **Description:** A self-contained, end-to-end GraphRAG demo on Bedrock and Neo4j over an Aircraft Digital Twin fleet. Point every project at the same Neo4j instance with a matching embedder and they work with no code changes.
    *   **[`pipeline/`](./demos/aircraft-fleet/pipeline/):** builds an operational graph in Neo4j from synthetic fleet data, then enriches it from maintenance manuals with `neo4j-graphrag` using Bedrock Titan embeddings and Bedrock Claude entity extraction, fusing the structured and extracted graphs into one Neo4j knowledge graph.
    *   **[`graphrag-agent/`](./demos/aircraft-fleet/graphrag-agent/):** a Strands ReAct agent that answers questions over that graph, connecting directly to Neo4j with the driver and combining Text2Cypher with Bedrock-embedded vector search over the maintenance chunks.
    *   **[`supervisor-agent/`](./demos/aircraft-fleet/supervisor-agent/):** multi-agent supervisor over the same aviation graph. Classifies intent and routes to Maintenance or Operations specialists, then synthesizes cross-domain answers. It reaches Neo4j through the MCP server over an AgentCore Gateway with OAuth2 auth.
    *   **Key Features:** `pipeline/setup.sh` one-command five-stage Neo4j ingest, Bedrock structured-output extraction via forced `toolChoice`, structured plus unstructured graph fusion in Neo4j, direct-to-Neo4j Strands agent with live-schema caching, Text2Cypher plus Bedrock vector search, AgentCore Runtime deployment via `graphrag-agent/agent.sh`, multi-agent supervisor routing with CloudWatch observability.
    *   **Use Case:** A reference for building GraphRAG ingest on Bedrock and running an agent over the result, runnable top to bottom from one walkthrough.
    *   **Docs:** Start with the **[`demos/aircraft-fleet/README.md`](./demos/aircraft-fleet/README.md)** quickstart, then see **[`pipeline/README.md`](./demos/aircraft-fleet/pipeline/README.md)**, **[`graphrag-agent/README.md`](./demos/aircraft-fleet/graphrag-agent/README.md)**, and **[`supervisor-agent/README.md`](./demos/aircraft-fleet/supervisor-agent/README.md)** for details.

---

### 🕵️ **Fraud Investigation with Amazon Quick** (`demos/fraud-amazon-quick/`)

*   **[`graph-loader/`](./demos/fraud-amazon-quick/graph-loader/)**: loads the shared fraud dataset into Neo4j with a direct driver, then adds GDS fraud signals.
*   **[`fraud-memory-agent/`](./demos/fraud-amazon-quick/fraud-memory-agent/)**: Strands fraud-investigation agent over a synthetic finance graph, with `core/`, `client/`, and `server/` folders. It captures every turn in the Neo4j Agent Memory Service.
*   **[`fraud-iceberg/`](./demos/fraud-amazon-quick/fraud-iceberg/)**: loads the same fraud dataset into Iceberg tables and S3 Tables for Athena.

---

### 📄 **SEC Filings GraphRAG** (`demos/sec-filings-graphrag/`)

*   **[`demos/sec-filings-graphrag`](./demos/sec-filings-graphrag/)**: one notebook that teaches four levels of GraphRAG retrieval over SEC 10-K filings with Bedrock embeddings.

---

## Integrations and Patterns

> Supporting samples for connecting Neo4j to other platforms and securing the Gateway. The `gateway-rbac-interceptor` pattern is adapted from the official [Amazon Bedrock AgentCore Samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples) repository, simplified with shell-script wrappers.

*   **[`integrations/neo4j-aura-agents`](./integrations/neo4j-aura-agents/)**
    *   **Description:** A Python client for calling Neo4j Aura Agents over the REST API. Aura Agents are built and grounded in AuraDB through the Neo4j console, then exposed as an external endpoint; this client handles OAuth2 against `api.neo4j.io` and invokes the agent from code, a CLI, or an interactive chat. It is the managed-Neo4j counterpart to the self-hosted AgentCore agents in this repo.
    *   **Key Features:** Neo4j Aura Agent REST invocation, OAuth2 with cached auto-refreshed tokens, sync and async clients, Pydantic-typed responses with thinking and token usage, CLI and interactive chat.
    *   **Use Case:** Calling a graph-grounded agent that Neo4j Aura hosts for you, with no AWS infrastructure to deploy.

*   **[`integrations/databricks`](./integrations/databricks/)**
    *   **Description:** Connects Databricks workspaces to the Neo4j MCP server on AgentCore. A Unity Catalog HTTP connection with OAuth2 M2M auth proxies MCP requests from Databricks notebooks and LangGraph agents to the AgentCore Gateway, with Databricks handling token refresh. The official Neo4j MCP server is a compiled Go binary that Databricks Apps cannot host, so fronting it through AgentCore is the recommended pattern.
    *   **Key Features:** Unity Catalog HTTP connection to the AgentCore Gateway, OAuth2 M2M via Cognito, LangGraph agent with MLflow deployment, automatic token management, read-only Neo4j access.
    *   **Use Case:** Databricks teams querying Neo4j graph data in natural language, or deploying agents that combine Spark processing with the graph.

*   **[`patterns/gateway-rbac-interceptor`](./patterns/gateway-rbac-interceptor/)**
    *   **Description:** An OAuth2 Gateway demo with role-based access control and a Lambda Interceptor. Shows how to secure MCP server access with Cognito authentication and enforce per-group authorization at the AgentCore Gateway, the same Gateway layer that fronts the Neo4j MCP server.
    *   **Key Features:** Cognito User Pool integration, M2M and user OAuth flows, Lambda Interceptor for JWT claim extraction and authorization, RBAC via `cognito:groups`, identity header injection to downstream tools.
    *   **Use Case:** Securing Gateway access to MCP tools with authentication, multi-tenant access, and enterprise compliance.

---


## Documentation

*   [CLAUDE.md](CLAUDE.md) - detailed commands for Claude Code / Developers.
*   [demos/aircraft-fleet/README.md](demos/aircraft-fleet/README.md) - end-to-end walkthrough: build a GraphRAG ingest pipeline on Bedrock, load the Aircraft Digital Twin graph into Neo4j, and run an agent over it.
