#!/usr/bin/env python3
"""Aircraft Fleet Supervisor Agent on AgentCore Runtime.

A Strands supervisor delegates each question to one of two specialist
agents, each wrapped as a tool:

- Maintenance Agent: reliability, faults, components, sensors
- Operations Agent: flights, delays, routes, airports

The model and the Gateway MCP client are created once, on the first request.
The agents are built per request. See ``core.agents`` for why.

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
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# When AgentCore Runtime runs this file as a script, sys.path holds server/
# and not the agent root, so ``core`` would not import.
_AGENT_ROOT = str(Path(__file__).resolve().parent.parent)
if _AGENT_ROOT not in sys.path:
    sys.path.insert(0, _AGENT_ROOT)

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402
from strands.models import BedrockModel  # noqa: E402
from strands.tools.mcp import MCPClient  # noqa: E402

from core.agents import build_supervisor  # noqa: E402
from core.config import LOCAL_PORT, MODEL_ID  # noqa: E402
from core.credentials import load_credentials  # noqa: E402
from core.events import EventMapper  # noqa: E402
from core.mcp import build_mcp_client  # noqa: E402
from core.model import build_model  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

GENERIC_ERROR = "The agent could not complete this request. Check the server logs for details."

app = BedrockAgentCoreApp()


@dataclass
class Runtime:
    """Process-wide resources, created once."""

    model: BedrockModel
    mcp_client: MCPClient
    tools: list[Any]


_runtime: Runtime | None = None
_runtime_lock = threading.Lock()


def _start_runtime() -> Runtime:
    """Build the model, start the MCP client, and fetch the filtered tool list."""
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            credentials = load_credentials()
            # One filtered client serves both specialists: they need the same
            # two tools, so per-specialist filters would be identical.
            mcp_client = build_mcp_client(credentials)
            mcp_client.start()
            try:
                tools = mcp_client.list_tools_sync()
            except Exception:
                # Stop the client's background thread; the next request retries.
                mcp_client.stop(None, None, None)
                raise
            logger.info("Gateway tools: %s", [t.tool_name for t in tools])
            _runtime = Runtime(model=build_model(), mcp_client=mcp_client, tools=tools)
        return _runtime


async def get_runtime() -> Runtime:
    """Return the shared runtime, starting it on the first call."""
    if _runtime is not None:
        return _runtime
    return await asyncio.to_thread(_start_runtime)


def extract_prompt(payload: dict) -> str | None:
    """Read the question from the payload keys clients commonly send."""
    return (
        payload.get("prompt")
        or payload.get("message")
        or payload.get("query")
        or payload.get("inputText")
        or payload.get("input")
    )


@app.entrypoint
async def invoke(payload: dict, context):
    """Stream the supervisor's answer as SSE events."""
    payload = payload or {}
    prompt = extract_prompt(payload)
    if not prompt:
        yield {"type": "error", "error": "No prompt provided. Include 'prompt' in the request."}
        return

    # AgentCore Runtime sets the session ID from the session header. A local
    # call without the header gets its own ID, so callers never share a session.
    session_id = getattr(context, "session_id", None) or str(uuid.uuid4())
    user_id = payload.get("user_id") or "anonymous"
    logger.info("Request session=%s user=%s prompt=%s", session_id, user_id, prompt[:100])

    try:
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
        logger.exception("Request failed for session %s", session_id)
        yield {"type": "error", "error": GENERIC_ERROR}


def main() -> None:
    """Local dev entry point: ``uv run fleet-supervisor-server``.

    Defaults to port 7071 so it can run beside graphrag-agent on 7070.
    ``AGENT_PORT`` overrides it.
    """
    logger.info(
        "Starting Aircraft Fleet Supervisor Agent (model %s) on port %s", MODEL_ID, LOCAL_PORT
    )
    app.run(port=LOCAL_PORT)


if __name__ == "__main__":
    # AgentCore Runtime runs this file directly and expects port 8080.
    port = int(os.environ.get("AGENT_PORT", "8080"))
    logger.info("Starting Aircraft Fleet Supervisor Agent (model %s) on port %s", MODEL_ID, port)
    app.run(port=port)
