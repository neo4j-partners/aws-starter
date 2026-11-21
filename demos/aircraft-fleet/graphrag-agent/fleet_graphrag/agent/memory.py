"""Conversation memory in its own Neo4j instance, through Neo4j Agent Memory.

The agent keeps short-term history and long-term entities and preferences in
a memory instance that is separate from the fleet graph. Memory labels never
reach the fleet schema that Text2Cypher reads.

:func:`memory_settings` builds the settings once per process from the
``MEM_NEO4J_*`` variables. :func:`shared_memory` opens one ``SharedMemory``
per process on the first request that needs it. It holds the memory client
and the event-loop thread that every manager runs on. A failed open is not
kept, so the next request tries again. :func:`close_memory` closes it at
shutdown.

:func:`session_manager` builds one ``Neo4jSessionManager`` per request on the
shared memory. The caller must ``close()`` the manager when the request ends.
The close writes the turn and leaves its entity extraction running in the
background, so the answer does not wait for it.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from functools import cache

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

# The open shared memory, and the open in flight. Both are only read and set
# on the server's event loop, so no lock is needed.
_shared: SharedMemory | None = None
_opening: asyncio.Task[SharedMemory] | None = None


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

    Concurrent first callers wait for the same open. The open runs in its own
    task, so a caller that is cancelled does not stop it, and the next caller
    gets the memory it opened. A failed open raises to every caller waiting
    for it and is not kept.
    """
    global _opening
    if _shared is not None:
        return _shared
    if _opening is None:
        _opening = asyncio.create_task(_open(background_hook))
    return await asyncio.shield(_opening)


async def _open(background_hook: BackgroundHook) -> SharedMemory:
    """Open the shared memory in a worker thread, since the open blocks."""
    global _shared, _opening
    try:
        _shared = await asyncio.to_thread(
            lambda: SharedMemory.open(memory_settings(), background_hook=background_hook)
        )
        return _shared
    finally:
        _opening = None


async def close_memory() -> None:
    """Close the shared memory if it is open. A second call does nothing.

    An open still in flight is waited out first, so the client it opens is
    closed too. Closing waits for the background extractions still running.
    """
    global _shared
    if _opening is not None:
        try:
            await asyncio.shield(_opening)
        except Exception:
            # The failed open has nothing to close. Its error already went to
            # the request that started it.
            return
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
