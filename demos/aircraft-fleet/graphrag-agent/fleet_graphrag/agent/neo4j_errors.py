"""Classify Neo4j driver errors for the messages clients and the model see.

``fleet_graphrag.server`` maps them to client error events, and
``fleet_graphrag.agent.tools`` maps them to tool results. Neither passes the
driver's own message through, because it can name the server address.
"""

import neo4j

# Failures to connect or authenticate.
UNREACHABLE = (
    neo4j.exceptions.ServiceUnavailable,
    neo4j.exceptions.SessionExpired,
    neo4j.exceptions.ConnectionPoolError,
    neo4j.exceptions.AuthError,
    neo4j.exceptions.DatabaseUnavailable,
)

# Server error code prefixes for a problem in the query text itself, such as
# a syntax error, an unknown function, or a bad argument.
_QUERY_ERROR_PREFIXES = ("Neo.ClientError.Statement.", "Neo.ClientError.Procedure.")


def is_transaction_timeout(error: neo4j.exceptions.Neo4jError) -> bool:
    """True for a server-side transaction timeout.

    The server reports ``...TransactionTimedOut`` for its own limit and
    ``...TransactionTimedOutClientConfiguration`` for the driver's
    ``neo4j.Query(timeout=...)``, which Text2Cypher sets.
    """
    return (error.code or "").startswith("Neo.ClientError.Transaction.TransactionTimedOut")


def is_query_error(error: neo4j.exceptions.Neo4jError) -> bool:
    """True when the server rejected the query text rather than the connection."""
    return (error.code or "").startswith(_QUERY_ERROR_PREFIXES)
