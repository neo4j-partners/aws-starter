# AWS Bedrock AgentCore Starter Kit

This repository is primarily focused on **deploying the Neo4j MCP server to AWS Bedrock AgentCore** and demonstrating various approaches to calling that agent. Beyond basic deployment, the samples explore advanced AgentCore patterns including agent orchestration, observability, and production deployment strategies.

The core workflow centers on:
1. **Deploying an MCP server** (Neo4j graph database tools) to AgentCore Runtime
2. **Connecting AI agents** to the deployed MCP server via AgentCore Gateway
3. **Exploring advanced patterns** like multi-agent orchestration, memory management, and cloud-native agent deployment

## Recommended Learning Path

| Step | Project | Purpose |
|------|---------|---------|
| 1 | [`neo4j-agentcore-mcp-server`](./neo4j-agentcore-mcp-server/) | Deploy the Neo4j MCP server to AgentCore |
| 2 | [`langgraph-neo4j-mcp-agent`](./langgraph-neo4j-mcp-agent/) | Run locally to verify deployment and test MCP tools |
| 3 | [`agentcore-neo4j-mcp-agent`](./agentcore-neo4j-mcp-agent/) | Deploy the agent itself to AgentCore for orchestration and observability |

---

## Project Overview

### 🚀 **Neo4j MCP Server**

*   **[`neo4j-agentcore-mcp-server`](./neo4j-agentcore-mcp-server/)**
    *   **Status:** ✅ Works
    *   **Description:** Successfully deploys the Neo4j MCP server to AWS Bedrock AgentCore using **environment variable authentication** (`NEO4J_MCP_HTTP_AUTH_MODE=env`). This approach bypasses the HTTP `Authorization` header conflict between AgentCore and the Neo4j server by storing Neo4j credentials securely in environment variables rather than passing them per-request.
    *   **Key Features:** Single-tenant deployment, credentials passed via CDK/Env vars, CDK-based infrastructure-as-code deployment, Docker container packaging for AgentCore Runtime.
    *   **Use Case:** Teams needing a shared Neo4j graph database accessible via MCP tools for AI agents.

---

### 🤖 **LangGraph MCP Agent**

*   **[`langgraph-neo4j-mcp-agent`](./langgraph-neo4j-mcp-agent/)**
    *   **Status:** ✅ Ready to Run
    *   **Description:** A standalone LangGraph ReAct agent that connects to any MCP server via AgentCore Gateway. Demonstrates the complete pattern of using LangChain + MCP + AWS Bedrock Claude to build intelligent agents that can reason and call tools. The agent dynamically discovers tools from connected MCP servers and uses a reasoning loop to decide which tools to call.
    *   **Key Features:** ReAct pattern for multi-step reasoning, OAuth2 Gateway authentication, Claude Sonnet 4 via AWS Bedrock Converse API, automatic tool discovery via `langchain-mcp-adapters`, streaming responses.
    *   **Use Case:** Building AI assistants that can query databases, call APIs, or perform complex multi-step tasks by chaining MCP tool calls.

---

### 🤖 **AgentCore Neo4j MCP Agent**

*   **[`agentcore-neo4j-mcp-agent`](./agentcore-neo4j-mcp-agent/)**
    *   **Status:** ✅ Ready to Run
    *   **Description:** A LangGraph ReAct agent that deploys to AgentCore Runtime. Uses the `BedrockAgentCoreApp` pattern with `@app.entrypoint` decorator for cloud deployment via the AgentCore CLI (`agentcore configure`, `agentcore deploy`). This is the recommended final step to unlock AgentCore's advanced capabilities including built-in observability, auto-scaling, and multi-agent orchestration patterns.
    *   **Key Features:** AgentCore Runtime deployment, CLI-based workflow, programmatic invocation via boto3, LangChain + MCP integration, CloudWatch observability, managed infrastructure.
    *   **Use Case:** Production deployments requiring managed scaling, observability dashboards, enterprise security, and advanced orchestration patterns like supervisor/worker agents.

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

### 📦 **Foundation Samples** (`foundation_samples/`)

> These samples are adapted from the official [Amazon Bedrock AgentCore Samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples) repository. They have been simplified and restructured with shell script wrappers to make them easy to run and understand without navigating the full samples repo.

*   **[`foundation_samples/simple-agentcore-agent`](./foundation_samples/simple-agentcore-agent/)**
    *   **Status:** ✅ Works
    *   **Description:** A "Hello World" baseline sample that deploys a simple AI agent to AgentCore Runtime using the Strands Agents framework. This is the best starting point for verifying your AWS setup, CDK bootstrapping, and understanding the basic AgentCore deployment lifecycle.
    *   **Key Features:** Minimal dependencies, `@app.entrypoint` decorator pattern, local development with hot reload, one-command cloud deployment.
    *   **Use Case:** First-time AgentCore users, testing AWS permissions, learning the deployment workflow.

*   **[`foundation_samples/sample-agentcore-mcp-server`](./foundation_samples/sample-agentcore-mcp-server/)**
    *   **Status:** ✅ Works
    *   **Description:** A generic MCP server example with Calculator and Greeter tools using the `FastMCP` framework. Demonstrates the foundational pattern for hosting custom Python MCP servers on AgentCore without the complexity of external databases or authentication.
    *   **Key Features:** FastMCP stateless HTTP transport, CloudFormation-based deployment, local development server, comprehensive test scripts.
    *   **Use Case:** Learning MCP server development, creating custom tool servers, prototyping before adding database integrations.

*   **[`foundation_samples/simple-oauth-gateway`](./foundation_samples/simple-oauth-gateway/)**
    *   **Status:** ✅ Works
    *   **Description:** A comprehensive demo of setting up an OAuth2 Gateway with Role-Based Access Control (RBAC) and Lambda Interceptors. Shows how to secure MCP server access with Cognito-based authentication and implement custom authorization logic.
    *   **Key Features:** Cognito User Pool integration, machine-to-machine (M2M) OAuth flows, Lambda interceptors for request/response modification, RBAC patterns.
    *   **Use Case:** Production deployments requiring authentication, multi-tenant MCP servers, enterprise security compliance.

---

## Documentation

*   [CLAUDE.md](CLAUDE.md) - detailed commands for Claude Code / Developers.
