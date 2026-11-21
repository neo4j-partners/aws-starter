"""Supervisor memory in Neo4j, through neo4j-agent-memory.

Memory is required. These variables configure it:

- ``MEM_NEO4J_URI``, ``MEM_NEO4J_USERNAME``, and ``MEM_NEO4J_DATABASE`` name
  the memory database. It is a separate database from the fleet graph.
- ``MEM_NEO4J_PASSWORD_SECRET_ARN`` names a Secrets Manager secret in the
  cloud. ``MEM_NEO4J_PASSWORD`` holds the password itself for a local run.

The settings are built once per process. If Neo4j rejects the password,
:func:`forget_memory_settings` drops them so the next build reads the
password again. Each request gets its own
:class:`Neo4jSessionManager`, and the caller must close it when the request
ends. Each manager runs its own event-loop thread, and its Neo4j driver is
bound to that loop, so managers cannot share one client.
"""

from __future__ import annotations

import os
from functools import cache

from neo4j.exceptions import AuthError
from neo4j_agent_memory import MemorySettings
from neo4j_agent_memory.config.settings import ExtractionConfig, ExtractorType, Neo4jConfig
from neo4j_agent_memory.integrations.strands import Neo4jRetrievalConfig, Neo4jSessionManager
from neo4j_agent_memory.llm.adapters.bedrock import BedrockEmbeddingProvider, BedrockProvider
from pydantic import SecretStr

from fleet_supervisor.core.config import AWS_REGION, ConfigError
from fleet_supervisor.core.secrets import forget_secrets, password_from

MEM_NEO4J_URI = "MEM_NEO4J_URI"

EMBEDDING_MODEL = "bedrock/amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024
# The model that extracts entities from stored messages. Sonnet 5.5 rejects
# the forced toolChoice and the temperature that the extractor sends, so
# extraction stays on Sonnet 4.6.
EXTRACTION_MODEL = "bedrock/global.anthropic.claude-sonnet-4-6"
# Only memories at least this similar to the question are added to it.
RETRIEVAL_MIN_SCORE = 0.75


def memory_password() -> str:
    """Return the memory database password."""
    return password_from("MEM_NEO4J_PASSWORD_SECRET_ARN", "MEM_NEO4J_PASSWORD")


def forget_memory_settings() -> None:
    """Drop the cached settings and secrets, so the next build reads them again."""
    memory_settings.cache_clear()
    forget_secrets()


def password_rejected(error: BaseException) -> bool:
    """Return True if Neo4j rejected the credentials somewhere in ``error``'s chain.

    neo4j-agent-memory wraps the driver's ``AuthError`` in its own
    ``ConnectionError``, and Strands wraps that in a ``SessionException``.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, AuthError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


@cache
def memory_settings() -> MemorySettings:
    """Build the memory settings once per process.

    Raises :class:`~fleet_supervisor.core.config.ConfigError` when
    ``MEM_NEO4J_URI`` or the password is missing, or the password secret
    cannot be read. A failure is not cached.
    """
    uri = os.environ.get(MEM_NEO4J_URI, "").strip()
    if not uri:
        raise ConfigError(f"{MEM_NEO4J_URI} is not set.")
    return MemorySettings(
        # Every value comes from here, never from a .env file.
        _env_file=None,
        # Set explicitly so a MEMORY_API_KEY in the environment cannot switch
        # the backend to the hosted service.
        backend="bolt",
        neo4j=Neo4jConfig(
            uri=uri,
            username=os.environ.get("MEM_NEO4J_USERNAME") or "neo4j",
            password=SecretStr(memory_password()),
            database=os.environ.get("MEM_NEO4J_DATABASE") or "neo4j",
        ),
        # Provider instances, so the region and dimensions are set here and
        # not left to package defaults.
        embedding=BedrockEmbeddingProvider(
            EMBEDDING_MODEL, aws_region=AWS_REGION, dimensions=EMBEDDING_DIMENSIONS
        ),
        llm=BedrockProvider(EXTRACTION_MODEL, aws_region=AWS_REGION),
        # The default pipeline needs spaCy and GLiNER, which are not installed.
        extraction=ExtractionConfig(extractor_type=ExtractorType.LLM),
    )


def build_session_manager(session_id: str, user_id: str) -> Neo4jSessionManager:
    """Return the memory session manager for one request.

    It connects when the agent that owns it is built. The caller must call
    ``close()`` when the request ends, on every path.
    """
    return Neo4jSessionManager(
        session_id,
        settings=memory_settings(),
        user_id=user_id,
        retrieval_config=Neo4jRetrievalConfig(min_score=RETRIEVAL_MIN_SCORE),
        # Set explicitly, because defaults can change between releases.
        extract_entities=True,
        record_tool_calls=False,
    )
