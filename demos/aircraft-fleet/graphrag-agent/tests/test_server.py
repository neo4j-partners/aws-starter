"""Tests for the ``server.invoke`` request handling paths.

These paths never reach Neo4j or Bedrock. Retrieval calls are monkeypatched.
"""

from __future__ import annotations

import asyncio

import neo4j
import pytest
from bedrock_agentcore.runtime import RequestContext

from fleet_graphrag import server


def _run(payload: dict | None, session_id: str | None = None) -> list[dict]:
    async def collect() -> list[dict]:
        ctx = RequestContext(session_id=session_id)
        return [event async for event in server.invoke(payload, ctx)]

    return asyncio.run(collect())


def test_handler_takes_context() -> None:
    assert server.app._takes_context(server.invoke)


def test_invalid_mode_is_rejected() -> None:
    events = _run({"mode": "drop_database"})
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "Invalid request payload" in events[0]["error"]


def test_missing_prompt_is_an_error() -> None:
    events = _run({})
    assert events == [
        {
            "type": "error",
            "error": "No prompt provided. Please include 'prompt' in your request.",
        }
    ]


def test_missing_query_for_data_mode() -> None:
    events = _run({"mode": "graph_query"})
    assert events[0]["type"] == "error"
    assert "No query provided for mode 'graph_query'" in events[0]["error"]


def test_schema_mode_streams_chunk_then_complete(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_graph_schema", lambda: "SCHEMA")
    assert _run({"mode": "schema"}) == [
        {"type": "chunk", "data": "SCHEMA"},
        {"type": "complete"},
    ]


def test_vector_search_mode_passes_top_k(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_search(query: str, top_k: int) -> str:
        calls.append((query, top_k))
        return "chunks"

    monkeypatch.setattr(server, "vector_search", fake_search)
    events = _run({"mode": "vector_search", "query": "leaks", "top_k": "3"})
    assert calls == [("leaks", 3)]
    assert events[0] == {"type": "chunk", "data": "chunks"}


def test_generic_error_does_not_leak_details(monkeypatch) -> None:
    secret = "bolt://admin:hunter2@10.0.0.5"

    def boom(_query: str) -> str:
        raise ValueError(secret)

    monkeypatch.setattr(server, "graph_query", boom)
    events = _run({"mode": "graph_query", "query": "count aircraft"})
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert secret not in events[0]["error"]
    assert "check the server logs" in events[0]["error"]


def test_session_id_comes_from_context(monkeypatch, caplog) -> None:
    def no_schema() -> str:
        raise ValueError("stop before the agent runs")

    monkeypatch.setattr(server, "get_graph_schema", no_schema)
    with caplog.at_level("INFO", logger="fleet_graphrag.server"):
        _run({"prompt": "hi", "session_id": "from-payload"}, session_id="from-header")
    assert "session from-header" in caplog.text
    assert "from-payload" not in caplog.text


@pytest.mark.parametrize(("env", "expected"), [(None, 7070), ("9001", 9001)])
def test_main_port(monkeypatch, env: str | None, expected: int) -> None:
    ports: list[int] = []
    monkeypatch.setattr(server.app, "run", lambda port: ports.append(port))
    if env is None:
        monkeypatch.delenv("AGENT_PORT", raising=False)
    else:
        monkeypatch.setenv("AGENT_PORT", env)
    server.main()
    assert ports == [expected]


def test_user_id_defaults_to_anonymous() -> None:
    assert server.RequestPayload(prompt="hi").user_id == "anonymous"


@pytest.mark.parametrize("user_id", [None, ""])
def test_null_or_empty_user_id_is_anonymous(user_id: str | None) -> None:
    payload = server.RequestPayload.model_validate({"prompt": "hi", "user_id": user_id})
    assert payload.user_id == "anonymous"


def test_user_id_is_kept() -> None:
    assert server.RequestPayload(prompt="hi", user_id="pilot-7").user_id == "pilot-7"


def test_invalid_payload_names_fields_without_values(caplog) -> None:
    events = _run({"mode": "drop_database", "top_k": "lots", "inputText": 42})
    assert events == [
        {
            "type": "error",
            "error": "Invalid request payload. Invalid fields: mode, top_k, inputText",
        }
    ]
    # The rejected values stay in the server log.
    assert "drop_database" in caplog.text


def test_env_file_is_overridden_for_tests() -> None:
    assert str(server.ENV_FILE) == server.os.devnull


def test_config_error_detail_stays_in_the_log(monkeypatch, caplog) -> None:
    def missing() -> str:
        raise server.ConfigError("NEO4J_PASSWORD is not set.")

    monkeypatch.setattr(server, "get_graph_schema", missing)
    with caplog.at_level("ERROR"):
        events = _run({"mode": "schema"})
    assert events == [
        {"type": "error", "error": "The agent is not configured. Check the server logs."}
    ]
    assert "NEO4J_PASSWORD is not set." in caplog.text


def test_other_runtime_errors_get_the_generic_message(monkeypatch) -> None:
    def broken() -> str:
        raise RuntimeError("internal detail")

    monkeypatch.setattr(server, "get_graph_schema", broken)
    [event] = _run({"mode": "schema"})
    assert event["type"] == "error"
    assert "internal detail" not in event["error"]


def _raise_in_schema(monkeypatch, error: Exception) -> dict:
    def fail() -> str:
        raise error

    monkeypatch.setattr(server, "get_graph_schema", fail)
    [event] = _run({"mode": "schema"})
    assert event["type"] == "error"
    return event


@pytest.mark.parametrize(
    "code",
    [
        "Neo.ClientError.Transaction.TransactionTimedOut",
        "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration",
    ],
)
def test_transaction_timeout_says_the_query_took_too_long(monkeypatch, code) -> None:
    error = neo4j.exceptions.Neo4jError._hydrate_neo4j(code=code, message="timed out")
    event = _raise_in_schema(monkeypatch, error)
    assert event["error"] == "The query took too long. Try a narrower question."


@pytest.mark.parametrize(
    "error",
    [
        neo4j.exceptions.ServiceUnavailable("no route"),
        neo4j.exceptions.SessionExpired("expired"),
        neo4j.exceptions.Neo4jError._hydrate_neo4j(
            code="Neo.ClientError.Security.Unauthorized", message="bad password"
        ),
    ],
)
def test_connection_failures_say_neo4j_is_unreachable(monkeypatch, error) -> None:
    event = _raise_in_schema(monkeypatch, error)
    assert event["error"].startswith("Could not reach the Neo4j database.")


def test_other_neo4j_errors_get_the_generic_message(monkeypatch) -> None:
    error = neo4j.exceptions.Neo4jError._hydrate_neo4j(
        code="Neo.ClientError.Statement.SyntaxError", message="bad cypher"
    )
    event = _raise_in_schema(monkeypatch, error)
    assert event["error"] == server.GENERIC_ERROR
