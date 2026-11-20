"""Static configuration shared by the agent entrypoints."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import cast

from agent.model import DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, DEFAULT_MODEL_ID, Effort


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
    embed_model_id: str = "amazon.titan-embed-text-v2:0"
    embed_dimensions: int = 1024

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from the environment, falling back to the defaults."""
        defaults = cls()
        return cls(
            model_id=os.getenv("MODEL_ID", defaults.model_id),
            max_tokens=int(os.getenv("MAX_TOKENS", str(defaults.max_tokens))),
            effort=cast(Effort, os.getenv("MODEL_EFFORT", defaults.effort)),
            aws_region=os.getenv("AWS_REGION", defaults.aws_region),
            vector_index_name=os.getenv(
                "VECTOR_INDEX_NAME", defaults.vector_index_name
            ),
            fulltext_index_name=os.getenv(
                "FULLTEXT_INDEX_NAME", defaults.fulltext_index_name
            ),
            schema_ttl_s=int(os.getenv("SCHEMA_TTL_S", str(defaults.schema_ttl_s))),
            text2cypher_timeout_s=float(
                os.getenv("TEXT2CYPHER_TIMEOUT_S", str(defaults.text2cypher_timeout_s))
            ),
            text2cypher_max_rows=int(
                os.getenv("TEXT2CYPHER_MAX_ROWS", str(defaults.text2cypher_max_rows))
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
