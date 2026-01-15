# AWS Bedrock AgentCore Starter Kit

This repository contains a collection of samples and starter projects for working with Amazon Bedrock AgentCore, focusing on deploying MCP (Model Context Protocol) servers and AI agents.

## Project Overview

### 🚀 **Neo4j MCP Server (Working Solution)**

*   **`simple-neo4j-mcp-server`**
    *   **Status:** ✅ Works
    *   **Description:** Successfully deploys the Neo4j MCP server to AWS Bedrock AgentCore using **environment variable authentication** (`NEO4J_MCP_HTTP_AUTH_MODE=env`). This approach bypasses the HTTP `Authorization` header conflict between AgentCore and the Neo4j server by storing Neo4j credentials securely in environment variables rather than passing them per-request.
    *   **Key Features:** Single-tenant deployment, credentials passed via CDK/Env vars, CDK-based infrastructure-as-code deployment, Docker container packaging for AgentCore Runtime.
    *   **Use Case:** Teams needing a shared Neo4j graph database accessible via MCP tools for AI agents.

---

### 🤖 **LangGraph MCP Agent**

*   **`sample-mcp-agent`**
    *   **Status:** ✅ Ready to Run
    *   **Description:** A standalone LangGraph ReAct agent that connects to any MCP server via AgentCore Gateway. Demonstrates the complete pattern of using LangChain + MCP + AWS Bedrock Claude to build intelligent agents that can reason and call tools. The agent dynamically discovers tools from connected MCP servers and uses a reasoning loop to decide which tools to call.
    *   **Key Features:** ReAct pattern for multi-step reasoning, OAuth2 Gateway authentication, Claude Sonnet 4 via AWS Bedrock Converse API, automatic tool discovery via `langchain-mcp-adapters`, streaming responses.
    *   **Use Case:** Building AI assistants that can query databases, call APIs, or perform complex multi-step tasks by chaining MCP tool calls.
    *   **Quick Start:**
        ```bash
        cd sample-mcp-agent
        ./agent.sh setup
        cp /path/to/.mcp-credentials.json .
        ./agent.sh "What is the database schema?"
        ```

---

### 📦 **Foundation Samples**

*   **`simple-agentcore-agent`**
    *   **Status:** ✅ Works
    *   **Description:** A "Hello World" baseline sample that deploys a simple AI agent to AgentCore Runtime using the Strands Agents framework. This is the best starting point for verifying your AWS setup, CDK bootstrapping, and understanding the basic AgentCore deployment lifecycle.
    *   **Key Features:** Minimal dependencies, `@app.entrypoint` decorator pattern, local development with hot reload, one-command cloud deployment.
    *   **Use Case:** First-time AgentCore users, testing AWS permissions, learning the deployment workflow.

*   **`sample-agentcore-mcp-server`**
    *   **Status:** ✅ Works
    *   **Description:** A generic MCP server example with Calculator and Greeter tools using the `FastMCP` framework. Demonstrates the foundational pattern for hosting custom Python MCP servers on AgentCore without the complexity of external databases or authentication.
    *   **Key Features:** FastMCP stateless HTTP transport, CloudFormation-based deployment, local development server, comprehensive test scripts.
    *   **Use Case:** Learning MCP server development, creating custom tool servers, prototyping before adding database integrations.

*   **`simple-oauth-gateway`**
    *   **Status:** ✅ Works
    *   **Description:** A comprehensive demo of setting up an OAuth2 Gateway with Role-Based Access Control (RBAC) and Lambda Interceptors. Shows how to secure MCP server access with Cognito-based authentication and implement custom authorization logic.
    *   **Key Features:** Cognito User Pool integration, machine-to-machine (M2M) OAuth flows, Lambda interceptors for request/response modification, RBAC patterns.
    *   **Use Case:** Production deployments requiring authentication, multi-tenant MCP servers, enterprise security compliance.

---

### ⚠️ **Experimental / Non-Working**

*   **`neo4j-mcp-server`**
    *   **Status:** ❌ Not Working
    *   **Description:** A documented attempt to deploy the Neo4j MCP server using **per-request HTTP authentication** rather than environment variables. This approach would allow multi-tenant deployments where each request carries its own Neo4j credentials.
    *   **Why it doesn't work:** Demonstrates an unsolvable protocol conflict where both AgentCore (OAuth) and Neo4j (Basic Auth) require the single available `Authorization` HTTP header. Custom header workarounds with Gateway interceptors also failed because headers don't propagate from Gateway to Runtime.
    *   **Value:** Useful as documentation of AgentCore limitations and as a reference for anyone attempting similar multi-tenant authentication patterns.
    *   **See:** `STATUS.md` in this directory for a deep dive into the technical blockers.

## Getting Started

1.  **Prerequisites:**
    *   Python 3.10+
    *   `uv` package manager
    *   AWS CLI & CDK CLI
    *   Docker

2.  **Explore a Project:**
    Navigate to any project folder and follow its `README.md` for deployment instructions.

    ```bash
    cd simple-neo4j-mcp-server
    # Follow instructions in README.md
    ```

## Documentation

*   [CLAUDE.md](CLAUDE.md) - detailed commands for Claude Code / Developers.
