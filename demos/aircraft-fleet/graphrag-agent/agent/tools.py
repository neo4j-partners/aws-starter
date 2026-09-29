"""Strands-native tool wrappers over the framework-agnostic retrieval callables.

Imported by ``runtime_app.py`` (the only agent builder). The wrapped callables
in :mod:`agent.retrieval` carry no Strands dependency; the ``@tool`` decorator
and the docstrings the LLM sees live here.
"""

from strands import tool

from agent.retrieval import graph_query, vector_search


@tool
def graph_query_tool(question: str) -> str:
    """Answer a structured question by generating and running read-only Cypher.

    Use for exact lookups, counts, aggregations, and relationship traversal
    over the aircraft graph (aircraft, systems, components, flights,
    maintenance events). For fuzzy document search, use vector_search_tool.

    Args:
        question: Natural-language question about the graph.
    """
    return graph_query(question)


@tool
def vector_search_tool(query: str, top_k: int = 5) -> str:
    """Semantic search over aircraft maintenance-document chunks.

    Use for conceptual or descriptive questions where wording varies and the
    answer lives in document text. For exact lookups or counts, use
    graph_query_tool instead.

    Args:
        query: Natural-language search text.
        top_k: Number of chunks to return (default 5).
    """
    return vector_search(query, top_k)
