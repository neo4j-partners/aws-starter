# MCP Session Troubleshooting Log

## Problem

`McpError: Session terminated` when using `langchain-mcp-adapters` with Bedrock AgentCore Gateway in a Jupyter notebook.

## Environment

- Python 3.11 (Databricks/conda)
- langchain-mcp-adapters >= 0.2.1
- langgraph >= 1.0.6
- Transport: `streamable_http`
- Server: AWS Bedrock AgentCore MCP Gateway

## Error Stack Trace

```
ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  File "/opt/conda/lib/python3.11/site-packages/langchain_mcp_adapters/tools.py", line 481, in load_mcp_tools
    await tool_session.initialize()
  File "/opt/conda/lib/python3.11/site-packages/mcp/client/session.py", line 153, in initialize
    result = await self.send_request(
  File "/opt/conda/lib/python3.11/site-packages/mcp/shared/session.py", line 288, in send_request
    raise McpError(response_or_error.error)
mcp.shared.exceptions.McpError: Session terminated
```

---

## Attempt 1: Explicit Session Context Manager

**Date:** 2026-01-21

**Hypothesis:** Using `client.session()` with `load_mcp_tools()` would properly manage session lifecycle.

**Code (BEFORE):**
```python
async def query_async(question: str) -> str:
    client = MultiServerMCPClient({
        "neo4j": {
            "transport": "streamable_http",
            "url": GATEWAY_URL,
            "headers": {"Authorization": f"Bearer {ACCESS_TOKEN}"},
        }
    })

    # Use explicit session context manager
    async with client.session("neo4j") as session:
        tools = await load_mcp_tools(session)
        agent = create_react_agent(model=llm, tools=tools, prompt=SYSTEM_PROMPT)
        result = await agent.ainvoke({"messages": [("human", question)]})
        # ...
```

**Result:** FAILED - Same `Session terminated` error

**Source:** [LangChain MCP Adapters README](https://github.com/langchain-ai/langchain-mcp-adapters)

---

## Attempt 2: Stateless Pattern with get_tools()

**Date:** 2026-01-21

**Hypothesis:** Using `client.get_tools()` (stateless pattern) would avoid session lifecycle conflicts since each tool call creates its own session.

**Code (AFTER):**
```python
async def query_async(question: str) -> str:
    client = MultiServerMCPClient({
        "neo4j": {
            "transport": "streamable_http",
            "url": GATEWAY_URL,
            "headers": {"Authorization": f"Bearer {ACCESS_TOKEN}"},
        }
    })

    # Use get_tools() for stateless operation
    tools = await client.get_tools()
    agent = create_react_agent(model=llm, tools=tools, prompt=SYSTEM_PROMPT)
    result = await agent.ainvoke({"messages": [("human", question)]})
    # ...
```

**Result:** FAILED - Same `Session terminated` error

**Analysis:** The error occurs during `load_mcp_tools` internally when `get_tools()` tries to initialize a session. The problem is at the session initialization level, not the tool invocation level.

**Source:** [LangChain MCP Documentation](https://docs.langchain.com/oss/python/langchain/mcp)

---

## Attempt 3: Low-Level MCP Client with terminate_on_close=False

**Date:** 2026-01-21

**Hypothesis:** The langchain-mcp-adapters library doesn't properly handle AgentCore Gateway's session requirements. Use the low-level `mcp` client directly with `terminate_on_close=False` as shown in the working `mcp_operations.py` pattern.

**Discovery:** Found working pattern in `neo4j-agentcore-mcp-server/client/mcp_operations.py`:

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from datetime import timedelta

async with streamablehttp_client(
    mcp_url,
    headers,
    timeout=timedelta(seconds=120),
    terminate_on_close=False  # <-- KEY PARAMETER!
) as (read_stream, write_stream, _):
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        # ... use session
```

**Key Differences from langchain-mcp-adapters:**
1. Uses `terminate_on_close=False` - prevents premature session termination
2. Explicit timeout configuration (120 seconds)
3. Manual session lifecycle management
4. Headers passed directly to `streamablehttp_client`

**Code (AFTER):**
```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from datetime import timedelta

async def query_async(question: str) -> str:
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    async with streamablehttp_client(
        GATEWAY_URL,
        headers,
        timeout=timedelta(seconds=120),
        terminate_on_close=False
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Get tools directly from session
            tool_result = await session.list_tools()
            # Convert to LangChain tools...
```

**Implementation Applied to `neo4j_simple_mcp_agent.ipynb`:**
```python
async def query_async(question: str) -> str:
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    # Use low-level MCP client with terminate_on_close=False
    async with streamablehttp_client(
        GATEWAY_URL,
        headers,
        timeout=timedelta(seconds=120),
        terminate_on_close=False
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            agent = create_react_agent(model=llm, tools=tools, prompt=SYSTEM_PROMPT)
            result = await agent.ainvoke({"messages": [("human", question)]})
            # ...
```

**Result:** PENDING - Test in Databricks

**Source:**
- Working code: `neo4j-agentcore-mcp-server/client/mcp_operations.py`
- AWS re:Post: [Session state management](https://repost.aws/questions/QU-YbedQP2Qj6QwqR5EnuELQ)

---

## Research Notes

### Transport Naming
- Must use `streamable_http` (underscore), not `streamable-http` (hyphen)
- Source: [GitHub Issue #322](https://github.com/langchain-ai/langchain-mcp-adapters/issues/322)

### Session Lifecycle
- Streamable HTTP sessions require `Mcp-Session-Id` header management
- Server assigns session ID during initialization
- Source: [MCP Transports Spec](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)

### Related Issues
- [Issue #265](https://github.com/langchain-ai/langchain-mcp-adapters/issues/265) - McpError: Connection closed
- [Issue #373](https://github.com/langchain-ai/langchain-mcp-adapters/issues/373) - stdio transport failures

### LangChain MCP Adapters Internals
- `get_tools()` internally calls `load_mcp_tools()` which creates a session
- Session initialization happens in `tools.py:481`
- Uses `_create_streamable_http_session` from `sessions.py:322`

---

## Questions to Investigate

1. Is the AgentCore Gateway returning a proper MCP initialization response?
2. Are there specific headers the Gateway expects?
3. Is the Bearer token being passed correctly through the session?
4. Does the Gateway support streamable_http or only specific transports?
5. Is there a timeout issue during initialization?

---

## Summary of Fixes

| Attempt | Approach | Result | Key Learning |
|---------|----------|--------|--------------|
| 1 | `client.session()` + `load_mcp_tools()` | FAILED | Session terminates during init |
| 2 | `client.get_tools()` stateless | FAILED | Same error - internal `load_mcp_tools` fails |
| 3 | Low-level `streamablehttp_client` with `terminate_on_close=False` | PENDING | Matches working `mcp_operations.py` pattern |

## Key Technical Insight

The `langchain-mcp-adapters` library does NOT pass `terminate_on_close=False` to `streamablehttp_client`, but this parameter is **critical** for AgentCore Gateway:

```python
# langchain-mcp-adapters (problematic)
async with streamablehttp_client(url, headers) as (r, w, _):
    ...

# Working pattern (mcp_operations.py)
async with streamablehttp_client(url, headers, terminate_on_close=False) as (r, w, _):
    ...
```

The `terminate_on_close=False` prevents the client from sending a session termination signal when the context exits, which AgentCore Gateway seems to interpret as an early termination request.
