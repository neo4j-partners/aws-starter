"""Direct-to-Neo4j GraphRAG retrieval — the agent's only path to the database.

There is no MCP server and no AgentCore Gateway in this path. The agent
connects straight to Neo4j with the driver and answers questions with two
``neo4j-graphrag`` retrievers:

- ``vector_search``  — semantic search over maintenance-document chunks, using
  the ``maintenanceChunkEmbeddings`` index that ``bedrock-graphrag-pipeline``
  populates.
- ``graph_query``    — Text2Cypher: the LLM writes a read-only Cypher query
  from the live schema and the question, for exact/aggregate answers.

The embedder here MUST match the one ``bedrock-graphrag-pipeline`` used to
populate the graph, or vector search returns noise. It defaults to Amazon
Bedrock Titan v2 (1024 dims); both are env-overridable.

Nothing in this module imports Strands. ``agent.tools`` wraps the two
callables below as Strands-native tools.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

import neo4j
from neo4j import Driver, GraphDatabase
from neo4j_graphrag.embeddings import BedrockEmbeddings
from neo4j_graphrag.llm import BedrockLLM
from neo4j_graphrag.retrievers import Text2CypherRetriever, VectorRetriever
from neo4j_graphrag.schema import get_schema
from neo4j_graphrag.types import RetrieverResultItem

from agent.config import (
    AWS_REGION,
    EMBED_DIMENSIONS,
    EMBED_MODEL_ID,
    MODEL_ID,
    VECTOR_INDEX_NAME,
)

logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. The fleet agent connects directly to Neo4j; "
            f"set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD (e.g. in the "
            f"agent-root .env for local runs, or as Runtime env vars when "
            f"deployed)."
        )
    return value


_driver: Driver | None = None


def get_driver() -> Driver:
    """Process-wide Neo4j driver (a connection pool — created once)."""
    global _driver
    if _driver is None:
        uri = _require_env("NEO4J_URI")
        username = os.environ.get("NEO4J_USERNAME", "neo4j")
        password = _require_env("NEO4J_PASSWORD")
        logger.info("Connecting to Neo4j at %s", uri)
        _driver = GraphDatabase.driver(uri, auth=(username, password))
    return _driver


def _neo4j_database() -> str:
    return os.environ.get("NEO4J_DATABASE", "neo4j")


@lru_cache(maxsize=1)
def _embedder() -> BedrockEmbeddings:
    """Bedrock embedder — must match what bedrock-graphrag-pipeline used to populate."""
    return BedrockEmbeddings(
        model_id=EMBED_MODEL_ID,
        dimensions=EMBED_DIMENSIONS,
        region_name=AWS_REGION,
    )


def _chunk_formatter(record: neo4j.Record) -> RetrieverResultItem:
    """Return clean chunk text instead of the default ``str(node)`` dump."""
    node = record.get("node") or {}
    return RetrieverResultItem(
        content=node.get("text", ""),
        metadata={"score": record.get("score")},
    )


@lru_cache(maxsize=1)
def _vector_retriever() -> VectorRetriever:
    return VectorRetriever(
        get_driver(),
        index_name=VECTOR_INDEX_NAME,
        embedder=_embedder(),
        return_properties=["text"],
        result_formatter=_chunk_formatter,
        neo4j_database=_neo4j_database(),
    )


@lru_cache(maxsize=1)
def get_graph_schema() -> str:
    """Live Neo4j schema string — fetched once, reused for the process."""
    logger.info("Fetching Neo4j schema (first request)...")
    schema = get_schema(get_driver(), database=_neo4j_database())
    logger.info("Schema cached (%d bytes)", len(schema))
    return schema


@lru_cache(maxsize=1)
def _text2cypher_retriever() -> Text2CypherRetriever:
    return Text2CypherRetriever(
        get_driver(),
        llm=BedrockLLM(model_name=MODEL_ID, region_name=AWS_REGION),
        neo4j_schema=get_graph_schema(),
        neo4j_database=_neo4j_database(),
    )


def vector_search(query: str, top_k: int = 5) -> str:
    """Semantic search over aircraft maintenance-document chunks.

    Use for conceptual or descriptive questions ("what does the manual say
    about hydraulic leaks") where wording varies. For exact lookups, counts,
    or graph traversal, use ``graph_query`` instead.

    Args:
        query: Natural-language search text.
        top_k: Number of chunks to return (default 5).
    """
    result = _vector_retriever().search(query_text=query, top_k=top_k)
    if not result.items:
        return "No relevant document chunks found."
    return "\n\n---\n\n".join(item.content for item in result.items if item.content)


def graph_query(question: str) -> str:
    """Answer a structured question by generating and running read-only Cypher.

    Use for exact lookups, counts, aggregations, and relationship traversal
    over the aircraft graph (aircraft, systems, components, flights,
    maintenance events). For fuzzy document search, use ``vector_search``.

    Args:
        question: Natural-language question about the graph.
    """
    result = _text2cypher_retriever().search(query_text=question)
    if not result.items:
        return "The generated query returned no results."
    return "\n".join(str(item.content) for item in result.items)


def close() -> None:
    """Close the shared driver (best-effort; for CLI teardown)."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
