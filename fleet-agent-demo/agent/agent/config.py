"""Static configuration shared by the agent entrypoints."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """Env-derived runtime configuration, resolved once via :meth:`from_env`.

    The vector index + embedder MUST match what ``bedrock-graphrag-pipeline``
    used to populate the graph, or vector search returns noise. They default
    to Amazon Bedrock Titan v2 (1024 dims) on the ``maintenanceChunkEmbeddings``
    index over :Chunk(text). Every field is env-overridable.
    """

    model_id: str = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    aws_region: str = "us-west-2"
    vector_index_name: str = "maintenanceChunkEmbeddings"
    embed_model_id: str = "amazon.titan-embed-text-v2:0"
    embed_dimensions: int = 1024

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from the environment, falling back to the defaults."""
        defaults = cls()
        return cls(
            model_id=os.getenv("MODEL_ID", defaults.model_id),
            aws_region=os.getenv("AWS_REGION", defaults.aws_region),
            vector_index_name=os.getenv(
                "VECTOR_INDEX_NAME", defaults.vector_index_name
            ),
            embed_model_id=os.getenv(
                "EMBED_MODEL_ID", defaults.embed_model_id
            ),
            embed_dimensions=int(
                os.getenv("EMBED_DIMENSIONS", str(defaults.embed_dimensions))
            ),
        )


# Resolved once at import. ``agent/__init__`` loads the shared
# fleet-agent-demo-root .env before this module is imported, so local-run
# vars are already in os.environ here.
settings = Settings.from_env()

SYSTEM_PROMPT_TEMPLATE = """You are a helpful aircraft fleet assistant with direct access to a Neo4j graph database. You answer questions using two tools — there is no Cypher console; use the tools.

## Database Schema (Pre-loaded)

The live schema is already known — do NOT ask for it, use this:

{schema}

## Your Tools

- `graph_query` — ask a structured question; it generates and runs a READ-ONLY
  Cypher query against the graph. Use for exact lookups, counts, aggregations,
  and relationship traversal (aircraft, systems, components, flights,
  maintenance events).
- `vector_search` — semantic search over maintenance-document chunks. Use for
  conceptual or descriptive questions where wording varies and the answer
  lives in document text rather than structured graph data.

## Choosing a Tool

1. "How many...", "list...", "which aircraft...", anything counting or joining
   structured entities -> `graph_query`.
2. "What does the manual say about...", "describe the procedure for...",
   fuzzy/topical questions over documents -> `vector_search`.
3. If a tool returns nothing, say what you looked for and suggest an
   alternative phrasing or the other tool.

## Response Guidelines

- Cite the actual data returned; do not invent values.
- Format results clearly for a human reader.
- Be concise but thorough.
- All access is read-only — never claim to have modified data."""
