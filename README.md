# AWS Bedrock AgentCore Starter Kit

This repository contains a collection of samples and starter projects for working with Amazon Bedrock AgentCore, focusing on deploying MCP (Model Context Protocol) servers and AI agents.

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
    *   **Description:** A LangGraph ReAct agent that deploys to AgentCore Runtime. Uses the `BedrockAgentCoreApp` pattern with `@app.entrypoint` decorator for cloud deployment via the AgentCore CLI (`agentcore configure`, `agentcore deploy`).
    *   **Key Features:** AgentCore Runtime deployment, CLI-based workflow, programmatic invocation via boto3, LangChain + MCP integration.
    *   **Use Case:** Deploying AI agents to AgentCore Runtime for managed scaling, observability, and enterprise deployment.

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

## Getting Started

1.  **Prerequisites:**
    *   Python 3.10+
    *   `uv` package manager
    *   AWS CLI & CDK CLI
    *   Docker

2.  **Explore a Project:**
    Navigate to any project folder and follow its `README.md` for deployment instructions.

    ```bash
    cd neo4j-agentcore-mcp-server
    # Follow instructions in README.md
    ```

## Documentation

*   [CLAUDE.md](CLAUDE.md) - detailed commands for Claude Code / Developers.
