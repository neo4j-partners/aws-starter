"""Static configuration shared by the agent entrypoints."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast, get_args

Effort = Literal["low", "medium", "high", "xhigh", "max"]

DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-5-5"
DEFAULT_MAX_TOKENS = 64_000
DEFAULT_EFFORT: Effort = "medium"


class ConfigError(RuntimeError):
    """Required configuration is missing or unusable.

    The message names the setting, so it belongs in the server log. Clients
    get a generic message instead.
    """


def _env_int(name: str, default: int) -> int:
    """Read an int env var. An unset or empty value gives ``default``."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None


def _env_float(name: str, default: float) -> float:
    """Read a float env var. An unset or empty value gives ``default``."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None


def _env_effort(name: str, default: Effort) -> Effort:
    """Read the effort level. An unset or empty value gives ``default``."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    allowed = get_args(Effort)
    if raw not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)}, got {raw!r}")
    return cast(Effort, raw)


@dataclass(frozen=True, slots=True)
class Settings:
    """Env-derived runtime configuration, resolved once via :meth:`from_env`.

    The vector index + embedder MUST match what ``aircraft-fleet-pipeline``
    used to populate the graph, or vector search returns noise. They default
    to Amazon Bedrock Titan v2 (1024 dims) on the ``maintenanceChunkEmbeddings``
    index over :Chunk(text). Hybrid search also uses the ``maintenanceChunkText``
    fulltext index. Every field is env-overridable.
    """

    model_id: str = DEFAULT_MODEL_ID
    max_tokens: int = DEFAULT_MAX_TOKENS
    effort: Effort = DEFAULT_EFFORT
    aws_region: str = "us-east-1"
    vector_index_name: str = "maintenanceChunkEmbeddings"
    fulltext_index_name: str = "maintenanceChunkText"
    schema_ttl_s: int = 600
    text2cypher_timeout_s: float = 30.0
    text2cypher_max_rows: int = 200
    # Output cap for the Cypher-writing call. A query needs far less than the
    # agent's MAX_TOKENS, and the cap stops a runaway generation early.
    text2cypher_max_tokens: int = 2048
    embed_model_id: str = "amazon.titan-embed-text-v2:0"
    embed_dimensions: int = 1024

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from the environment, falling back to the defaults."""
        defaults = cls()
        return cls(
            model_id=os.getenv("MODEL_ID", defaults.model_id),
            max_tokens=_env_int("MAX_TOKENS", defaults.max_tokens),
            effort=_env_effort("MODEL_EFFORT", defaults.effort),
            aws_region=os.getenv("AWS_REGION", defaults.aws_region),
            vector_index_name=os.getenv(
                "VECTOR_INDEX_NAME", defaults.vector_index_name
            ),
            fulltext_index_name=os.getenv(
                "FULLTEXT_INDEX_NAME", defaults.fulltext_index_name
            ),
            schema_ttl_s=_env_int("SCHEMA_TTL_S", defaults.schema_ttl_s),
            text2cypher_timeout_s=_env_float(
                "TEXT2CYPHER_TIMEOUT_S", defaults.text2cypher_timeout_s
            ),
            text2cypher_max_rows=_env_int(
                "TEXT2CYPHER_MAX_ROWS", defaults.text2cypher_max_rows
            ),
            text2cypher_max_tokens=_env_int(
                "TEXT2CYPHER_MAX_TOKENS", defaults.text2cypher_max_tokens
            ),
            embed_model_id=os.getenv(
                "EMBED_MODEL_ID", defaults.embed_model_id
            ),
            embed_dimensions=int(
                os.getenv("EMBED_DIMENSIONS", str(defaults.embed_dimensions))
            ),
        )


# Resolved once at import. Entry points load the local .env before they
# import this package, so local-run vars are already in os.environ here.
settings = Settings.from_env()

SYSTEM_PROMPT_TEMPLATE = """You are a helpful aircraft fleet assistant with direct access to a Neo4j graph database. You answer questions using two tools. There is no Cypher console, so use the tools.

## Database Schema (Pre-loaded)

The live schema is already known. Do NOT ask for it. Use this:

{schema}

## Your Tools

- `graph_query_tool`: ask a structured question; it generates and runs a READ-ONLY
  Cypher query against the graph. Use for exact lookups, counts, aggregations,
  and relationship traversal (aircraft, systems, components, flights,
  maintenance events).
- `vector_search_tool`: semantic search over maintenance-document chunks. Use for
  conceptual or descriptive questions where wording varies and the answer
  lives in document text rather than structured graph data.

## Choosing a Tool

1. "How many...", "list...", "which aircraft...", anything counting or joining
   structured entities -> `graph_query_tool`.
2. "What does the manual say about...", "describe the procedure for...",
   fuzzy/topical questions over documents -> `vector_search_tool`.
3. If a tool returns nothing, say what you looked for and suggest an
   alternative phrasing or the other tool.

## Response Guidelines

- Cite the actual data returned; do not invent values.
- When an answer uses document chunks, cite the document ID from the chunk's
  [Source: ...] line.
- Format results clearly for a human reader.
- Be concise but thorough.
- All access is read-only. Never claim to have modified data."""
