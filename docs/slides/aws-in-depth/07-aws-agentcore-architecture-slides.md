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


# AWS Bedrock AgentCore

The runtime, the Gateway, and the agents that connect to Neo4j

---

## What AgentCore Provides

Amazon Bedrock AgentCore is purpose-built to run AI agents and their tools:

- **Runtime**: hosts agents and MCP servers in isolated microVMs
- **Gateway**: a single authenticated entry point that aggregates tools
- **Built-in observability**: tracing of reasoning, tool calls, and model calls
- **Managed scaling**: no auto-scaling groups, health checks, or cold-start tuning

---

## The End-to-End Request Flow

```
Agent  -> Cognito (client_credentials) -> JWT token
Agent  -> Gateway + JWT                -> validates token
Gateway-> OAuth Provider               -> Runtime token
Gateway-> Runtime -> MCP Server -> Neo4j
```

The agent authenticates once. The Gateway handles the credential exchange with the Runtime on every call.

---

## Authentication Layers

| Layer | Purpose |
|-------|---------|
| Cognito OAuth2 | M2M token for agent to Gateway |
| Gateway JWT | Validates agent identity |
| OAuth2 Provider | Gateway to Runtime token exchange |
| Neo4j (env vars) | Database credentials in the container |

M2M-only: no user accounts, no interactive login, no passwords to rotate.

---

## Built-In Observability

Deploying to AgentCore gives you, with zero configuration:

- **End-to-end tracing**: every reasoning step, tool invocation, and model call as spans with timing and inputs and outputs
- **OpenTelemetry format**: integrates with existing monitoring tools, no proprietary lock-in
- **CloudWatch dashboards**: token usage, latency, session duration, error rates

This is invaluable for debugging why an agent made a decision or why a tool call failed.

---

## Unified Agent-to-Tool Integration

The Gateway is a managed service providing one endpoint for many tools:

- **Tool discovery**: at scale, dozens or hundreds of MCP servers. Agents search for tools semantically across all of them
- **Unified authentication**: the agent authenticates once to the Gateway, which handles credential exchange with each backend MCP server

---

## The Agents in This Repo

Agents connect to the Neo4j MCP server through the Gateway:

| Agent | Pattern |
|-------|---------|
| **Fleet Agent** | Strands agent over a shared core |
| **Finance Agent** | Same LangGraph / Strands split over its own core |
| **Orchestrator Agent** | Multi-agent supervisor with routing |

Fleet Agent uses one `agent.sh` (`./agent.sh start`) with `runtime_app.py` and a Dockerfile over a shared `common/` core and uv project.

---

## Multi-Agent Orchestration

- An **orchestrator** routes each question to the right specialized agent
- Relationship and structure questions go to the Neo4j MCP agent
- Numeric and aggregation questions go to an analytics agent
- Questions needing both are answered in sequence and the results combined
- The end user asks in plain English. No Cypher or SQL knowledge required

---

## Summary

- AgentCore Runtime runs agents and MCP servers with microVM isolation, long sessions, and managed scaling
- The Gateway is one authenticated entry point with unified auth and semantic tool discovery
- Observability and tracing are built in and emitted as OpenTelemetry
- Agents connect to Neo4j through the Gateway, and an orchestrator routes across them
