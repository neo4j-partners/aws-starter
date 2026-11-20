"""Aircraft Fleet Supervisor Agent on AgentCore Runtime.

A Strands supervisor delegates each question to one of two specialist
agents, each wrapped as a tool:

- Maintenance Agent: reliability, faults, components, sensors
- Operations Agent: flights, delays, routes, airports

The model and the Gateway MCP client are created once, on the first request.
The client is rebuilt if its MCP session ends.
The agents are built per request. See ``fleet_supervisor.core.agents`` for why.

Local testing:
    uv run fleet-supervisor-server
    uv run fleet-supervisor-cli "What are the most common maintenance faults?"

Cloud deployment:
    ./agent.sh deploy
    ./agent.sh invoke-cloud "What are the most common maintenance faults?"
"""

import asyncio
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from functools import cache
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

from fleet_supervisor.core.agents import build_supervisor
from fleet_supervisor.core.config import LOCAL_PORT, MODEL_ID
from fleet_supervisor.core.credentials import load_credentials
from fleet_supervisor.core.events import EventMapper
from fleet_supervisor.core.mcp import (
    GatewayAuth,
    build_gateway_auth,
    build_mcp_client,
    list_all_tools,
)
from fleet_supervisor.core.model import build_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

GENERIC_ERROR = "The agent could not complete this request. Check the server logs for details."
NO_PROMPT_ERROR = "No prompt provided. Include 'prompt' in the request."

app = BedrockAgentCoreApp()


@dataclass
class Runtime:
    """Process-wide resources, created once and rebuilt if the MCP session ends."""

    model: BedrockModel
    mcp_client: MCPClient
    tools: list[Any]


_runtime: Runtime | None = None
_runtime_lock = threading.Lock()


@cache
def gateway_auth() -> GatewayAuth:
    """Return the process-wide Gateway auth.

    It outlives MCP client rebuilds, so a reconnect keeps the cached token.
    A failure is not cached, so the next request tries again.
    """
    return build_gateway_auth(load_credentials())


def _session_is_running(client: MCPClient) -> bool:
    """Report whether the MCP client's session is still up.

    Strands has no public health check. ``_is_session_active`` is the check
    ``list_tools_sync`` and ``call_tool`` make before they run, so it matches
    when tool calls would start failing. tests/test_server.py pins it.
    """
    return client._is_session_active()


def _stop_quietly(client: MCPClient) -> None:
    """Stop the client, logging a failure so it cannot hide the original error."""
    try:
        client.stop(None, None, None)
    except Exception:
        logger.exception("Error while stopping the MCP client")


def _connect_mcp() -> tuple[MCPClient, list[Any]]:
    """Start the Gateway client and fetch the filtered tool list."""
    # One filtered client serves both specialists: they need the same
    # two tools, so per-specialist filters would be identical.
    mcp_client = build_mcp_client(gateway_auth())
    try:
        mcp_client.start()
        tools = list_all_tools(mcp_client)
        if not tools:
            raise RuntimeError(
                "The Gateway returned none of the specialist tools. "
                "Check the Gateway target and SPECIALIST_TOOL_FILTERS."
            )
    except Exception:
        # Stop the client's background thread; the next request retries.
        _stop_quietly(mcp_client)
        raise
    logger.info("Gateway tools: %s", [t.tool_name for t in tools])
    return mcp_client, tools


def _start_runtime() -> Runtime:
    """Return a runtime with a live MCP session, building or rebuilding it."""
    global _runtime
    with _runtime_lock:
        if _runtime is not None and _session_is_running(_runtime.mcp_client):
            return _runtime
        if _runtime is not None:
            logger.warning("The MCP session ended; reconnecting to the Gateway")
            _stop_quietly(_runtime.mcp_client)
            model = _runtime.model
            _runtime = None
        else:
            # Build the model before the client, so a model error leaves
            # no client thread running.
            model = build_model()
        mcp_client, tools = _connect_mcp()
        _runtime = Runtime(model=model, mcp_client=mcp_client, tools=tools)
        return _runtime


async def get_runtime() -> Runtime:
    """Return the shared runtime, starting or reconnecting it when needed."""
    runtime = _runtime
    if runtime is not None and _session_is_running(runtime.mcp_client):
        return runtime
    return await asyncio.to_thread(_start_runtime)


def extract_prompt(payload: Any) -> str | None:
    """Read the question from the payload keys clients commonly send."""
    if not isinstance(payload, dict):
        return None
    for key in ("prompt", "message", "query", "inputText", "input"):
        if isinstance(value := payload.get(key), str) and value.strip():
            return value
    return None


@app.entrypoint
async def invoke(payload: Any, context):
    """Stream the supervisor's answer as SSE events."""
    # Everything runs inside the try, so no input can raise past the handler
    # and send exception text to the client.
    try:
        prompt = extract_prompt(payload)
        if not prompt:
            yield {"type": "error", "error": NO_PROMPT_ERROR}
            return

        # AgentCore Runtime sets the session ID from the session header. A
        # local call without the header gets its own ID, so callers never
        # share a session.
        session_id = getattr(context, "session_id", None) or str(uuid.uuid4())
        user_id = payload.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            user_id = "anonymous"
        logger.info("Request session=%s user=%s prompt=%s", session_id, user_id, prompt[:100])

        # The workload access token is valid here, on the request path, so
        # the Gateway token is fetched here too. See GatewayAuth.
        gateway = await asyncio.to_thread(gateway_auth)
        await gateway.prepare_request()
        runtime = await get_runtime()
        supervisor = build_supervisor(runtime.model, runtime.tools)
        mapper = EventMapper()
        async for event in supervisor.stream_async(prompt):
            for client_event in mapper.map(event):
                yield client_event
        logger.info("Session %s handled by %s", session_id, mapper.specialists or "supervisor only")
        yield {"type": "complete"}
    except Exception:
        # Log the details here; the client gets a generic message only.
        logger.exception("Request failed")
        yield {"type": "error", "error": GENERIC_ERROR}


def main(default_port: int = LOCAL_PORT) -> None:
    """Start the server in the foreground. Stop it with Ctrl+C.

    ``uv run fleet-supervisor-server`` calls this with the local port, 7071,
    so the supervisor can run beside graphrag-agent on 7070. The root
    ``main.py`` calls it with 8080, the port AgentCore Runtime expects.
    ``AGENT_PORT`` overrides both.
    """
    port = int(os.environ.get("AGENT_PORT", str(default_port)))
    logger.info("Starting Aircraft Fleet Supervisor Agent (model %s) on port %s", MODEL_ID, port)
    app.run(port=port)
