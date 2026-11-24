"""Aircraft Fleet Supervisor Agent on AgentCore Runtime.

A Strands supervisor delegates each question to one of two specialist
agents, each wrapped as a tool:

- Maintenance Agent: reliability, faults, components, sensors
- Operations Agent: flights, delays, routes, airports

The specialists query Neo4j directly through the graph tools in
``fleet_supervisor.core.graph``. The model is created once, on the first
request. Each request reads the graph schema, which the graph package caches,
and formats it into the specialist prompts. The agents are built per request.
See ``fleet_supervisor.core.agents`` for why. Each request also gets its own
memory session manager on the supervisor, closed when the request ends. The
managers share one memory client, opened on the first request and closed at
shutdown. Entity extraction runs after the reply, and the health check reports
busy until it ends. See ``fleet_supervisor.core.memory``.

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
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import cache, partial
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
from neo4j_agent_memory import MemorySettings  # noqa: E402
from strands import Agent  # noqa: E402
from strands.models import BedrockModel  # noqa: E402
from strands.types.exceptions import SessionException  # noqa: E402

from fleet_supervisor.core.agents import build_supervisor  # noqa: E402
from fleet_supervisor.core.config import LOCAL_PORT, MODEL_ID  # noqa: E402
from fleet_supervisor.core.events import EventMapper  # noqa: E402
from fleet_supervisor.core.graph import close, get_graph_schema  # noqa: E402
from fleet_supervisor.core.memory import (  # noqa: E402
    MemoryClientError,
    MemorySession,
    MemorySessionError,
    build_session_manager,
    close_shared_memory,
    forget_memory_settings,
    memory_settings,
    password_rejected,
    reload_memory_login,
)
from fleet_supervisor.core.model import build_model  # noqa: E402
from fleet_supervisor.core.secrets import neo4j_login  # noqa: E402

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


@asynccontextmanager
async def _lifespan(app: BedrockAgentCoreApp) -> AsyncIterator[None]:
    """Close the shared memory client and the graph driver when the server stops.

    The memory close waits up to 30 seconds for open memory sessions. A
    request cancelled at shutdown still writes its memory only if its session
    closes in that time. Then the close waits for background extraction.
    Closing the memory clients takes at most about 100 seconds. An extraction
    still running at that deadline is lost. The graph driver closes after
    that, even if the memory close fails.
    """
    yield
    try:
        await asyncio.to_thread(close_shared_memory)
    finally:
        await asyncio.to_thread(close)


app = BedrockAgentCoreApp(lifespan=_lifespan)


def track_background_task(name: str) -> Callable[[], None]:
    """Mark the server busy while background memory work runs.

    The memory client calls this when a task such as entity extraction
    starts, and calls the returned function once when it ends. While any
    task runs, the health check reports busy, so AgentCore Runtime does not
    stop the session in the middle of it.
    """
    return partial(app.complete_async_task, app.add_async_task(name))


@cache
def get_model() -> BedrockModel:
    """Return the process-wide model, built on the first request.

    A failure is not cached, so the next request tries again.
    """
    return build_model()


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


def _close_logged(session: MemorySession) -> None:
    """Close a memory session, logging a failure. Blocks on Neo4j."""
    try:
        session.close()
    except Exception:
        logger.exception("Error while closing the memory session manager")


def _build_agent(
    model: BedrockModel, schema: str, session_id: str, user_id: str
) -> tuple[Agent, MemorySession | None]:
    """Build the memory session and the supervisor. Blocks on Neo4j.

    The first request opens the shared memory client. The supervisor's
    constructor restores the session history on the client's event loop. If
    Neo4j rejects the password, the cached one may predate a secret
    rotation. So this drops it and retires the client that opened with it,
    unless another request already did, and builds once more with the
    current settings. The rejected password is the one the shared client
    used, which may be another request's.
    """
    settings = memory_settings()
    try:
        return _build_agent_once(model, schema, settings, session_id, user_id)
    except Exception as error:
        if not password_rejected(error):
            raise
        if isinstance(error, MemoryClientError):
            settings = error.settings
    # Outside the except block, so a second failure does not chain the first.
    logger.warning("Neo4j rejected the memory password; reading it again")
    forget_memory_settings(settings)
    return _build_agent_once(model, schema, memory_settings(), session_id, user_id)


def _build_agent_once(
    model: BedrockModel,
    schema: str,
    settings: MemorySettings,
    session_id: str,
    user_id: str,
) -> tuple[Agent, MemorySession | None]:
    """Build the memory session and the supervisor once.

    If the build fails, this closes the session before raising, so the
    caller only closes a session it gets back. Neo4j can reject the
    password while the supervisor restores the session. That raises a
    MemorySessionError with the settings the session's client used.
    """
    session = build_session_manager(session_id, user_id, settings, track_background_task)
    try:
        supervisor = build_supervisor(
            model, schema, session.manager if session is not None else None
        )
    except BaseException as error:
        if session is not None:
            _close_logged(session)
            if isinstance(error, Exception) and password_rejected(error):
                raise MemorySessionError(session.settings) from error
        raise
    return supervisor, session


async def _late_write_rejected(error: BaseException, session: MemorySession | None) -> bool:
    """Handle a memory write Neo4j rejected after the agent was built.

    Strands flushes memory at the end of the turn, after the answer has
    streamed. If Neo4j rejects the memory login there, the password may have
    rotated since the client opened. This reads the memory secret again into
    the client's auth manager and logs a warning. The message stays queued,
    and the session's close writes it again under the same message id with
    the new login. Returns False, and does nothing, for any other error.
    """
    if session is None or not isinstance(error, SessionException) or not password_rejected(error):
        return False
    rotated = await asyncio.to_thread(reload_memory_login, session.settings)
    logger.warning(
        "Neo4j rejected the memory login on a late write; %s. "
        "The session's close writes the message again.",
        "read the rotated password" if rotated else "the password has not changed",
    )
    return True


async def _close_after_build(build: asyncio.Task[tuple[Agent, MemorySession | None]]) -> None:
    """Wait for the build to finish, then close the memory session it returned."""
    try:
        _, session = await build
    except BaseException:
        # _build_agent closed the session and the request logged the error.
        return
    if session is not None:
        await asyncio.to_thread(_close_logged, session)


async def _release(build: asyncio.Task[tuple[Agent, MemorySession | None]]) -> None:
    """Close the request's memory session once its build ends, even if cancelled.

    A client disconnect cancels the request. The AgentCore SDK calls
    ``task.cancel()`` once, which interrupts whichever await in this finally
    block is running. Under an anyio cancel scope, every later await is
    cancelled too. So the wait for the build and the close run as one task
    under one shield, and that task finishes on its own if the request is
    cancelled. Closing before the build ends would race the constructor,
    which restores history on the shared client's event loop after the close.
    """
    cleanup = asyncio.create_task(_close_after_build(build))
    _cleanups.add(cleanup)
    cleanup.add_done_callback(_cleanups.discard)
    await asyncio.shield(cleanup)


@app.entrypoint
async def invoke(payload: Any, context):
    """Stream the supervisor's answer as SSE events."""
    build: asyncio.Task[tuple[Agent, MemorySession | None]] | None = None
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
        # The prompt is user text, so only its length goes to INFO.
        logger.info("Request session=%s user=%s prompt_chars=%d", session_id, user_id, len(prompt))
        logger.debug("Request session=%s prompt=%s", session_id, prompt)

        model = await asyncio.to_thread(get_model)
        # The graph package caches the schema, so this queries Neo4j only
        # when the cached copy has expired.
        schema = await asyncio.to_thread(get_graph_schema)
        # The shield keeps a cancel from abandoning the build, so the finally
        # block can wait for it before closing the manager.
        build = asyncio.create_task(
            asyncio.to_thread(_build_agent, model, schema, session_id, user_id)
        )
        supervisor, session = await asyncio.shield(build)
        mapper = EventMapper(trace=payload.get("trace") is True)
        # Strands flushes memory through a hook in the stream's finally. The
        # stream is closed here, so that flush ends before the manager
        # closes. A dropped stream would be closed later by the event loop.
        # A finished turn raises a failed flush from the loop below, and a
        # disconnect raises it from the close.
        stream = mapper.stream(supervisor, prompt)
        try:
            async for event in stream:
                for client_event in mapper.map(event):
                    yield client_event
        except GeneratorExit:
            # The client disconnected. A flush error must not replace
            # GeneratorExit, or the handler below would yield while this
            # generator closes. So log it here and close without yielding.
            try:
                await stream.aclose()
            except Exception as error:
                if not await _late_write_rejected(error, session):
                    logger.exception("The agent stream failed while closing")
            raise
        except SessionException as error:
            # The answer has streamed. A rejected memory login is retried
            # when the session closes, so the request still completes.
            if not await _late_write_rejected(error, session):
                raise
        finally:
            await stream.aclose()
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

    ``uv run fleet-supervisor-server`` calls this with the local port, 7071.
    The root ``main.py`` calls it with 8080, the port AgentCore Runtime
    expects.
    ``AGENT_PORT`` overrides both.
    """
    port = int(os.environ.get("AGENT_PORT", str(default_port)))
    # Read the graph login, build the memory settings, and read the memory
    # password before serving. A missing setting, a bad secret ARN, or a
    # missing IAM grant then stops startup.
    neo4j_login()
    memory_settings()
    logger.info("Starting Aircraft Fleet Supervisor Agent (model %s) on port %s", MODEL_ID, port)
    app.run(port=port)
