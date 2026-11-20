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
    monkeypatch.setattr(server, "memory_settings", lambda: None)
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
        # Pool exhaustion. It subclasses ConnectionPoolError.
        neo4j.exceptions.ConnectionAcquisitionTimeoutError("pool exhausted"),
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


def test_main_builds_memory_settings_before_serving(monkeypatch) -> None:
    def missing() -> None:
        raise server.ConfigError("MEM_NEO4J_URI is not set.")

    served: list[int] = []
    monkeypatch.setattr(server.app, "run", lambda port: served.append(port))
    monkeypatch.setattr(server, "memory_settings", missing)
    with pytest.raises(server.ConfigError):
        server.main()
    assert served == []


class _FakeMemory:
    def __init__(self, session_id: str, user_id: str, *, close_error: bool = False) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.closed = 0
        self._close_error = close_error

    def close(self) -> None:
        self.closed += 1
        if self._close_error:
            raise RuntimeError("flush failed")


class _FakeAgent:
    """Stands in for ``strands.Agent``. ``fail`` raises mid-stream."""

    fail = False

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def stream_async(self, prompt: str):
        yield {"data": "partial "}
        if self.fail:
            raise RuntimeError("model blew up")
        yield {"data": "answer"}


def _agent_path(monkeypatch, *, fail: bool = False, close_error: bool = False):
    made: list[_FakeMemory] = []
    agents: list[_FakeAgent] = []

    def fake_manager(session_id: str, user_id: str) -> _FakeMemory:
        made.append(_FakeMemory(session_id, user_id, close_error=close_error))
        return made[-1]

    def fake_agent(**kwargs: object) -> _FakeAgent:
        agents.append(_FakeAgent(**kwargs))
        agents[-1].fail = fail
        return agents[-1]

    monkeypatch.setattr(server, "get_graph_schema", lambda: "SCHEMA")
    monkeypatch.setattr(server, "session_manager", fake_manager)
    monkeypatch.setattr(server, "Agent", fake_agent)
    return made, agents


def test_agent_gets_a_per_request_memory_that_is_closed(monkeypatch) -> None:
    made, agents = _agent_path(monkeypatch)
    events = _run({"prompt": "hi", "user_id": "pilot-7"}, session_id="s-1")
    assert events[-1] == {"type": "complete"}
    [memory] = made
    assert (memory.session_id, memory.user_id) == ("s-1", "pilot-7")
    assert agents[0].kwargs["session_manager"] is memory
    assert memory.closed == 1


def test_each_request_builds_its_own_memory(monkeypatch) -> None:
    made, _ = _agent_path(monkeypatch)
    _run({"prompt": "one"}, session_id="s-1")
    _run({"prompt": "two"}, session_id="s-1")
    assert len(made) == 2
    assert made[0] is not made[1]
    assert [m.closed for m in made] == [1, 1]


def test_memory_is_closed_when_the_agent_fails(monkeypatch) -> None:
    made, _ = _agent_path(monkeypatch, fail=True)
    events = _run({"prompt": "hi"}, session_id="s-1")
    assert events[-1] == {"type": "error", "error": server.GENERIC_ERROR}
    assert made[0].closed == 1


def test_memory_is_closed_when_the_client_disconnects(monkeypatch) -> None:
    made, _ = _agent_path(monkeypatch)

    async def first_chunk_then_disconnect() -> dict:
        stream = server.invoke({"prompt": "hi"}, RequestContext(session_id="s-1"))
        first = await anext(stream)
        await stream.aclose()
        return first

    assert asyncio.run(first_chunk_then_disconnect())["type"] == "chunk"
    assert made[0].closed == 1


def test_close_failure_is_logged_not_sent(monkeypatch, caplog) -> None:
    made, _ = _agent_path(monkeypatch, close_error=True)
    events = _run({"prompt": "hi"}, session_id="s-1")
    assert events[-1] == {"type": "complete"}
    assert made[0].closed == 1
    assert "Could not close the memory session s-1" in caplog.text
