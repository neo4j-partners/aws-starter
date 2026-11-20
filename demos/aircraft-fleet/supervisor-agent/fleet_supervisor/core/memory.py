"""Supervisor memory in Neo4j, through neo4j-agent-memory.

Memory is optional. It is on when ``MEM_NEO4J_URI`` is set:

- ``MEM_NEO4J_URI``, ``MEM_NEO4J_USERNAME``, and ``MEM_NEO4J_DATABASE`` name
  the memory database. It is a separate database from the fleet graph.
- ``MEM_NEO4J_PASSWORD_SECRET_ARN`` names a Secrets Manager secret in the
  cloud. ``MEM_NEO4J_PASSWORD`` holds the password itself for a local run.

The settings are built once per process. Each request gets its own
:class:`Neo4jSessionManager`, and the caller must close it when the request
ends. Each manager runs its own event-loop thread, and its Neo4j driver is
bound to that loop, so managers cannot share one client.
"""

from __future__ import annotations

import os
from functools import cache

from neo4j_agent_memory import MemorySettings
from neo4j_agent_memory.config.settings import ExtractionConfig, ExtractorType, Neo4jConfig
from neo4j_agent_memory.integrations.strands import Neo4jRetrievalConfig, Neo4jSessionManager
from pydantic import SecretStr

from fleet_supervisor.core.secrets import password_from

MEM_NEO4J_URI = "MEM_NEO4J_URI"

# Titan v2 returns 1024-dimension vectors.
EMBEDDING_MODEL = "bedrock/amazon.titan-embed-text-v2:0"
# The model that extracts entities from stored messages.
EXTRACTION_MODEL = "bedrock/global.anthropic.claude-sonnet-4-6"
# Only memories at least this similar to the question are added to it.
RETRIEVAL_MIN_SCORE = 0.75


def memory_password() -> str:
    """Return the memory database password."""
    return password_from("MEM_NEO4J_PASSWORD_SECRET_ARN", "MEM_NEO4J_PASSWORD")


@cache
def memory_settings() -> MemorySettings | None:
    """Return the memory settings, or None when ``MEM_NEO4J_URI`` is unset.

    Built once per process. A failure is not cached. Raises
    :class:`~fleet_supervisor.core.config.ConfigError` when the URI is set
    but no password resolves.
    """
    uri = os.environ.get(MEM_NEO4J_URI, "").strip()
    if not uri:
        return None
    return MemorySettings(
        # Every value comes from here, never from a .env file.
        _env_file=None,
        backend="bolt",
        neo4j=Neo4jConfig(
            uri=uri,
            username=os.environ.get("MEM_NEO4J_USERNAME", "neo4j"),
            password=SecretStr(memory_password()),
            database=os.environ.get("MEM_NEO4J_DATABASE", "neo4j"),
        ),
        embedding=EMBEDDING_MODEL,
        llm=EXTRACTION_MODEL,
        # The default pipeline needs spaCy and GLiNER, which are not installed.
        extraction=ExtractionConfig(extractor_type=ExtractorType.LLM),
    )


def build_session_manager(session_id: str, user_id: str | None) -> Neo4jSessionManager | None:
    """Return a session manager for one request, or None when memory is off.

    The manager opens its connection when the agent uses it. The caller must
    call ``close()`` when the request ends, on every path.
    """
    settings = memory_settings()
    if settings is None:
        return None
    return Neo4jSessionManager(
        session_id,
        settings=settings,
        user_id=user_id,
        retrieval_config=Neo4jRetrievalConfig(min_score=RETRIEVAL_MIN_SCORE),
    )
