"""Strands tool wrappers over the retrieval callables.

The callables in :mod:`core.graph.retrieval` carry no Strands dependency. The
``@tool`` decorator and the docstrings the model sees live here.
"""

import logging

import neo4j
from neo4j_graphrag.exceptions import Text2CypherRetrievalError
from strands import tool

from fleet_supervisor.core.graph.neo4j_errors import (
    UNREACHABLE,
    is_query_error,
    is_transaction_timeout,
)
from fleet_supervisor.core.graph.retrieval import graph_query, vector_search

logger = logging.getLogger(__name__)

# Strands sends a tool's exception text to the model, and a driver message can
# name the server address. These fixed results replace it. The details go to
# the log.
TIMEOUT_RESULT = (
    "The query took too long and was stopped. Try a narrower question, "
    "for example with a filter or fewer aircraft."
)
UNAVAILABLE_RESULT = (
    "The graph database is unavailable right now. Tell the user the data could not be reached."
)
DATABASE_ERROR_RESULT = (
    "The graph database returned an error. Tell the user the data could not be retrieved."
)
# Any other failure, such as a Bedrock error while generating the Cypher. Its
# text can name the account, a role, or a model ARN, so it stays in the log.
QUERY_FAILED_RESULT = (
    "The query could not be generated. Tell the user the question could not be answered right now."
)
SEARCH_FAILED_RESULT = (
    "The search could not be run. Tell the user the question could not be answered right now."
)
# A Cypher error from the database starts with this, followed by its message.
QUERY_ERROR_PREFIX = "The generated Cypher query failed:"
# The vector search returns between these many chunks. The tool description
# states the same bounds.
MIN_TOP_K = 1
MAX_TOP_K = 20
# Enough of a query error for the model to rephrase the question.
_MAX_QUERY_ERROR_CHARS = 500


def _neo4j_error_result(tool_name: str, error: Exception) -> str:
    """Log a driver error and return the fixed result the model sees."""
    if isinstance(error, UNREACHABLE):
        logger.error("%s: Neo4j unreachable", tool_name, exc_info=error)
        return UNAVAILABLE_RESULT
    if isinstance(error, neo4j.exceptions.Neo4jError) and is_transaction_timeout(error):
        logger.warning("%s: Neo4j transaction timed out: %s", tool_name, error)
        return TIMEOUT_RESULT
    logger.error("%s: Neo4j error", tool_name, exc_info=error)
    return DATABASE_ERROR_RESULT


def _query_error_result(message: str) -> str:
    return (
        f"{QUERY_ERROR_PREFIX} {message[:_MAX_QUERY_ERROR_CHARS]}\n"
        "Rephrase the question to fit the schema and try again."
    )


@tool
def graph_query_tool(question: str) -> str:
    """Answer a structured question by generating and running read-only Cypher.

    Use for exact lookups, counts, aggregations, and relationship traversal
    over the aircraft graph (aircraft, systems, components, flights,
    maintenance events). For fuzzy document search, use vector_search_tool.

    Args:
        question: Natural-language question about the graph.
    """
    try:
        return graph_query(question)
    except Text2CypherRetrievalError as e:
        # Raised for a syntax error or a refused write query. The text holds
        # the server's message or the query, never the server address.
        logger.warning("graph_query_tool: %s", e)
        return _query_error_result(str(e))
    except neo4j.exceptions.Neo4jError as e:
        if is_query_error(e):
            logger.warning("graph_query_tool: query error %s: %s", e.code, e.message)
            return _query_error_result(f"{e.code}: {e.message}")
        return _neo4j_error_result("graph_query_tool", e)
    except neo4j.exceptions.DriverError as e:
        return _neo4j_error_result("graph_query_tool", e)
    except Exception as e:
        logger.error("graph_query_tool failed", exc_info=e)
        return QUERY_FAILED_RESULT


@tool
def vector_search_tool(query: str, top_k: int = 5, aircraft_type: str | None = None) -> str:
    """Search aircraft maintenance-document chunks by meaning and keywords.

    Use for conceptual or descriptive questions where wording varies and the
    answer lives in document text. For exact lookups or counts, use
    graph_query_tool instead. Each chunk starts with a [Source: ...] line that
    names its document ID, aircraft type, and chunk number, and an Entities
    line lists the faults, components, and limits extracted from it.

    Args:
        query: Natural-language search text.
        top_k: Number of chunks to return, from 1 to 20 (default 5).
        aircraft_type: Search only this aircraft type's manual, such as
            "B737-800". Leave it out to search every manual.
    """
    top_k = min(max(top_k, MIN_TOP_K), MAX_TOP_K)
    # The search Cypher is fixed, so no error here is the model's to fix.
    try:
        return vector_search(query, top_k, aircraft_type)
    except (neo4j.exceptions.Neo4jError, neo4j.exceptions.DriverError) as e:
        return _neo4j_error_result("vector_search_tool", e)
    except Exception as e:
        # The embedding call to Bedrock can fail too. Its text stays in the log.
        logger.error("vector_search_tool failed", exc_info=e)
        return SEARCH_FAILED_RESULT
