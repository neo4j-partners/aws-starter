"""classify_tool_error, on error texts captured from the Neo4j MCP server.

The server texts below were captured from mcp-neo4j-cypher 0.6.0 with the
neo4j 6.4.1 driver, locally and through the fleet Gateway, which passes them
through unchanged.
"""

import pytest

from fleet_supervisor.core.tool_errors import (
    DATABASE_ERROR_RESULT,
    TIMEOUT_RESULT,
    UNAVAILABLE_RESULT,
    ErrorKind,
    classify_tool_error,
)

SYNTAX_ERROR = (
    "Error calling tool 'read_neo4j_cypher': {neo4j_code: Neo.ClientError.Statement.SyntaxError}"
    " {message: Invalid input 'MATC': expected 'ALTER', 'ORDER BY', 'CALL', 'WITH' or '{'"
    ' (line 1, column 9 (offset: 8))\n"EXPLAIN MATC (n) RETURN n"\n         ^}'
    " {gql_status: 42001} {gql_status_description: error: syntax error or access rule"
    " violation - invalid syntax}"
)
UNKNOWN_PROCEDURE = (
    "Error calling tool 'read_neo4j_cypher': {neo4j_code: Neo.ClientError.Procedure."
    "ProcedureNotFound} {message: There is no procedure with the name `db.nosuch` registered"
    " for this database instance. Please ensure you've spelled the procedure name correctly"
    " and that the procedure is properly deployed.} {gql_status: 42001}"
    " {gql_status_description: error: syntax error or access rule violation - invalid syntax}"
)
DIVISION_BY_ZERO = (
    "Neo4j Error: {neo4j_code: Neo.ClientError.Statement.ArithmeticError} {message: / by zero}"
    " {gql_status: 22012} {gql_status_description: error: data exception - division by zero}"
    "\nRETURN 1/0 AS x\n{}"
)
REFUSED_WRITE = (
    "Error calling tool 'read_neo4j_cypher': Only MATCH queries are allowed for read-query"
)
UNREACHABLE = (
    "Error calling tool 'read_neo4j_cypher': Couldn't connect to host.docker.internal:37687"
    " (resolved to ('0.250.250.254:37687',)):\nFailed to establish connection to"
    " ResolvedIPv4Address(('0.250.250.254', 37687)) (reason [Errno 111] Connect call failed"
    " ('0.250.250.254', 37687))"
)
TRANSACTION_TIMEOUT = (
    "Neo4j Error: {neo4j_code: Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration}"
    " {message: The transaction has been terminated. Retry your operation in a new transaction,"
    " and you should see a successful result. The transaction has not completed within the"
    " timeout specified at its start by the client. You may want to retry with a longer"
    " timeout. } {gql_status: 25N14} {gql_status_description: error: invalid transaction state"
    " - transaction termination client error.}\nMATCH (a) RETURN a\n{}"
)

ADDRESS_FRAGMENTS = (
    "host.docker.internal",
    "37687",
    "0.250.250.254",
    "abc123.databases.neo4j.io",
    "10.1.2.3",
    "db.internal",
)


def test_syntax_error_keeps_code_and_message_for_the_model():
    error = classify_tool_error(SYNTAX_ERROR)
    assert error.kind is ErrorKind.QUERY
    assert error.code == "Neo.ClientError.Statement.SyntaxError"
    assert error.text.startswith(
        "The generated Cypher query failed: Neo.ClientError.Statement.SyntaxError:"
        " Invalid input 'MATC'"
    )
    assert error.text.endswith("Rephrase the question to fit the schema and try again.")
    assert "gql_status" not in error.text
    assert "Error calling tool" not in error.text


def test_procedure_error_is_a_query_error():
    error = classify_tool_error(UNKNOWN_PROCEDURE)
    assert error.kind is ErrorKind.QUERY
    assert "ProcedureNotFound: There is no procedure with the name `db.nosuch`" in error.text


def test_runtime_query_error_drops_the_echoed_query_and_params():
    error = classify_tool_error(DIVISION_BY_ZERO)
    assert error.kind is ErrorKind.QUERY
    assert error.text.startswith(
        "The generated Cypher query failed: Neo.ClientError.Statement.ArithmeticError: / by zero\n"
    )
    assert "RETURN 1/0" not in error.text


def test_refused_write_is_a_query_error():
    error = classify_tool_error(REFUSED_WRITE)
    assert error.kind is ErrorKind.QUERY
    assert "Only MATCH queries are allowed for read-query" in error.text


def test_transaction_timeout():
    error = classify_tool_error(TRANSACTION_TIMEOUT)
    assert (error.kind, error.text) == (ErrorKind.TIMEOUT, TIMEOUT_RESULT)


@pytest.mark.parametrize(
    "text",
    [
        UNREACHABLE,
        "Error: Unable to retrieve routing information\nMATCH (a) RETURN a\n{}",
        "Error: failed to obtain a connection from the pool within 60.0s (timeout)\n"
        "MATCH (a) RETURN a\n{}",
        "Error calling tool 'read_neo4j_cypher': ConnectionAcquisitionTimeoutError: pool full",
        "Error: SessionExpired: Failed to read from defunct connection IPv4Address(('db', 7687))",
        "Neo4j Error: {neo4j_code: Neo.ClientError.Security.Unauthorized} {message: The client"
        " is unauthorized due to authentication failure.} {gql_status: 42NFF}\nMATCH (a)\n{}",
        "Neo4j Error: {neo4j_code: Neo.TransientError.General.DatabaseUnavailable} {message:"
        " Database 'neo4j' is unavailable.} {gql_status: 51N33}\nMATCH (a)\n{}",
        "Tool execution failed: Client error '502 Bad Gateway' for url"
        " 'https://gw.example.amazonaws.com/mcp'",
    ],
    ids=[
        "connect",
        "routing",
        "pool-timeout",
        "pool-timeout-class",
        "session-expired",
        "auth",
        "database-unavailable",
        "gateway-request",
    ],
)
def test_connection_and_auth_failures_are_unavailable(text):
    error = classify_tool_error(text)
    assert (error.kind, error.text) == (ErrorKind.UNAVAILABLE, UNAVAILABLE_RESULT)


@pytest.mark.parametrize(
    "text",
    [
        "Neo4j Client Error: This instance of Neo4j does not have the APOC plugin installed.",
        "Neo4j Error: {neo4j_code: Neo.DatabaseError.General.UnknownError} {message: at"
        " 10.1.2.3:7687} {gql_status: 50N42}\nMATCH (a)\n{}",
        "Neo4j Error: {neo4j_code: Neo.ClientError.Security.Forbidden} {message: denied}"
        " {gql_status: 42NFF}\nMATCH (a)\n{}",
        "Unexpected Error: something new",
    ],
    ids=["apoc", "database-error", "forbidden", "unknown"],
)
def test_other_errors_get_the_fixed_database_result(text):
    error = classify_tool_error(text)
    assert (error.kind, error.text) == (ErrorKind.DATABASE, DATABASE_ERROR_RESULT)


def test_query_error_loses_server_addresses():
    text = (
        "{neo4j_code: Neo.ClientError.Statement.SyntaxError} {message: bad input near"
        " neo4j+s://abc123.databases.neo4j.io, 10.1.2.3:7687, and db.internal:7687}"
        " {gql_status: 42001}"
    )
    error = classify_tool_error(text)
    assert error.kind is ErrorKind.QUERY
    assert error.text.count("<address>") == 3
    assert not [f for f in ADDRESS_FRAGMENTS if f in error.text]


def test_query_error_message_is_cut_to_500_characters():
    text = (
        "{neo4j_code: Neo.ClientError.Statement.SyntaxError} {message: "
        + "x" * 2000
        + "} {gql_status: 42001}"
    )
    error = classify_tool_error(text)
    detail = error.text.removeprefix("The generated Cypher query failed: ").split("\n")[0]
    assert len(detail) == 500


@pytest.mark.parametrize(
    "text",
    [SYNTAX_ERROR, UNKNOWN_PROCEDURE, DIVISION_BY_ZERO, REFUSED_WRITE, UNREACHABLE],
)
def test_no_result_names_a_server_address(text):
    assert not [f for f in ADDRESS_FRAGMENTS if f in classify_tool_error(text).text]


def test_message_without_gql_status_stops_at_the_first_newline():
    text = (
        "{neo4j_code: Neo.ClientError.Statement.SyntaxError} {message: Invalid input 'MATC'\n"
        "\"MATC (a:Aircraft {tail: 'N-SECRET'}) RETURN a\"\n"
        " ^}"
    )
    error = classify_tool_error(text)
    assert error.kind is ErrorKind.QUERY
    assert "Invalid input 'MATC'\n" in error.text
    assert "N-SECRET" not in error.text


def test_one_line_message_without_gql_status_drops_the_closing_brace():
    text = "{neo4j_code: Neo.ClientError.Statement.ArithmeticError} {message: / by zero}"
    assert ": / by zero\n" in classify_tool_error(text).text
