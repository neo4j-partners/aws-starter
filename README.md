# AWS Bedrock AgentCore Starter Kit

This repository is primarily focused on **deploying the Neo4j MCP server to AWS Bedrock AgentCore** and demonstrating various approaches to calling that agent. Beyond basic deployment, the samples explore advanced AgentCore patterns including agent orchestration, observability, and production deployment strategies.

The core workflow centers on:
1. **Deploying an MCP server** (Neo4j graph database tools) to AgentCore Runtime
2. **Connecting AI agents** to the deployed MCP server via AgentCore Gateway
3. **Exploring advanced patterns** like multi-agent orchestration, memory management, and cloud-native agent deployment

📊 **[View the presentation slides](https://neo4j-partners.github.io/aws-starter/)** — a seven-part deck covering the aircraft graph data model, dual data architecture, GraphRAG, graph-enriched search, Neo4j Aura and agents, the Neo4j MCP server, and the AWS AgentCore architecture.

For a detailed explanation of how all the pieces fit together, see the **[Architecture Documentation](./docs/ARCHITECTURE.md)** which includes Mermaid diagrams, component descriptions, and end-to-end request flows.

---

## Project Overview

### 🚀 **Neo4j MCP Server**

*   **[`neo4j-agentcore-mcp-server`](./neo4j-agentcore-mcp-server/)**
    *   **Status:** ✅ Works
    *   **Description:** Deploys the official Neo4j MCP server to Amazon Bedrock AgentCore behind an AgentCore Gateway, so AI agents query a Neo4j graph through Model Context Protocol tools over one OAuth2-secured HTTPS endpoint. Neo4j credentials live in container environment variables, which avoids the `Authorization` header conflict between AgentCore and the Neo4j server.
    *   **Key Features:** Neo4j MCP server on AgentCore Runtime, AgentCore Gateway with Cognito M2M OAuth2, CDK infrastructure-as-code, ARM64 Docker packaging, dynamic Neo4j tool discovery (`get-schema`, `read-cypher`).
    *   **Use Case:** A shared Neo4j graph database exposed to Bedrock-hosted agents as MCP tools.

---

### 🤖 **LangGraph MCP Agent**

*   **[`neo4j-agentcore-agents/langgraph-mcp-agent`](./neo4j-agentcore-agents/langgraph-mcp-agent/)**
    *   **Status:** ✅ Ready to Run
    *   **Description:** A standalone LangGraph ReAct agent that connects to any MCP server via AgentCore Gateway. Demonstrates the complete pattern of using LangChain + MCP + AWS Bedrock Claude to build intelligent agents that can reason and call tools. The agent dynamically discovers tools from connected MCP servers and uses a reasoning loop to decide which tools to call.
    *   **Key Features:** ReAct pattern for multi-step reasoning, OAuth2 Gateway authentication, Claude Sonnet 4 via AWS Bedrock Converse API, automatic tool discovery via `langchain-mcp-adapters`, streaming responses.
    *   **Use Case:** Building AI assistants that can query databases, call APIs, or perform complex multi-step tasks by chaining MCP tool calls.

---

### 🤖 **AgentCore Neo4j MCP Agent**

*   **[`neo4j-agentcore-agents`](./neo4j-agentcore-agents/)**
    *   **Status:** ✅ Ready to Run
    *   **Description:** Two ReAct agents that deploy to AgentCore Runtime using the `BedrockAgentCoreApp` pattern with the `@app.entrypoint` decorator and the AgentCore CLI (`agentcore configure`, `agentcore deploy`). Each reaches Neo4j through the MCP server over an AgentCore Gateway with OAuth2 auth. This is the recommended final step to unlock AgentCore's advanced capabilities including built-in observability, auto-scaling, and multi-agent orchestration.
    *   **Key Features:** AgentCore Runtime deployment, MCP Gateway access with OAuth2 token refresh, programmatic invocation via boto3, CloudWatch observability, managed infrastructure.
    *   **Use Case:** Production deployments requiring managed scaling, observability dashboards, enterprise security, and supervisor/worker orchestration.
    *   **Includes:**
        *   **[`finance-agent/`](./neo4j-agentcore-agents/finance-agent/)** — SEC filings and corporate finance agent. Simplest to deploy, no Docker. Strands variant adds Neo4j-backed semantic memory.
        *   **[`orchestrator-agent/`](./neo4j-agentcore-agents/orchestrator-agent/)** — Multi-agent supervisor. Classifies intent and routes to Maintenance or Operations specialists, then synthesizes cross-domain answers.

---

### 🛩️ **Fleet Agent Demo** (`fleet-agent-demo/`)

*   **[`fleet-agent-demo`](./fleet-agent-demo/)**
    *   **Status:** ✅ Ready to Run
    *   **Description:** A self-contained, end-to-end GraphRAG demo pairing two projects that belong together. **`pipeline/`** is a worked example of a **GraphRAG ingestion pipeline on Amazon Bedrock**: it builds an operational graph from synthetic data, enriches it from unstructured maintenance manuals (Bedrock Titan embeddings plus Bedrock Claude entity extraction via Converse tool-use), and fuses the structured and extracted graphs into one Neo4j knowledge graph. **`agent/`** is a Strands ReAct agent that answers natural language questions over that graph, connecting directly to Neo4j (no MCP server, no Gateway) and combining Text2Cypher with vector search over the maintenance chunks. The **Aircraft Digital Twin** fleet is the example dataset. Point both at the same Neo4j instance with a matching embedder and they work with no code changes.
    *   **Key Features:** `pipeline/setup.sh` one-command five-stage ingest, structured-output extraction via `StructuredBedrockLLM` (forced `toolChoice`), structured plus unstructured graph fusion, a direct-to-Neo4j Strands agent with live-schema caching, local server plus thin CLI/demo/load-test clients, AgentCore Runtime deployment via `agent/agent.sh`.
    *   **Use Case:** A reference for building GraphRAG ingest on Bedrock and running an agent over the result, runnable top to bottom from one walkthrough.
    *   **Docs:** Start with the **[`fleet-agent-demo/README.md`](./fleet-agent-demo/README.md)** quickstart, then see **[`fleet-agent-demo/pipeline/README.md`](./fleet-agent-demo/pipeline/README.md)** and **[`fleet-agent-demo/agent/README.md`](./fleet-agent-demo/agent/README.md)** for details.

---

### 📊 **Databricks Integration** (`databrick_samples/`)

*   **[`databrick_samples`](./databrick_samples/)**
    *   **Status:** ✅ Ready to Run
    *   **Description:** Demonstrates how to connect Databricks workspaces to the Neo4j MCP server deployed on AWS AgentCore. Uses Unity Catalog HTTP connections with OAuth2 M2M authentication to securely proxy MCP requests from Databricks notebooks and LangGraph agents to the AgentCore Gateway. Databricks handles token refresh automatically.
    *   **Key Features:** Unity Catalog HTTP connection, OAuth2 M2M (Cognito), LangGraph agent with MLflow deployment, automatic token management, read-only Neo4j access.
    *   **Use Case:** Data teams using Databricks for analytics who need to query Neo4j graph data via natural language, or deploy AI agents that combine Spark data processing with graph database intelligence.
    *   **External Hosting** The official Neo4j MCP server is written in Go and runs as a compiled binary. Databricks Apps only supports Python/Node.js frameworks (Streamlit, Dash, Gradio) and cannot run Docker containers or compiled binaries. External hosting via AgentCore is the Databricks-recommended pattern for MCP servers that don't fit these constraints.
    *   **Unity Catalog HTTP connection** Databricks Unity Catalog supports creating HTTP connections to external services with built-in OAuth2 authentication. This allows secure, managed access to the AgentCore Gateway without hardcoding tokens in notebooks or code.

---

### 📦 **Infra Samples** (`infra_samples/`)

> These samples are adapted from the official [Amazon Bedrock AgentCore Samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples) repository. They have been simplified and restructured with shell script wrappers to make them easy to run and understand without navigating the full samples repo.

*   **[`infra_samples/simple-agentcore-agent`](./infra_samples/simple-agentcore-agent/)**
    *   **Status:** ✅ Works
    *   **Description:** A "Hello World" baseline sample that deploys a simple AI agent to AgentCore Runtime using the Strands Agents framework. This is the best starting point for verifying your AWS setup, CDK bootstrapping, and understanding the basic AgentCore deployment lifecycle.
    *   **Key Features:** Minimal dependencies, `@app.entrypoint` decorator pattern, local development with hot reload, one-command cloud deployment.
    *   **Use Case:** First-time AgentCore users, testing AWS permissions, learning the deployment workflow.

*   **[`infra_samples/sample-agentcore-mcp-server`](./infra_samples/sample-agentcore-mcp-server/)**
    *   **Status:** ✅ Works
    *   **Description:** A generic MCP server example with Calculator and Greeter tools using the `FastMCP` framework. Demonstrates the foundational pattern for hosting custom Python MCP servers on AgentCore without the complexity of external databases or authentication.
    *   **Key Features:** FastMCP stateless HTTP transport, CloudFormation-based deployment, local development server, comprehensive test scripts.
    *   **Use Case:** Learning MCP server development, creating custom tool servers, prototyping before adding database integrations.

*   **[`infra_samples/simple-oauth-gateway`](./infra_samples/simple-oauth-gateway/)**
    *   **Status:** ✅ Works
    *   **Description:** A comprehensive demo of setting up an OAuth2 Gateway with Role-Based Access Control (RBAC) and Lambda Interceptors. Shows how to secure MCP server access with Cognito-based authentication and implement custom authorization logic.
    *   **Key Features:** Cognito User Pool integration, machine-to-machine (M2M) OAuth flows, Lambda interceptors for request/response modification, RBAC patterns.
    *   **Use Case:** Production deployments requiring authentication, multi-tenant MCP servers, enterprise security compliance.

---


## Documentation

*   [CLAUDE.md](CLAUDE.md) - detailed commands for Claude Code / Developers.
*   [fleet-agent-demo/README.md](fleet-agent-demo/README.md) - end-to-end walkthrough: build a GraphRAG ingest pipeline on Bedrock, load the Aircraft Digital Twin graph into Neo4j, and run an agent over it.
