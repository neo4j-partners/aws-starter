"""Strands-native tool wrappers over the framework-agnostic common callables.

Imported by both ``strands/runtime_app.py`` and ``strands/local_cli.py``: the
variant directory is ``sys.path[0]`` for the script entrypoints, so this is a
plain top-level module, not a package import.
"""

from strands import tool

from common import graph_query, vector_search


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
