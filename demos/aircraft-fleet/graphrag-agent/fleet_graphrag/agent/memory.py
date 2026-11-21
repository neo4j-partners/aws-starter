"""Conversation memory in its own Neo4j instance, through Neo4j Agent Memory.

The agent keeps short-term history and long-term entities and preferences in
a memory instance that is separate from the fleet graph. Memory labels never
reach the fleet schema that Text2Cypher reads.

:func:`memory_settings` builds the settings once per process from the
``MEM_NEO4J_*`` variables. :func:`shared_memory` opens one ``SharedMemory``
per process on the first request that needs it. It holds the memory client
and the event-loop thread that every manager runs on. A failed open is not
kept, so the next request tries again. :func:`close_memory` closes it at
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
import os
import threading
from collections.abc import Callable
from functools import cache

import neo4j
from neo4j_agent_memory import (
    ExtractionConfig,
    ExtractorType,
    MemorySettings,
    Neo4jConfig,
)
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
from fleet_graphrag.agent.secrets import memory_password

# Sonnet 5.5 rejects a temperature and a forced toolChoice, so the extractor
# is built with send_temperature=False and tool_choice="auto".
EXTRACTOR_MODEL_ID = "bedrock/global.anthropic.claude-sonnet-5-5"
EMBED_MODEL_ID = "bedrock/amazon.titan-embed-text-v2:0"
EMBED_DIMENSIONS = 1024

# A vector-index score. 0.75 equals cosine similarity 0.5.
MIN_SCORE = 0.75

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


class MemoryClosedError(neo4j.exceptions.ServiceUnavailable):
    """The shared memory was closed at shutdown.

    It is a ``ServiceUnavailable``, so a request that arrives after shutdown
    gets the same error as a failed open.
    """


@cache
def memory_settings() -> MemorySettings:
    """Build the memory settings once per process.

    Raises :class:`ConfigError` when ``MEM_NEO4J_URI`` or the password is
    missing, or the password secret cannot be read. A failure is not cached.
    """
    uri = os.getenv("MEM_NEO4J_URI", "").strip()
    if not uri:
        raise ConfigError("MEM_NEO4J_URI is not set.")
    region = settings.aws_region
    return MemorySettings(
        # Set explicitly so a MEMORY_API_KEY in the environment cannot switch
        # the backend to the hosted service.
        backend="bolt",
        neo4j=Neo4jConfig(
            uri=uri,
            username=os.getenv("MEM_NEO4J_USERNAME") or "neo4j",
            password=SecretStr(memory_password()),
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
    to every caller waiting for it and is not kept.

    Raises :class:`MemoryClosedError` after :func:`close_memory`.
    """
    global _opening, _open_thread
    with _lock:
        if _closed:
            raise MemoryClosedError("The memory is closed. The server is shutting down.")
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
    global _shared, _opening
    # A running future cannot be cancelled, so no waiter can drop the open.
    opening.set_running_or_notify_cancel()
    try:
        shared = SharedMemory.open(memory_settings(), background_hook=background_hook)
    except Exception as e:
        with _lock:
            _opening = None
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
        # A failed open leaves nothing to close. Its error already went to
        # the request that started it, so it is not raised here.
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
        retrieval_config=Neo4jRetrievalConfig(min_score=MIN_SCORE),
        extract_entities=True,
        record_tool_calls=False,
        defer_extraction=True,
    )
