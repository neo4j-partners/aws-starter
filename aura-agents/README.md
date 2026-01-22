# Neo4j Aura Agents Python Client

A Python client for calling external Neo4j Aura Agents via the REST API.

## Overview

[Neo4j Aura Agents](https://neo4j.com/developer/genai-ecosystem/aura-agent/) is an agent-creation platform that enables you to rapidly build, test, and deploy AI agents grounded by your enterprise data in AuraDB. Once you've created an agent and made it "external," you can call it via a REST API endpoint.

This client library provides:

- OAuth2 authentication with automatic token caching and refresh
- Both synchronous and asynchronous invocation methods
- Pydantic models for type-safe responses
- CLI tool for quick queries
- Interactive chat mode

## Prerequisites

1. **Neo4j Aura Account** with an AuraDB instance
2. **An Aura Agent** created in the Aura console with external visibility enabled
3. **API Credentials** from your Neo4j user profile (Settings → API Keys)

## Installation

```bash
cd aura-agents
uv sync
```

## Configuration

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your credentials:
   ```bash
   # From your Neo4j Aura user profile (API Keys)
   NEO4J_CLIENT_ID=your-client-id
   NEO4J_CLIENT_SECRET=your-client-secret

   # From the Aura Agent console (Copy endpoint button)
   NEO4J_AGENT_ENDPOINT=https://api.neo4j.io/v2beta1/projects/.../agents/.../invoke
   ```

## Usage

### Python API

```python
from src import AuraAgentClient

# Create client from environment variables
client = AuraAgentClient.from_env()

# Or create with explicit credentials
client = AuraAgentClient(
    client_id="your-client-id",
    client_secret="your-client-secret",
    endpoint_url="https://api.neo4j.io/v2beta1/projects/.../agents/.../invoke"
)

# Invoke the agent (sync)
response = client.invoke("What contracts mention Motorola?")
print(response.text)

# Invoke the agent (async)
import asyncio
response = asyncio.run(client.invoke_async("What's in the graph?"))
print(response.text)
```

### CLI

```bash
# Simple query
uv run python cli.py "What types of nodes exist?"

# JSON output (for scripting)
uv run python cli.py --json "List all relationships" | jq .text

# Verbose mode
uv run python cli.py -v "Explain the schema"

# Read from stdin
echo "What's in the graph?" | uv run python cli.py -
```

### Interactive Chat

```bash
uv run python examples/interactive_chat.py
```

## Examples

| Example | Description |
|---------|-------------|
| `examples/basic_usage.py` | Simple synchronous invocation |
| `examples/async_usage.py` | Concurrent async queries |
| `examples/interactive_chat.py` | Interactive Q&A session |

Run an example:
```bash
uv run python examples/basic_usage.py
```

## API Reference

### AuraAgentClient

```python
class AuraAgentClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        endpoint_url: str,
        token_url: str | None = None,  # Default: https://api.neo4j.io/oauth/token
        timeout: int | None = None,     # Default: 60 seconds
    ): ...

    def invoke(self, question: str) -> AgentResponse: ...
    async def invoke_async(self, question: str) -> AgentResponse: ...
    def clear_token_cache(self) -> None: ...

    @classmethod
    def from_env(cls) -> "AuraAgentClient": ...
```

### AgentResponse

```python
class AgentResponse:
    text: str | None           # Formatted response text
    thinking: str | None       # Agent reasoning steps
    tool_uses: list[ToolUse]   # Tools used during invocation
    status: str | None         # Request status (SUCCESS)
    usage: AgentUsage | None   # Token usage metrics
    raw_response: dict | None  # Full JSON for debugging
```

## How Aura Agents Work

1. **Create an Agent** in the Neo4j Aura console:
   - Configure your AuraDB instance as the data source
   - Define the agent's capabilities and behavior
   - Test with the built-in chat interface

2. **Make it External**:
   - Set visibility to "External" in the agent settings
   - Copy the endpoint URL

3. **Get API Credentials**:
   - Go to your Neo4j user profile → API Keys
   - Create a new API key and secret

4. **Call via REST API**:
   - Authenticate via OAuth2 to get a bearer token
   - POST to the agent endpoint with `{"input": "your question"}`

## Authentication Flow

The client handles OAuth2 automatically:

```
1. POST https://api.neo4j.io/oauth/token
   - Basic Auth: client_id:client_secret
   - Body: grant_type=client_credentials
   - Response: { access_token, expires_in: 3600, token_type: bearer }

2. POST {endpoint_url}
   - Authorization: Bearer {access_token}
   - Body: { input: "your question" }
   - Response: { text, thinking, status, usage, ... }
```

Tokens are cached and automatically refreshed when expired.

## Resources

- [Aura Agent Documentation](https://neo4j.com/developer/genai-ecosystem/aura-agent/)
- [Build a GraphRAG Agent in Minutes](https://neo4j.com/blog/genai/build-context-aware-graphrag-agent/)
- [Aura API Authentication](https://neo4j.com/docs/aura/platform/api/authentication/)
- [GraphAcademy: Aura Agents](https://graphacademy.neo4j.com/courses/workshop-genai/3-agents/5-aura-agents/)
