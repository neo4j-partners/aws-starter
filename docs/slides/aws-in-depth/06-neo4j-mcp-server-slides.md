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


# The Neo4j MCP Server

What it provides, and how this project deploys it on Amazon Bedrock AgentCore

---

## What Is the Model Context Protocol?

- **MCP** is an open standard that lets AI agents use external tools through a consistent interface
- An agent does not need a hand-written integration per data source
- The agent asks the server "what tools do you have?", then calls them
- Tools are described in natural language, so the LLM can choose them on its own

---

## The Neo4j MCP Server

- Open-source server from Neo4j: [github.com/neo4j/mcp](https://github.com/neo4j/mcp)
- Exposes a Neo4j database to any MCP-capable agent
- Speaks the streamable HTTP MCP transport
- Verifies database connectivity on startup and exits immediately if it cannot connect
- Database credentials are passed to the container as environment variables, never to the agent

---

## Tools It Provides (Read-Only Mode)

This deployment runs the server with `NEO4J_READ_ONLY=true`:

| Tool | What it does |
|------|--------------|
| `get-schema` | Returns the graph schema: node labels, relationship types, properties |
| `read-cypher` | Executes a read-only Cypher query and returns results |

- Write tools are disabled by design for safe agent access
- The agent discovers the schema first, then generates and runs Cypher

---

## Why MCP for a Graph

- The agent does not need pre-built Neo4j integration code
- `get-schema` teaches the agent what is queryable, so generated Cypher matches the real model
- `read-cypher` lets the agent answer relationship and traversal questions directly
- One protocol, reusable across every agent framework (LangGraph, Strands, and others)

---

## Neo4j AgentCore MCP Server Overview

- Deploy the Neo4j MCP server to Amazon Bedrock AgentCore
- Put it behind an AgentCore Gateway with OAuth2 authentication
- Restrict access to machine-to-machine (M2M) only, designed for agents
- The Gateway provides unified auth, centralized access control, multi-target aggregation, and audit logging

---

## Deployment Architecture

An AI agent authenticates to Cognito (M2M OAuth2), sends MCP requests with a JWT to the AgentCore Gateway, which forwards them to the AgentCore Runtime hosting the Neo4j MCP server, which queries the Neo4j database.

---

![bg contain](images/neo4j-mcp-agentcore-architecture.png)

---

## The Request Flow

```
Agent  -> Cognito (client_credentials)        -> JWT token
Agent  -> Gateway + JWT                       -> validates token
Gateway-> OAuth Provider                      -> Runtime token
Gateway-> Runtime -> Neo4j MCP Server -> Neo4j
```

1. Agent gets an M2M JWT from Cognito
2. Agent calls the Gateway with the JWT
3. Gateway validates the JWT, then exchanges it for a Runtime OAuth token
4. Runtime invokes the MCP server, which queries Neo4j

---

## Authentication Layers

| Layer | Purpose |
|-------|---------|
| Cognito OAuth2 | M2M token for agent to Gateway |
| Gateway JWT | Validates agent identity (allowed_clients check) |
| OAuth2 Provider | Gateway to Runtime token exchange |
| Neo4j (env vars) | Database credentials inside the container |

No user accounts, no passwords to rotate. Agents use client credentials only.

---

## How `./deploy.sh` Sets It Up

1. Builds the **ARM64** Docker image of the Neo4j MCP server
2. Creates an Amazon ECR repository and pushes the image
3. Deploys the CDK stack
4. Runs custom resources for the OAuth provider and a Runtime health check

Deployment takes roughly 5 to 10 minutes. The Neo4j database must be running and reachable first.

---

## Custom Resources Solve Ordering

- **OAuth Provider** custom resource creates the OAuth2 credential provider used for Gateway to Runtime auth
- **Runtime Health Check** custom resource waits until the Runtime is ready before the Gateway Target is created
- Without the health gate, the Target can attach to a Runtime that is not yet serving requests

---

## Gateway Tool Name Prefixing

When tools are accessed through the Gateway, names are prefixed with the target name. This is intentional AWS behavior.

| Original Tool | Gateway Tool |
|---------------|--------------|
| `get-schema` | `neo4j-mcp-server-target___get-schema` |
| `read-cypher` | `neo4j-mcp-server-target___read-cypher` |

Delimiter is a triple underscore. It prevents tool-name collisions when the Gateway aggregates multiple MCP servers and drives request routing and authorization policies.

---

## Handling the Prefix: Dynamic Discovery

```python
# From client/mcp_operations.py
async def get_tool_map(session: ClientSession) -> dict[str, str]:
    """Map base tool names to actual (possibly prefixed) names."""
    result = await session.list_tools()
    tool_map = {}
    for tool in result.tools:
        full_name = tool.name
        if "___" in full_name:
            base_name = full_name.split("___", 1)[1]
        else:
            base_name = full_name
        tool_map[base_name] = full_name
    return tool_map
```

Discover names at runtime. The same pattern works for Gateway (prefixed) and direct Runtime (unprefixed) access.

---

## Why Claude Sonnet

- Tool names use hyphens: `get-schema`, `read-cypher`
- The MCP spec permits hyphens (`[a-zA-Z0-9_.-]{1,128}`)
- Claude accepts hyphenated tool names; Amazon Nova rejects them
- Using Claude means the project keeps the Neo4j server's standard tool names unchanged

---

## Testing the Deployment

| Command | What it does |
|---------|--------------|
| `./deploy.sh credentials` | Generates `.mcp-credentials.json` (gateway URL, client creds, JWT) |
| `./cloud.sh` | Full test **via Gateway**: initialize, tools/list, get-schema, read-cypher |
| `./cloud.sh token` | Checks JWT expiry |
| `./cloud-http.sh` | Raw JSON-RPC **direct to Runtime**, bypassing Gateway, for debugging |

Direct-Runtime testing isolates whether a failure is in the Gateway or the Runtime.

---

## Stack Outputs

| Output | Use |
|--------|-----|
| `GatewayUrl` | Primary endpoint for MCP clients |
| `CognitoMachineClientId` | Client ID for M2M auth |
| `CognitoTokenUrl` | OAuth2 token endpoint |
| `CognitoScope` | OAuth2 scope (`...-mcp/invoke`) |
| `MCPServerRuntimeArn` | ARN of the AgentCore Runtime |
| `CognitoUserPoolId` | Used to retrieve the client secret |

---

## Summary

- The Neo4j MCP server exposes a graph to agents through two read-only tools: `get-schema` and `read-cypher`
- MCP removes the need for custom Neo4j integration code per agent
- This project deploys it to AgentCore Runtime behind a Gateway with M2M OAuth2
- A single `./deploy.sh` builds the ARM64 image and deploys the stack, with custom resources handling OAuth provider and Runtime-readiness ordering
- Gateway tool prefixing is handled with runtime tool discovery, and Claude Sonnet keeps the standard hyphenated tool names
