"""Tests for the model-facing error results in ``core.graph.tools``.

Most retrieval calls are monkeypatched, so those tests never reach Neo4j. The
rotation tests run the real driver against a fake Bolt server.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace

import neo4j
import pytest
from neo4j_graphrag.exceptions import Text2CypherRetrievalError

from fleet_supervisor.core.graph import retrieval, tools
from tests.fake_bolt import FakeNeo4j

ADDRESS = "10.1.2.3:7687"


def _server_error(code: str, message: str) -> neo4j.exceptions.Neo4jError:
    return neo4j.exceptions.Neo4jError._hydrate_neo4j(code=code, message=message)


def _raise(error: BaseException):
    def fail(*args: object) -> str:
        raise error

    return fail


def test_graph_query_result_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "graph_query", lambda question: "42")
    assert tools.graph_query_tool("How many aircraft?") == "42"


def test_text2cypher_error_is_returned_for_self_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = Text2CypherRetrievalError("Failed to get search result: Invalid input 'MATCHH'")
    monkeypatch.setattr(tools, "graph_query", _raise(error))
    result = tools.graph_query_tool("q")
    assert "Invalid input 'MATCHH'" in result
    assert "Rephrase the question" in result


def test_statement_error_is_returned_for_self_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _server_error("Neo.ClientError.Statement.ArgumentError", "bad argument to toInteger")
    monkeypatch.setattr(tools, "graph_query", _raise(error))
    result = tools.graph_query_tool("q")
    assert "Neo.ClientError.Statement.ArgumentError: bad argument to toInteger" in result


def test_query_error_text_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    error = _server_error("Neo.ClientError.Statement.SyntaxError", "x" * 5000)
    monkeypatch.setattr(tools, "graph_query", _raise(error))
    assert len(tools.graph_query_tool("q")) < 700


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            neo4j.exceptions.ServiceUnavailable(f"Couldn't connect to {ADDRESS}"),
            tools.UNAVAILABLE_RESULT,
        ),
        (
            neo4j.exceptions.SessionExpired(f"Session to {ADDRESS} expired"),
            tools.UNAVAILABLE_RESULT,
        ),
        (
            _server_error("Neo.ClientError.Security.Unauthorized", f"auth failed at {ADDRESS}"),
            tools.UNAVAILABLE_RESULT,
        ),
        (
            _server_error(
                "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration",
                f"timed out on {ADDRESS}",
            ),
            tools.TIMEOUT_RESULT,
        ),
        (
            _server_error("Neo.ClientError.Security.Forbidden", f"denied on {ADDRESS}"),
            tools.DATABASE_ERROR_RESULT,
        ),
        (
            _server_error(
                "Neo.TransientError.General.MemoryPoolOutOfMemoryError",
                f"out of memory on {ADDRESS}",
            ),
            tools.DATABASE_ERROR_RESULT,
        ),
        (
            neo4j.exceptions.ConfigurationError(f"bad routing to {ADDRESS}"),
            tools.DATABASE_ERROR_RESULT,
        ),
    ],
)
def test_driver_errors_get_fixed_results(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    expected: str,
) -> None:
    monkeypatch.setattr(tools, "graph_query", _raise(error))
    monkeypatch.setattr(tools, "vector_search", _raise(error))
    with caplog.at_level("INFO", logger="fleet_supervisor"):
        results = [tools.graph_query_tool("q"), tools.vector_search_tool("q")]
    assert results == [expected, expected]
    # The model never sees the address, and INFO records do not carry it.
    assert all(ADDRESS not in result for result in results)
    info = [r for r in caplog.records if r.levelname == "INFO"]
    assert all(ADDRESS not in r.getMessage() for r in info)
    # The detail stays in the WARNING and ERROR records.
    detail = "".join(caplog.handler.format(r) for r in caplog.records if r.levelno >= 30)
    assert ADDRESS in detail


def test_vector_search_query_errors_are_not_the_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _server_error("Neo.ClientError.Statement.SyntaxError", "index missing")
    monkeypatch.setattr(tools, "vector_search", _raise(error))
    assert tools.vector_search_tool("q") == tools.DATABASE_ERROR_RESULT


BEDROCK_DETAIL = (
    "AccessDeniedException: User arn:aws:sts::123456789012:assumed-role/AgentRole/s "
    "is not authorized to perform bedrock:InvokeModel"
)


def test_other_exceptions_get_fixed_results(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = RuntimeError(BEDROCK_DETAIL)
    monkeypatch.setattr(tools, "graph_query", _raise(error))
    monkeypatch.setattr(tools, "vector_search", _raise(error))
    with caplog.at_level("ERROR", logger="fleet_supervisor"):
        results = [tools.graph_query_tool("q"), tools.vector_search_tool("q")]
    assert results == [tools.QUERY_FAILED_RESULT, tools.SEARCH_FAILED_RESULT]
    # No account ID or ARN text reaches the model.
    for result in results:
        assert "123456789012" not in result
        assert "arn:" not in result
    # The detail and the traceback stay in the ERROR log.
    assert [r.levelname for r in caplog.records] == ["ERROR", "ERROR"]
    assert all(r.exc_info for r in caplog.records)
    assert "123456789012" in caplog.text


@pytest.mark.parametrize("name", ["graph_query", "vector_search"])
def test_cancellation_is_not_swallowed(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr(tools, name, _raise(asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        if name == "graph_query":
            tools.graph_query_tool("q")
        else:
            tools.vector_search_tool("q")


@pytest.mark.parametrize(("asked", "used"), [(0, 1), (-5, 1), (1, 1), (7, 7), (20, 20), (500, 20)])
def test_vector_search_top_k_is_clamped(
    monkeypatch: pytest.MonkeyPatch, asked: int, used: int
) -> None:
    calls: list[int] = []

    def fake_search(query: str, top_k: int, aircraft_type: str | None) -> str:
        calls.append(top_k)
        return "chunks"

    monkeypatch.setattr(tools, "vector_search", fake_search)
    tools.vector_search_tool("q", asked)
    assert calls == [used]


@pytest.mark.parametrize("aircraft_type", [None, "A320-200"])
def test_vector_search_passes_the_aircraft_type(
    monkeypatch: pytest.MonkeyPatch, aircraft_type: str | None
) -> None:
    calls: list[str | None] = []

    def fake_search(query: str, top_k: int, aircraft_type: str | None) -> str:
        calls.append(aircraft_type)
        return "chunks"

    monkeypatch.setattr(tools, "vector_search", fake_search)
    tools.vector_search_tool("q", aircraft_type=aircraft_type)
    assert calls == [aircraft_type]


def test_the_aircraft_type_is_optional_for_the_model() -> None:
    schema = tools.vector_search_tool.tool_spec["inputSchema"]["json"]
    assert "aircraft_type" in schema["properties"]
    assert "aircraft_type" not in schema.get("required", [])


def test_tool_description_states_the_top_k_bounds() -> None:
    schema = tools.vector_search_tool.tool_spec["inputSchema"]["json"]
    description = schema["properties"]["top_k"]["description"]
    assert f"from {tools.MIN_TOP_K} to {tools.MAX_TOP_K}" in description


@pytest.fixture
def tools_on_fake_neo4j(
    fake_neo4j: FakeNeo4j, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FakeNeo4j]:
    """Point the shared driver at the fake server with a login it rejects.

    The retrievers are replaced with ones that run one query on the shared
    driver, so no Bedrock call is made.
    """

    class DriverRetriever:
        def search(self, **_kwargs: object) -> SimpleNamespace:
            retrieval.get_driver().execute_query("RETURN 1", database_="neo4j")
            hit = SimpleNamespace(content="row", metadata={"chunk_index": 0, "entities": []})
            return SimpleNamespace(items=[hit], metadata={})

    monkeypatch.setenv("NEO4J_URI", fake_neo4j.uri)
    monkeypatch.setenv("NEO4J_USERNAME", "reader")
    monkeypatch.setenv("NEO4J_PASSWORD", "first-pw")
    monkeypatch.setattr(retrieval, "_driver", None)
    monkeypatch.setattr(retrieval, "_auth", None)
    monkeypatch.setattr(retrieval, "_text2cypher_retriever", DriverRetriever)
    monkeypatch.setattr(retrieval, "_hybrid_retriever", DriverRetriever)
    monkeypatch.setattr(retrieval, "get_graph_schema", lambda: "schema")
    monkeypatch.setattr(retrieval, "_embedder", lambda: SimpleNamespace(embed_query=lambda _q: []))
    yield fake_neo4j
    # Close only the driver. The retrievers here are fakes with no cache to clear.
    if retrieval._driver is not None:
        retrieval._driver.close()


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (lambda: tools.graph_query_tool("How many aircraft?"), "row"),
        (lambda: tools.vector_search_tool("hydraulic leak"), "row"),
    ],
    ids=["graph_query_tool", "vector_search_tool"],
)
def test_a_rotated_password_recovers_in_the_same_tool_call(
    tools_on_fake_neo4j: FakeNeo4j, monkeypatch: pytest.MonkeyPatch, call, expected: str
) -> None:
    """The driver opens a new connection, and Neo4j rejects its LOGON."""
    assert retrieval._shared_driver()[1].get_auth().credentials == "first-pw"
    monkeypatch.setenv("NEO4J_PASSWORD", "rotated-pw")

    assert expected in call()
    assert tools_on_fake_neo4j.logins == ["first-pw", "rotated-pw"]


# The embedding runs before the retried call, so a rotated login reruns only
# the Neo4j search and makes no second Bedrock embedding call.
def test_a_rotated_password_embeds_a_manual_search_once(
    tools_on_fake_neo4j: FakeNeo4j, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedded: list[str] = []

    def embed_query(query: str) -> list[float]:
        embedded.append(query)
        return []

    monkeypatch.setattr(retrieval, "_embedder", lambda: SimpleNamespace(embed_query=embed_query))
    assert retrieval._shared_driver()[1].get_auth().credentials == "first-pw"
    monkeypatch.setenv("NEO4J_PASSWORD", "rotated-pw")

    assert "row" in tools.vector_search_tool("hydraulic leak")
    assert tools_on_fake_neo4j.logins == ["first-pw", "rotated-pw"]
    assert embedded == ["hydraulic leak"]


@pytest.mark.parametrize(
    "call",
    [
        lambda: tools.graph_query_tool("How many aircraft?"),
        lambda: tools.vector_search_tool("hydraulic leak"),
    ],
    ids=["graph_query_tool", "vector_search_tool"],
)
def test_a_password_still_wrong_fails_the_tool_call_after_one_attempt(
    tools_on_fake_neo4j: FakeNeo4j, call
) -> None:
    assert call() == tools.UNAVAILABLE_RESULT
    assert tools_on_fake_neo4j.logins == ["first-pw"]
