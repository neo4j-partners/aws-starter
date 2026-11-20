"""Aircraft Fleet Supervisor Agent on AgentCore Runtime.

A Strands supervisor delegates each question to one of two specialist
agents, each wrapped as a tool:

- Maintenance Agent: reliability, faults, components, sensors
- Operations Agent: flights, delays, routes, airports

The model, the Gateway MCP client, and the Gateway tools are created once,
on the first request. The client is rebuilt if its MCP session ends. A tool
call that finds the session ended rebuilds it and retries once. See
``fleet_supervisor.core.gateway_tools``. The agents are built per request.
See ``fleet_supervisor.core.agents`` for why.

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

from fleet_supervisor.core.agents import build_supervisor
from fleet_supervisor.core.config import LOCAL_PORT, MODEL_ID
from fleet_supervisor.core.credentials import load_credentials
from fleet_supervisor.core.events import EventMapper
from fleet_supervisor.core.gateway_tools import (
    REQUEST_SESSION_ID,
    GatewayConnection,
    GatewayTool,
    stop_quietly,
)
from fleet_supervisor.core.mcp import (
    GatewayAuth,
    build_gateway_auth,
    build_mcp_client,
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
    """Process-wide resources, created on the first request.

    ``model`` and ``tools`` last for the process. ``connection`` is replaced
    when its MCP session ends, and is None after a failed rebuild.
    """

    model: BedrockModel
    tools: list[GatewayTool]
    connection: GatewayConnection | None


_runtime: Runtime | None = None
_runtime_lock = threading.Lock()


@cache
def gateway_auth() -> GatewayAuth:
    """Return the process-wide Gateway auth.

    It outlives MCP client rebuilds, so a reconnect keeps the cached token.
    A failure is not cached, so the next request tries again.
    """
    return build_gateway_auth(load_credentials())


def _connect_mcp() -> GatewayConnection:
    """Start the Gateway client and fetch the filtered tool list."""
    # One filtered client serves both specialists: they need the same
    # two tools, so per-specialist filters would be identical.
    mcp_client = build_mcp_client(gateway_auth())
    try:
        # load_tools starts the client, then lists every page with the
        # client's tool filters applied. This runs in a worker thread with
        # no event loop, so asyncio.run is safe here.
        tools = list(asyncio.run(mcp_client.load_tools()))
        if not tools:
            raise RuntimeError(
                "The Gateway returned none of the specialist tools. "
                "Check the Gateway target and SPECIALIST_TOOL_FILTERS."
            )
    except Exception:
        # Stop the client's background thread; the next request retries.
        stop_quietly(mcp_client)
        raise
    logger.info("Gateway tools: %s", [t.tool_name for t in tools])
    return GatewayConnection(mcp_client, tools)


def _is_usable(runtime: Runtime | None, stale: GatewayConnection | None) -> bool:
    connection = None if runtime is None else runtime.connection
    return connection is not None and connection is not stale and connection.is_running()


def current_connection() -> GatewayConnection | None:
    """Return the current Gateway connection for a tool call."""
    runtime = _runtime
    return None if runtime is None else runtime.connection


async def reconnect(stale: GatewayConnection | None) -> GatewayConnection:
    """Return a running connection for a tool call whose ``stale`` one failed."""
    connection = (await get_runtime(stale)).connection
    if connection is None:
        # get_runtime sets the connection or raises, so this means a bug.
        raise RuntimeError("get_runtime returned no Gateway connection")
    return connection


def _start_runtime(stale: GatewayConnection | None = None) -> Runtime:
    """Return a runtime with a live MCP session, building or rebuilding it.

    ``stale`` is a connection a caller saw fail. It is rebuilt only if it is
    still the current one, so callers that arrive after a rebuild reuse the
    new connection instead of rebuilding again.
    """
    global _runtime
    with _runtime_lock:
        runtime = _runtime
        if _is_usable(runtime, stale):
            return runtime
        if runtime is None:
            # Build the model before the client, so a model error leaves
            # no client thread running.
            model = build_model()
            connection = _connect_mcp()
            tools = [
                GatewayTool(tool, current_connection, reconnect)
                for tool in connection.tools.values()
            ]
            _runtime = Runtime(model=model, tools=tools, connection=connection)
            return _runtime

        old = runtime.connection
        runtime.connection = None
        if old is not None:
            logger.warning(
                "Rebuilding the Gateway MCP client (session=%s)", REQUEST_SESSION_ID.get()
            )
            old.retire()
        connection = _connect_mcp()
        missing = sorted({tool.tool_name for tool in runtime.tools} - connection.tools.keys())
        if missing:
            logger.warning("The rebuilt Gateway client lacks tools %s", missing)
        runtime.connection = connection
        return runtime


async def get_runtime(stale: GatewayConnection | None = None) -> Runtime:
    """Return the shared runtime, starting or reconnecting it when needed.

    Pass ``stale`` when a call on that connection found the session ended.
    """
    runtime = _runtime
    if _is_usable(runtime, stale):
        return runtime
    return await asyncio.to_thread(_start_runtime, stale)


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
        REQUEST_SESSION_ID.set(session_id)
        # The prompt is user text, so only its length goes to INFO.
        logger.info("Request session=%s user=%s prompt_chars=%d", session_id, user_id, len(prompt))
        logger.debug("Request session=%s prompt=%s", session_id, prompt)

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
