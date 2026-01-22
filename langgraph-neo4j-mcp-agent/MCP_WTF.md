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

**Result:** FAILED - Same `Session terminated` error in Databricks

**Error:**
```
mcp.shared.exceptions.McpError: Session terminated
```

**Analysis:** Even with `terminate_on_close=False`, the session still terminates. This suggests the issue is NOT with the client-side session termination signal.

**Source:**
- Working code: `neo4j-agentcore-mcp-server/client/mcp_operations.py`
- AWS re:Post: [Session state management](https://repost.aws/questions/QU-YbedQP2Qj6QwqR5EnuELQ)

---

## Attempt 4: FastMCP Client (High-Level)

**Date:** 2026-01-21

**Hypothesis:** FastMCP's high-level client might handle session lifecycle differently.

**Code:**
```python
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

transport = StreamableHttpTransport(
    url=GATEWAY_URL,
    headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}
)
client = Client(transport)

async with client:
    tools = await client.list_tools()
```

**Result:** FAILED - Same `Session terminated` error

**Analysis:** FastMCP's `StreamableHttpTransport` does not expose `terminate_on_close` parameter. The error occurs during session initialization, not during context exit.

---

## Attempt 5: Low-Level MCP in test_mcp.ipynb

**Date:** 2026-01-21

**Hypothesis:** A minimal notebook using only the low-level MCP client would isolate the issue.

**Code (test_mcp.ipynb):**
```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from datetime import timedelta

async def list_tools_async():
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    async with streamablehttp_client(
        GATEWAY_URL,
        headers,
        timeout=timedelta(seconds=120),
        terminate_on_close=False
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            return result.tools
```

**Result:** FAILED - Same `Session terminated` error

**Error Stack:**
```
File "/tmp/ipykernel_8343/2883280512.py", line 10, in list_tools_async
    await session.initialize()
File "/opt/conda/lib/python3.11/site-packages/mcp/client/session.py", line 171, in initialize
    result = await self.send_request(
File "/opt/conda/lib/python3.11/site-packages/mcp/shared/session.py", line 306, in send_request
    raise McpError(response_or_error.error)
mcp.shared.exceptions.McpError: Session terminated
```

**Critical Finding:** The error occurs at `session.initialize()` - the very first MCP request. This means:
1. HTTP connection is established (no network error)
2. Server receives the `initialize` request
3. Server responds with "Session terminated" error

This is a **server-side rejection**, not a client-side issue.

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

1. ~~Is the AgentCore Gateway returning a proper MCP initialization response?~~ **Answer: No - it returns "Session terminated"**
2. Are there specific headers the Gateway expects? (Try `Accept`, `Content-Type`)
3. ~~Is the Bearer token being passed correctly through the session?~~ **Likely yes - HTTP connection succeeds**
4. ~~Does the Gateway support streamable_http or only specific transports?~~ **Yes - works locally**
5. ~~Is there a timeout issue during initialization?~~ **No - fails immediately**

**New Questions:**
6. Is the Bearer token expired? Check `token_expires_at` in `.mcp-credentials.json`
7. What `mcp` package version is installed in Databricks? Compare to local
8. Is the Runtime in a healthy state? Check `aws bedrock-agentcore-control get-agent-runtime`
9. What do the CloudWatch logs show for the Gateway/Runtime?
10. Does the same code work from local machine (outside Databricks)?

---

## Summary of Fixes

| Attempt | Approach | Result | Key Learning |
|---------|----------|--------|--------------|
| 1 | `client.session()` + `load_mcp_tools()` | FAILED | Session terminates during init |
| 2 | `client.get_tools()` stateless | FAILED | Same error - internal `load_mcp_tools` fails |
| 3 | Low-level `streamablehttp_client` with `terminate_on_close=False` | FAILED | Same error - not a client termination issue |
| 4 | FastMCP high-level client | FAILED | Same error - no `terminate_on_close` param |
| 5 | Minimal test_mcp.ipynb with low-level MCP | FAILED | Confirms server-side rejection |

## Key Technical Insight

~~The `langchain-mcp-adapters` library does NOT pass `terminate_on_close=False`~~ **UPDATE:** Even with `terminate_on_close=False`, the session still fails. The issue is **server-side**.

The error occurs at `session.initialize()` - the very first MCP protocol message. The HTTP connection succeeds, but the Gateway responds with "Session terminated".

**Possible Causes:**
1. **Token expired** - Bearer token from `.mcp-credentials.json` may have expired (1-hour lifetime)
2. **Gateway state** - The AgentCore Gateway or Runtime may be in a bad state
3. **MCP version mismatch** - Databricks `mcp` package version may be incompatible with Gateway
4. **Missing headers** - Gateway may require additional headers (e.g., `Content-Type`, `Accept`)
5. **Runtime not ready** - The MCP server runtime may not be fully initialized

## Next Steps to Try

1. **Refresh token** - Run token refresh script or redeploy stack
2. **Check mcp version** - `pip show mcp` in Databricks vs local
3. **Add headers** - Try adding `Content-Type: application/json` and `Accept: application/json, text/event-stream`
4. **Check Gateway logs** - Look at CloudWatch logs for the Gateway
5. **Test from local** - Run the same code locally to isolate Databricks-specific issues
6. **curl test** - Try raw HTTP request to Gateway to see response

---

## Diagnostic: Raw HTTP Test

Test the Gateway directly with curl to bypass MCP client:

```bash
# MCP initialize request
curl -X POST "${GATEWAY_URL}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

**Expected response:** JSON with `result.protocolVersion` and `result.capabilities`

**If "Session terminated":** The Gateway/Runtime is rejecting the connection

---

## Diagnostic: Check MCP Package Version

```python
# Run in Databricks
import mcp
print(f"mcp version: {mcp.__version__}")

# Check if terminate_on_close is supported
import inspect
from mcp.client.streamable_http import streamablehttp_client
sig = inspect.signature(streamablehttp_client)
print(f"streamablehttp_client params: {list(sig.parameters.keys())}")
```

---

## Token Status

From `.mcp-credentials.json`:
- **Token expires:** `2026-01-22T05:40:26+00:00`
- **Current time:** Check if token is still valid in Databricks timezone

---

## ROOT CAUSE FOUND

**Date:** 2026-01-21

**Curl test result:**
```json
{"jsonrpc":"2.0","id":0,"error":{"code":-32001,"message":"Invalid Bearer token"}}
```

**The "Session terminated" error is caused by an INVALID BEARER TOKEN.**

The MCP client successfully connects, sends the `initialize` request, but the Gateway rejects it with an authentication error. The MCP library translates this into "Session terminated".

**Fix:** Refresh the access token using the OAuth2 client credentials flow:

```bash
curl -X POST "${TOKEN_URL}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "scope=${SCOPE}"
```

Or run the token refresh script in `neo4j-agentcore-mcp-server/scripts/`

**After token refresh - Gateway responds correctly:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-03-26",
    "capabilities": {"tools": {"listChanged": false}},
    "serverInfo": {"version": "1.0.0", "name": "simple-neo4j-mcp-server-gateway"}
  }
}
```

---

## RESOLUTION

**Problem:** "Session terminated" error during MCP initialization

**Root Cause:** Expired/invalid Bearer token. The token in `.mcp-credentials.json` was no longer valid, causing the Gateway to reject the connection with error code `-32001`.

**Fix:** Refresh the access token using OAuth2 client credentials flow:

```python
import json
import subprocess
from datetime import datetime, timezone, timedelta

with open('.mcp-credentials.json') as f:
    creds = json.load(f)

# Refresh token via curl
result = subprocess.run([
    'curl', '-s', '-X', 'POST', creds['token_url'],
    '-H', 'Content-Type: application/x-www-form-urlencoded',
    '-d', f'grant_type=client_credentials&client_id={creds["client_id"]}&client_secret={creds["client_secret"]}&scope={creds["scope"]}'
], capture_output=True, text=True)

token_response = json.loads(result.stdout)
creds['access_token'] = token_response['access_token']
creds['token_expires_at'] = (datetime.now(timezone.utc) + timedelta(seconds=token_response.get('expires_in', 3600))).isoformat()

with open('.mcp-credentials.json', 'w') as f:
    json.dump(creds, f, indent=2)
```

**Lesson Learned:** Always check token validity first when debugging MCP connection issues. The "Session terminated" error is misleading - it actually means authentication failed.
