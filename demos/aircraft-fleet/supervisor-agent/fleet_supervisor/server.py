"""Aircraft Fleet Supervisor Agent on AgentCore Runtime.

A Strands supervisor delegates each question to one of two specialist
agents, each wrapped as a tool:

- Maintenance Agent: reliability, faults, components, sensors
- Operations Agent: flights, delays, routes, airports

The model, the Gateway MCP client, and the Gateway tools are created once,
on the first request. The client is rebuilt if its MCP session ends. A tool
call that finds the session ended rebuilds it and retries once. See
``fleet_supervisor.core.gateway_tools``. The agents are built per request.
See ``fleet_supervisor.core.agents`` for why. Each request also gets its own
memory session manager on the supervisor, closed when the request ends. See
``fleet_supervisor.core.memory``.

Local testing:
    uv run fleet-supervisor-server
    uv run fleet-supervisor-cli "What are the most common maintenance faults?"

Cloud deployment:
    ./agent.sh deploy
    ./agent.sh invoke-cloud "What are the most common maintenance faults?"
"""

import asyncio
import contextlib
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Local runs read the shared aircraft-fleet .env next to supervisor-agent/,
# three levels above this file. The path comes from this file, so the working
# directory does not matter. FLEET_ENV_FILE overrides it; the tests point it
# at an empty file. Existing env vars win, so Runtime env vars are untouched.
# This runs before the package imports because ``core.config`` reads the
# environment at import time.
ENV_FILE = Path(os.environ.get("FLEET_ENV_FILE") or Path(__file__).resolve().parents[2] / ".env")
load_dotenv(ENV_FILE)

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402
from neo4j_agent_memory.integrations.strands import Neo4jSessionManager  # noqa: E402
from strands import Agent  # noqa: E402
from strands.models import BedrockModel  # noqa: E402

from fleet_supervisor.core.agents import build_supervisor  # noqa: E402
from fleet_supervisor.core.config import LOCAL_PORT, MODEL_ID  # noqa: E402
from fleet_supervisor.core.credentials import load_credentials  # noqa: E402
from fleet_supervisor.core.events import EventMapper  # noqa: E402
from fleet_supervisor.core.gateway_tools import (  # noqa: E402
    REQUEST_SESSION_ID,
    GatewayConnection,
    GatewayTool,
    stop_quietly,
)
from fleet_supervisor.core.mcp import (  # noqa: E402
    GatewayAuth,
    build_gateway_auth,
    build_mcp_client,
)
from fleet_supervisor.core.memory import build_session_manager, memory_settings  # noqa: E402
from fleet_supervisor.core.model import build_model  # noqa: E402

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
# Counts finished build and rebuild attempts, and records whether the last
# one failed. Both change only under _runtime_lock, when an attempt ends. A
# caller that waited for the lock while another caller's attempt failed
# skips its own attempt, so a Gateway outage costs one connect attempt, not
# one per waiting caller. That includes a caller that arrived while the
# attempt was running, because the count changes only when it ends.
_attempts = 0
_last_attempt_failed = False


class RecentRebuildFailedError(RuntimeError):
    """Another caller's build or rebuild failed while this one waited."""


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


def _start_runtime(
    stale: GatewayConnection | None = None, seen_attempts: int | None = None
) -> Runtime:
    """Return a runtime with a live MCP session, building or rebuilding it.

    ``stale`` is a connection a caller saw fail. It is rebuilt only if it is
    still the current one, so callers that arrive after a rebuild reuse the
    new connection instead of rebuilding again. ``seen_attempts`` is the
    attempt count the caller read before waiting for the lock. If an attempt
    since then failed, the caller fails fast instead of trying again. None
    means the caller did not wait, so it always tries.
    """
    global _runtime, _attempts, _last_attempt_failed
    with _runtime_lock:
        runtime = _runtime
        if _is_usable(runtime, stale):
            return runtime
        if seen_attempts is not None and _attempts != seen_attempts and _last_attempt_failed:
            raise RecentRebuildFailedError(
                "Another request's Gateway connect attempt just failed; not retrying yet"
            )
        failed = True
        try:
            runtime = _build_or_rebuild(runtime)
            failed = False
            return runtime
        finally:
            _attempts += 1
            _last_attempt_failed = failed


def _build_or_rebuild(runtime: Runtime | None) -> Runtime:
    """Build the runtime, or rebuild its connection. Hold ``_runtime_lock``."""
    global _runtime
    if runtime is None:
        # Build the model before the client, so a model error leaves
        # no client thread running.
        model = build_model()
        connection = _connect_mcp()
        tools = [
            GatewayTool(tool, current_connection, reconnect) for tool in connection.tools.values()
        ]
        _runtime = Runtime(model=model, tools=tools, connection=connection)
        return _runtime

    old = runtime.connection
    runtime.connection = None
    if old is not None:
        logger.warning("Rebuilding the Gateway MCP client (session=%s)", REQUEST_SESSION_ID.get())
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
    return await asyncio.to_thread(_start_runtime, stale, _attempts)


def extract_prompt(payload: Any) -> str | None:
    """Read the question from the payload keys clients commonly send."""
    if not isinstance(payload, dict):
        return None
    for key in ("prompt", "message", "query", "inputText", "input"):
        if isinstance(value := payload.get(key), str) and value.strip():
            return value
    return None


# Cleanup tasks that outlive a cancelled request. The event loop keeps only
# weak references to tasks, so this set keeps each one alive until it ends.
_cleanups: set[asyncio.Task[None]] = set()


def _close_logged(manager: Neo4jSessionManager) -> None:
    """Close a memory session manager, logging a failure. Blocks on Neo4j."""
    try:
        manager.close()
    except Exception:
        logger.exception("Error while closing the memory session manager")


def _build_agent(
    runtime: Runtime, session_id: str, user_id: str
) -> tuple[Agent, Neo4jSessionManager | None]:
    """Build the memory session manager and the supervisor. Blocks on Neo4j.

    The supervisor's constructor connects the manager and restores the
    session history. If it fails, this closes the manager before raising,
    so the caller only closes a manager it gets back.
    """
    manager = build_session_manager(session_id, user_id)
    try:
        supervisor = build_supervisor(runtime.model, runtime.tools, manager)
    except BaseException:
        if manager is not None:
            _close_logged(manager)
        raise
    return supervisor, manager


async def _close_after_build(build: asyncio.Task[tuple[Agent, Neo4jSessionManager | None]]) -> None:
    """Wait for the build to finish, then close the manager it returned."""
    try:
        _, manager = await build
    except BaseException:
        # _build_agent closed the manager and the request logged the error.
        return
    if manager is not None:
        await asyncio.to_thread(_close_logged, manager)


async def _release(build: asyncio.Task[tuple[Agent, Neo4jSessionManager | None]]) -> None:
    """Close the request's manager once its build ends, even if cancelled.

    A client disconnect cancels the request through an anyio cancel scope,
    which cancels every await in this finally block again. So the wait for
    the build and the close run as one task under one shield. If the request
    is cancelled, that task finishes on its own. Closing before the build
    ends would race the constructor, which connects the manager after the
    close and leaves the connection open.
    """
    cleanup = asyncio.create_task(_close_after_build(build))
    _cleanups.add(cleanup)
    cleanup.add_done_callback(_cleanups.discard)
    await asyncio.shield(cleanup)


@app.entrypoint
async def invoke(payload: Any, context):
    """Stream the supervisor's answer as SSE events."""
    build: asyncio.Task[tuple[Agent, Neo4jSessionManager | None]] | None = None
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
        # The shield keeps a cancel from abandoning the build, so the finally
        # block can wait for it before closing the manager.
        build = asyncio.create_task(asyncio.to_thread(_build_agent, runtime, session_id, user_id))
        supervisor, _ = await asyncio.shield(build)
        mapper = EventMapper()
        # Strands flushes memory through a hook in the stream's finally. On a
        # disconnect, aclosing runs that finally here, before the manager
        # closes. A dropped stream would be closed later by the event loop.
        async with contextlib.aclosing(supervisor.stream_async(prompt)) as stream:
            async for event in stream:
                for client_event in mapper.map(event):
                    yield client_event
        logger.info("Session %s handled by %s", session_id, mapper.specialists or "supervisor only")
        yield {"type": "complete"}
    except Exception:
        # Log the details here; the client gets a generic message only.
        logger.exception("Request failed")
        yield {"type": "error", "error": GENERIC_ERROR}
    finally:
        if build is not None:
            await _release(build)


def main(default_port: int = LOCAL_PORT) -> None:
    """Start the server in the foreground. Stop it with Ctrl+C.

    ``uv run fleet-supervisor-server`` calls this with the local port, 7071,
    so the supervisor can run beside graphrag-agent on 7070. The root
    ``main.py`` calls it with 8080, the port AgentCore Runtime expects.
    ``AGENT_PORT`` overrides both.
    """
    port = int(os.environ.get("AGENT_PORT", str(default_port)))
    # Build the memory settings and read the password before serving, so a
    # missing setting, a bad secret ARN, or a missing IAM grant stops startup.
    memory_settings()
    logger.info("Starting Aircraft Fleet Supervisor Agent (model %s) on port %s", MODEL_ID, port)
    app.run(port=port)
