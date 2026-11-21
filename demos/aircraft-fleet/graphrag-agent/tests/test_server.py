"""Tests for the ``server.invoke`` request handling paths.

These paths never reach Neo4j or Bedrock. Retrieval calls are monkeypatched.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time

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
    assert "session=from-header" in caplog.text
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


@pytest.mark.parametrize("top_k", [1, 20])
def test_top_k_bounds_are_accepted(top_k: int) -> None:
    assert server.RequestPayload(prompt="hi", top_k=top_k).top_k == top_k


@pytest.mark.parametrize("top_k", [0, -1, 21, 10_000])
def test_top_k_out_of_bounds_is_rejected(top_k: int) -> None:
    events = _run({"mode": "vector_search", "query": "leaks", "top_k": top_k})
    assert events == [{"type": "error", "error": "Invalid request payload. Invalid fields: top_k"}]


def _stop_before_the_agent(monkeypatch) -> None:
    def no_schema() -> str:
        raise ValueError("stop before the agent runs")

    monkeypatch.setattr(server, "get_graph_schema", no_schema)


def test_prompt_text_is_logged_only_at_debug(monkeypatch, caplog) -> None:
    _stop_before_the_agent(monkeypatch)
    prompt = "Which aircraft had an EGT exceedance?"
    with caplog.at_level("DEBUG", logger="fleet_graphrag.server"):
        _run({"prompt": prompt, "user_id": "pilot-7"}, session_id="s-1")
    info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert f"Request session=s-1 user=pilot-7 prompt_chars={len(prompt)}" in info
    assert not any(prompt in line for line in info)
    debug = [r.getMessage() for r in caplog.records if r.levelname == "DEBUG"]
    assert any(prompt in line for line in debug)


def test_direct_query_text_is_logged_only_at_debug(monkeypatch, caplog) -> None:
    monkeypatch.setattr(server, "graph_query", lambda query: "42")
    query = "count the aircraft"
    with caplog.at_level("DEBUG", logger="fleet_graphrag.server"):
        _run({"mode": "graph_query", "query": query})
    info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert f"graph_query direct call query_chars={len(query)}" in info
    assert not any(query in line for line in info)
    assert any(query in r.getMessage() for r in caplog.records if r.levelname == "DEBUG")


def test_user_id_control_characters_are_escaped(monkeypatch, caplog) -> None:
    _stop_before_the_agent(monkeypatch)
    user_id = "pilot\nINFO forged line\x1b[31m\u2028é"
    with caplog.at_level("INFO", logger="fleet_graphrag.server"):
        _run({"prompt": "hi", "user_id": user_id}, session_id="s-1")
    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Request ")]
    assert "user=pilot\\nINFO forged line\\x1b[31m\\u2028é " in line
    assert "\n" not in line
    assert "\x1b" not in line


def test_backslashes_are_escaped_so_a_literal_escape_is_distinct(monkeypatch, caplog) -> None:
    _stop_before_the_agent(monkeypatch)
    with caplog.at_level("INFO", logger="fleet_graphrag.server"):
        _run({"prompt": "hi", "user_id": "a\nb"}, session_id="s-1")
        _run({"prompt": "hi", "user_id": "a\\nb"}, session_id="s-1")
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Request ")]
    # A real newline and the two characters backslash and n must log differently.
    assert "user=a\\nb " in lines[0]
    assert "user=a\\\\nb " in lines[1]


def test_invalid_payload_names_fields_without_values(caplog) -> None:
    events = _run({"mode": "drop_database", "top_k": "lots", "inputText": 42})
    assert events == [
        {
            "type": "error",
            "error": "Invalid request payload. Invalid fields: mode, top_k, inputText",
        }
    ]
    # The log names each field and its error type, but not the values.
    assert "mode (enum), top_k (int_parsing), inputText (string_type)" in caplog.text
    assert "drop_database" not in caplog.text
    assert "lots" not in caplog.text


def test_invalid_prompt_text_stays_out_of_the_log(caplog) -> None:
    events = _run({"prompt": ["the secret question"]})
    assert events[0]["type"] == "error"
    assert "prompt (string_type)" in caplog.text
    assert "secret question" not in caplog.text


def test_session_id_control_characters_are_escaped(monkeypatch, caplog) -> None:
    _stop_before_the_agent(monkeypatch)
    with caplog.at_level("INFO", logger="fleet_graphrag.server"):
        _run({"prompt": "hi"}, session_id="s-1\nINFO forged line")
    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Request ")]
    assert "session=s-1\\nINFO forged line " in line
    assert "\n" not in line


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


def test_disconnect_closes_the_agent_stream_before_the_memory(monkeypatch) -> None:
    """The stream's own cleanup, where Strands flushes memory, runs before close."""
    order: list[str] = []

    class Memory(_FakeMemory):
        def close(self) -> None:
            order.append("close start")
            time.sleep(0.05)
            order.append("close end")

    class Agent(_FakeAgent):
        async def stream_async(self, prompt: str):
            try:
                for n in range(1000):
                    yield {"data": f"t{n}"}
                    await asyncio.sleep(0)
            finally:
                order.append("stream finally")

    monkeypatch.setattr(server, "get_graph_schema", lambda: "SCHEMA")
    monkeypatch.setattr(server, "session_manager", lambda s, u: Memory(s, u))
    monkeypatch.setattr(server, "Agent", lambda **kwargs: Agent(**kwargs))

    async def disconnect_mid_answer() -> None:
        stream = server.invoke({"prompt": "hi"}, RequestContext(session_id="s-1"))
        for _ in range(3):
            await anext(stream)
        await stream.aclose()
        # Give a stray close of the inner stream time to run, if one was scheduled.
        await asyncio.sleep(0.2)

    asyncio.run(disconnect_mid_answer())
    assert order == ["stream finally", "close start", "close end"]


def test_stream_close_failure_on_disconnect_is_logged(monkeypatch, caplog) -> None:
    """A flush that fails while the agent stream closes must not break the close."""

    class Agent(_FakeAgent):
        async def stream_async(self, prompt: str):
            try:
                for n in range(100):
                    yield {"data": f"t{n}"}
                    await asyncio.sleep(0)
            finally:
                # Stands in for the AfterInvocationEvent flush failing.
                raise RuntimeError("flush failed")

    made, _ = _agent_path(monkeypatch)
    monkeypatch.setattr(server, "Agent", lambda **kwargs: Agent(**kwargs))

    async def disconnect_mid_answer() -> None:
        stream = server.invoke({"prompt": "hi"}, RequestContext(session_id="s-1"))
        for _ in range(3):
            await anext(stream)
        await stream.aclose()

    asyncio.run(disconnect_mid_answer())
    assert made[0].closed == 1
    [record] = [
        r for r in caplog.records if r.getMessage() == "The agent stream failed while closing"
    ]
    assert record.exc_info is not None
    assert str(record.exc_info[1]) == "flush failed"


def test_cancel_with_a_failing_stream_close_ends_cancelled(monkeypatch, caplog) -> None:
    """A flush that fails while a cancel unwinds the stream must not end the request."""

    class Agent(_FakeAgent):
        async def stream_async(self, prompt: str):
            try:
                yield {"data": "partial "}
                # Waits for the model, where a cancel lands.
                await asyncio.sleep(10)
            finally:
                # Stands in for the AfterInvocationEvent flush failing.
                raise RuntimeError("flush failed")

    made, _ = _agent_path(monkeypatch)
    monkeypatch.setattr(server, "Agent", lambda **kwargs: Agent(**kwargs))
    events: list[dict] = []

    async def cancel_mid_answer() -> bool:
        async def consume() -> None:
            async for event in server.invoke({"prompt": "hi"}, RequestContext(session_id="s-1")):
                events.append(event)

        task = asyncio.create_task(consume())
        while not events:
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return task.cancelled()

    assert asyncio.run(cancel_mid_answer())
    assert events == [{"type": "chunk", "data": "partial "}]
    assert made[0].closed == 1
    assert "Error processing request" not in caplog.text
    [record] = [
        r for r in caplog.records if r.getMessage() == "The agent stream failed while closing"
    ]
    assert str(record.exc_info[1]) == "flush failed"


def test_close_failure_is_logged_not_sent(monkeypatch, caplog) -> None:
    made, _ = _agent_path(monkeypatch, close_error=True)
    events = _run({"prompt": "hi"}, session_id="s-1\nINFO forged line")
    assert events[-1] == {"type": "complete"}
    assert made[0].closed == 1
    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Could not")]
    assert line == "Could not close the memory session s-1\\nINFO forged line"


def test_failed_build_closes_the_memory_once(monkeypatch) -> None:
    made, _ = _agent_path(monkeypatch)

    def broken_agent(**kwargs: object) -> _FakeAgent:
        raise RuntimeError("restore failed")

    monkeypatch.setattr(server, "Agent", broken_agent)
    events = _run({"prompt": "hi"}, session_id="s-1")
    assert events == [{"type": "error", "error": server.GENERIC_ERROR}]
    assert made[0].closed == 1


def _blocked_build(monkeypatch) -> tuple[list[_FakeMemory], threading.Event, threading.Event]:
    """Make the Agent constructor block until ``release`` is set."""
    made, _ = _agent_path(monkeypatch)
    building, release = threading.Event(), threading.Event()

    def slow_agent(**kwargs: object) -> _FakeAgent:
        building.set()
        assert release.wait(5)
        # The close must not have run while the constructor used the manager.
        assert made[0].closed == 0
        return _FakeAgent(**kwargs)

    monkeypatch.setattr(server, "Agent", slow_agent)
    return made, building, release


async def _produce(stream) -> None:
    """Iterate a handler stream the way the AgentCore worker loop does.

    ``BedrockAgentCoreApp._async_gen_to_sync_gen`` runs this loop in a task.
    On a client disconnect it calls ``task.cancel()`` once, then the
    producer's finally awaits ``aclose()``.
    """
    try:
        async for _ in stream:
            pass
    finally:
        await stream.aclose()


def test_disconnect_during_the_build_closes_after_the_build(monkeypatch) -> None:
    made, building, release = _blocked_build(monkeypatch)

    async def disconnect_mid_build() -> None:
        stream = server.invoke({"prompt": "hi"}, RequestContext(session_id="s-1"))
        task = asyncio.create_task(_produce(stream))
        assert await asyncio.to_thread(building.wait, 5)
        task.cancel()
        # The request waits for the build before it closes the manager.
        await asyncio.sleep(0.05)
        assert not task.done()
        assert made[0].closed == 0
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(disconnect_mid_build())
    assert made[0].closed == 1
    assert not server._closing


def test_second_cancel_does_not_stop_the_close(monkeypatch) -> None:
    made, building, release = _blocked_build(monkeypatch)

    async def cancel_twice() -> None:
        stream = server.invoke({"prompt": "hi"}, RequestContext(session_id="s-1"))
        task = asyncio.create_task(_produce(stream))
        assert await asyncio.to_thread(building.wait, 5)
        task.cancel()
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # The request is gone, but its close task still waits for the build.
        [closing] = server._closing
        assert made[0].closed == 0
        release.set()
        await closing

    asyncio.run(cancel_twice())
    assert made[0].closed == 1
