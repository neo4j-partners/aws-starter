"""Conversation memory in its own Neo4j instance, through Neo4j Agent Memory.

The agent keeps short-term history and long-term entities and preferences in
a memory instance that is separate from the fleet graph. Memory labels never
reach the fleet schema that Text2Cypher reads.

:func:`memory_settings` builds the settings once per process from the
``MEM_NEO4J_*`` variables. :func:`session_manager` builds one
``Neo4jSessionManager`` per request. neo4j-agent-memory 0.8.0 cannot share a
client across managers: each manager runs its own event-loop thread, and the
async driver is bound to that loop. The caller must ``close()`` the manager
when the request ends.
"""

from __future__ import annotations

import os
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
)
from neo4j_agent_memory.llm.adapters.bedrock import (
    BedrockEmbeddingProvider,
    BedrockProvider,
)
from pydantic import SecretStr

from fleet_graphrag.agent.config import ConfigError, settings
from fleet_graphrag.agent.secrets import memory_password

# Sonnet 5.5 rejects the forced toolChoice and the temperature that the
# extractor sends, so extraction stays on Sonnet 4.6.
EXTRACTOR_MODEL_ID = "bedrock/global.anthropic.claude-sonnet-4-6"
EMBED_MODEL_ID = "bedrock/amazon.titan-embed-text-v2:0"
EMBED_DIMENSIONS = 1024

# A vector-index score. 0.75 equals cosine similarity 0.5.
MIN_SCORE = 0.75


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
        llm=BedrockProvider(EXTRACTOR_MODEL_ID, aws_region=region),
        extraction=ExtractionConfig(extractor_type=ExtractorType.LLM),
    )


def session_manager(session_id: str, user_id: str) -> Neo4jSessionManager:
    """Build the memory session manager for one request.

    It connects when the agent that owns it is constructed. The caller must
    call ``close()`` when the request ends, on every path.
    """
    return Neo4jSessionManager(
        session_id,
        settings=memory_settings(),
        user_id=user_id,
        retrieval_config=Neo4jRetrievalConfig(min_score=MIN_SCORE),
        extract_entities=True,
        record_tool_calls=False,
    )
