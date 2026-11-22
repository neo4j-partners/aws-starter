"""Conversation memory in its own Neo4j instance, through Neo4j Agent Memory.

The agent keeps short-term history and long-term entities and preferences in
a memory instance that is separate from the fleet graph. Memory labels never
reach the fleet schema that Text2Cypher reads.

:func:`memory_settings` builds the settings once per process from the
``MEM_NEO4J_*`` variables. :func:`shared_memory` opens one ``SharedMemory``
per process on the first request that needs it. It holds the memory client
and the event-loop thread that every manager runs on. A failed open is not
kept, so the next request tries again. A rejected password is kept until the
process restarts. The settings are read once, so a retry would send the same
password. :func:`close_memory` closes it at
shutdown, and no request opens it after that.

AgentCore runs requests on its own worker event loop and the server lifespan
on the main loop. So the open runs on its own thread, and any loop can wait
for it.

:func:`session_manager` builds one ``Neo4jSessionManager`` per request on the
shared memory. The caller must ``close()`` the manager when the request ends.
The close writes the turn and leaves its entity extraction running in the
background, so the answer does not wait for it.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import threading
from collections.abc import Callable
from functools import cache
from urllib.parse import urlsplit

import neo4j
from neo4j_agent_memory import (
    ExtractionConfig,
    ExtractorType,
    MemorySettings,
    Neo4jConfig,
)
from neo4j_agent_memory.core.exceptions import ConnectionError as MemoryConnectionError
from neo4j_agent_memory.integrations.strands import (
    Neo4jRetrievalConfig,
    Neo4jSessionManager,
    SharedMemory,
)
from neo4j_agent_memory.llm.adapters.bedrock import (
    BedrockEmbeddingProvider,
    BedrockProvider,
)
from pydantic import SecretStr

from fleet_graphrag.agent.config import ConfigError, settings
from fleet_graphrag.agent.neo4j_errors import UNREACHABLE, auth_error
from fleet_graphrag.agent.secrets import memory_login

logger = logging.getLogger(__name__)

# Sonnet 5.5 rejects a temperature and a forced toolChoice, so the extractor
# is built with send_temperature=False and tool_choice="auto".
EXTRACTOR_MODEL_ID = "bedrock/global.anthropic.claude-sonnet-5-5"
EMBED_MODEL_ID = "bedrock/amazon.titan-embed-text-v2:0"
EMBED_DIMENSIONS = 1024

# Memory hits that score below this are not added to the question. The
# score is Neo4j's cosine vector score, (1 + cosine) / 2, so 0.675 is cosine
# 0.35. Measured on 2026-11-21 with Titan v2 entity embeddings from real
# Sonnet 5.5 extraction: 10 of 15 relevant hits and 3 of 417 unrelated pairs
# scored 0.675 or higher. The old 0.75 kept only 6 of the 15 relevant hits.
# An entity embeds only its name, so short names such as airport codes score
# low against a full question.
RETRIEVAL_MIN_SCORE = 0.675

# Takes a background task's name and returns the callback for when it ends.
BackgroundHook = Callable[[str], Callable[[], None]]

# The state below is read and set from the request loop and the lifespan
# loop, which run on different threads, so the lock guards all of it.
_lock = threading.Lock()
# The open shared memory.
_shared: SharedMemory | None = None
# The open in flight, and the thread that runs it.
_opening: concurrent.futures.Future[SharedMemory] | None = None
_open_thread: threading.Thread | None = None
# Set by close_memory. No open starts after it.
_closed = False
# The message of a rejected login. Every later call raises a fresh
# MemoryAuthError with it, with no new open.
_auth_failure: str | None = None

# Open failures that are about reaching the database. They are logged
# without a traceback. Any other failure is logged with one.
_CONNECTION_ERRORS = (MemoryConnectionError, TimeoutError, *UNREACHABLE)


class MemoryClosedError(neo4j.exceptions.ServiceUnavailable):
    """The shared memory was closed at shutdown.

    It is a ``ServiceUnavailable``, so it is handled like a failed open,
    and the server reports it as a shutdown.
    """


class MemoryAuthError(neo4j.exceptions.AuthError):
    """The memory database rejected its password earlier in this process.

    It is an ``AuthError``, so it is handled like the first rejection.
    """


@cache
def memory_settings() -> MemorySettings:
    """Build the memory settings once per process.

    Raises :class:`ConfigError` when ``MEM_NEO4J_URI`` or the password is
    missing, ``MEM_NEO4J_URI`` holds a login, or the password secret cannot
    be read. A failure is not cached.
    """
    uri = os.getenv("MEM_NEO4J_URI", "").strip()
    if not uri:
        raise ConfigError("MEM_NEO4J_URI is not set.")
    if "@" in urlsplit(uri).netloc:
        # The driver echoes the URI in its errors, so a password in it would
        # reach the logs. The message does not echo it either.
        raise ConfigError(
            "MEM_NEO4J_URI must not hold a user name or password. Set "
            "MEM_NEO4J_USERNAME and MEM_NEO4J_PASSWORD instead."
        )
    region = settings.aws_region
    login = memory_login()
    return MemorySettings(
        # Set explicitly so a MEMORY_API_KEY in the environment cannot switch
        # the backend to the hosted service.
        backend="bolt",
        neo4j=Neo4jConfig(
            uri=uri,
            username=login.username,
            password=SecretStr(login.password),
            database=os.getenv("MEM_NEO4J_DATABASE") or "neo4j",
        ),
        # Provider instances, because the nested NAM_EMBEDDING__* variables
        # are silently ignored.
        embedding=BedrockEmbeddingProvider(
            EMBED_MODEL_ID, aws_region=region, dimensions=EMBED_DIMENSIONS
        ),
        llm=BedrockProvider(
            EXTRACTOR_MODEL_ID,
            aws_region=region,
            send_temperature=False,
            tool_choice="auto",
        ),
        extraction=ExtractionConfig(extractor_type=ExtractorType.LLM),
    )


async def shared_memory(background_hook: BackgroundHook) -> SharedMemory:
    """Return the process's shared memory, opening it on the first call.

    Concurrent first callers, on any event loop, wait for the same open. The
    open runs on its own thread, so a caller that is cancelled does not stop
    it, and the next caller gets the memory it opened. A failed open raises
    to every caller waiting for it and is not kept, except a rejected
    password, which every later call raises until the process restarts.

    Raises :class:`MemoryClosedError` after :func:`close_memory`.
    """
    global _opening, _open_thread
    with _lock:
        if _closed:
            raise MemoryClosedError("The memory is closed. The server is shutting down.")
        if _auth_failure is not None:
            # A fresh error each time, so no raise carries another's
            # traceback or context.
            raise MemoryAuthError(
                f"The memory database rejected its password: {_auth_failure}"
            ) from None
        if _shared is not None:
            return _shared
        if _opening is None:
            _opening = concurrent.futures.Future()
            _open_thread = threading.Thread(
                target=_open,
                args=(_opening, background_hook),
                name="memory-open",
                daemon=True,
            )
            _open_thread.start()
        opening = _opening
    return await asyncio.shield(asyncio.wrap_future(opening))


def _open(
    opening: concurrent.futures.Future[SharedMemory], background_hook: BackgroundHook
) -> None:
    """Open the shared memory and settle ``opening``. Runs on its own thread."""
    global _shared, _opening, _auth_failure
    # A running future cannot be cancelled, so no waiter can drop the open.
    # It returns False only when the future was cancelled before this.
    if not opening.set_running_or_notify_cancel():
        with _lock:
            _opening = None
        return
    try:
        shared = SharedMemory.open(memory_settings(), background_hook=background_hook)
    except BaseException as e:
        # Every failure settles the future, or close_memory would wait for
        # it forever. Logged here, since every caller waiting for it may be
        # gone. The error goes to the callers that are left.
        traceback = None if isinstance(e, _CONNECTION_ERRORS) else e
        logger.warning("Memory open failed: %s", e, exc_info=traceback)
        rejected = auth_error(e)
        with _lock:
            _opening = None
            if rejected is not None:
                # Retrying sends the same password. It cannot succeed and
                # counts toward the server's failed-login lockout. Only the
                # message is kept, so no traceback or context is shared.
                _auth_failure = str(rejected)
        opening.set_exception(e)
        return
    with _lock:
        _shared = shared
        _opening = None
    opening.set_result(shared)


async def close_memory() -> None:
    """Close the shared memory if it is open. A second call does nothing.

    No open starts after this. An open still in flight is waited out first,
    so the client it opens is closed too. Closing waits for the background
    extractions still running. It works from any event loop.
    """
    global _shared, _closed
    with _lock:
        _closed = True
        opening, thread = _opening, _open_thread
    if opening is not None:
        # A failed open leaves nothing to close. The open thread logged its
        # error, so it is not raised here.
        await asyncio.wait({asyncio.wrap_future(opening)})
    if thread is not None:
        await asyncio.to_thread(thread.join)
    with _lock:
        shared, _shared = _shared, None
    if shared is not None:
        await shared.aclose()


def session_manager(shared: SharedMemory, session_id: str, user_id: str) -> Neo4jSessionManager:
    """Build the memory session manager for one request on the shared memory.

    It restores the session when the agent that owns it is constructed. The
    caller must call ``close()`` when the request ends, on every path.
    """
    return shared.session_manager(
        session_id,
        user_id=user_id,
        retrieval_config=Neo4jRetrievalConfig(min_score=RETRIEVAL_MIN_SCORE),
        extract_entities=True,
        record_tool_calls=False,
        defer_extraction=True,
    )
