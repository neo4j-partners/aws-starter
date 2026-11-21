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


def auth_error(error: BaseException) -> neo4j.exceptions.AuthError | None:
    """Return the rejected login in ``error`` or the errors it was raised from.

    The memory library raises its own ``ConnectionError`` from the driver's
    ``AuthError``, so the chain of causes is checked too. A chain that loops
    back on itself is checked once.
    """
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        if isinstance(cause, neo4j.exceptions.AuthError):
            return cause
        seen.add(id(cause))
        cause = cause.__cause__
    return None


def is_auth_error(error: BaseException) -> bool:
    """True when ``error``, or an error it was raised from, is a rejected login."""
    return auth_error(error) is not None


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
