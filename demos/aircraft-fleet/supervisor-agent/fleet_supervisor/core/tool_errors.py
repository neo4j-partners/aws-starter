"""Turn Gateway tool error text into results that are safe for the model.

The Neo4j MCP server returns the driver's message as the tool's error text,
and Strands adds its own text when a request to the Gateway fails. Either can
name a server address. The supervisor has no driver, so it classifies the
text instead of an exception. The buckets and wording match the graphrag
agent's ``fleet_graphrag.agent.tools``:

- A query the server rejected keeps its code and message, so the model can
  fix its Cypher. Addresses are removed, and the message is cut to 500
  characters.
- A transaction timeout becomes :data:`TIMEOUT_RESULT`.
- A connection, pool, or auth failure becomes :data:`UNAVAILABLE_RESULT`.
- Anything else becomes :data:`DATABASE_ERROR_RESULT`.

Only the query error carries server text. The other results are fixed.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

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
# Enough of a query error for the model to rephrase the question.
_MAX_QUERY_ERROR_CHARS = 500

# The server formats a driver error as "{neo4j_code: X} {message: Y}
# {gql_status: Z} ...". The message can span lines and quote the query.
# Without the gql_status marker there is no safe end, so the message stops at
# the first newline and the echoed query is dropped.
_CODE = re.compile(r"\{neo4j_code: (Neo\.[A-Za-z]+\.[A-Za-z]+\.[A-Za-z]+)\}")
_MESSAGE = re.compile(
    r"\{message: (?:(?P<marked>.*?)\}(?= \{gql_status)|(?P<line>[^\n]*?)\}?(?=\n|\Z))",
    re.DOTALL,
)

_TIMEOUT_CODE_PREFIX = "Neo.ClientError.Transaction.TransactionTimedOut"
_QUERY_ERROR_PREFIXES = ("Neo.ClientError.Statement.", "Neo.ClientError.Procedure.")
# The codes the driver raises as AuthError or DatabaseUnavailable.
_UNAVAILABLE_CODES = frozenset(
    {
        "Neo.ClientError.Security.Unauthorized",
        "Neo.ClientError.Security.TokenExpired",
        "Neo.TransientError.General.DatabaseUnavailable",
    }
)

# The server refuses a write in read_neo4j_cypher with this sentence. The
# query is the model's own, so the model should see it.
_REFUSED_WRITE = "Only MATCH queries are allowed for read-query"

# Connection failures carry no code. The server includes the exception text,
# and sometimes the class name, of these driver errors: ServiceUnavailable,
# SessionExpired, ConnectionPoolError, ConnectionAcquisitionTimeoutError,
# AuthError, and DatabaseUnavailable.
_UNAVAILABLE_TEXT = re.compile(
    r"\b(?:ServiceUnavailable|SessionExpired|ConnectionPoolError"
    r"|ConnectionAcquisitionTimeoutError|AuthError|DatabaseUnavailable)\b"
    r"|Couldn't connect to"
    r"|Unable to retrieve routing information"
    r"|Failed to establish connection"
    r"|Timed out trying to establish connection"
    r"|failed to obtain a connection from the pool"
    r"|Failed to obtain connection towards"
    r"|Failed to (?:read from|write to) (?:defunct|closed) connection"
)
# Strands' text when the request to the Gateway itself failed, so no Neo4j
# answer came back.
_REQUEST_FAILED_PREFIX = "Tool execution failed:"

# Addresses to remove from a query error: URIs, IPv4 with an optional port,
# and host:port.
_ADDRESS = re.compile(
    r"\b[a-z][a-z0-9+.-]*://\S+"
    r"|\b\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?\b"
    r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+:\d{2,5}\b",
    re.IGNORECASE,
)


class ErrorKind(StrEnum):
    QUERY = "query"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    DATABASE = "database"


@dataclass(frozen=True)
class ModelSafeError:
    """What the model sees for one tool error, and why."""

    kind: ErrorKind
    text: str
    code: str | None = None


def _query_error_result(message: str) -> str:
    return (
        f"The generated Cypher query failed: {message[:_MAX_QUERY_ERROR_CHARS]}\n"
        "Rephrase the question to fit the schema and try again."
    )


def _without_addresses(text: str) -> str:
    return _ADDRESS.sub("<address>", text)


def classify_tool_error(text: str) -> ModelSafeError:
    """Map a tool's error text to the result the model may see."""
    if match := _CODE.search(text):
        code = match.group(1)
        if code.startswith(_TIMEOUT_CODE_PREFIX):
            return ModelSafeError(ErrorKind.TIMEOUT, TIMEOUT_RESULT, code)
        if code.startswith(_QUERY_ERROR_PREFIXES):
            message = _MESSAGE.search(text, match.end())
            text_part = message and (message["marked"] or message["line"] or "").strip()
            detail = f"{code}: {text_part}" if text_part else code
            return ModelSafeError(
                ErrorKind.QUERY, _query_error_result(_without_addresses(detail)), code
            )
        if code in _UNAVAILABLE_CODES:
            return ModelSafeError(ErrorKind.UNAVAILABLE, UNAVAILABLE_RESULT, code)
        return ModelSafeError(ErrorKind.DATABASE, DATABASE_ERROR_RESULT, code)
    if _REFUSED_WRITE in text:
        return ModelSafeError(ErrorKind.QUERY, _query_error_result(_REFUSED_WRITE))
    if _UNAVAILABLE_TEXT.search(text) or text.startswith(_REQUEST_FAILED_PREFIX):
        return ModelSafeError(ErrorKind.UNAVAILABLE, UNAVAILABLE_RESULT)
    return ModelSafeError(ErrorKind.DATABASE, DATABASE_ERROR_RESULT)
