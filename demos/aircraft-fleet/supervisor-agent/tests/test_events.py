"""EventMapper turns Strands stream events into client SSE events."""

from fleet_supervisor.core import events
from fleet_supervisor.core.events import EventMapper


def tool_use(tool_id: str, name: str) -> dict:
    return {"toolUseId": tool_id, "name": name, "input": ""}


def specialist_event(outer_id: str, inner: dict) -> dict:
    """The shape Strands gives an event from inside an agent wrapped by as_tool."""
    return {
        "type": "tool_stream",
        "tool_stream_event": {
            "tool_use": tool_use(outer_id, "maintenance_specialist"),
            "data": inner,
        },
    }


def map_all(events: list[dict]) -> tuple[list[dict], EventMapper]:
    mapper = EventMapper()
    return [out for event in events for out in mapper.map(event)], mapper


def test_supervisor_text_becomes_chunks():
    out, _ = map_all([{"data": "Hello "}, {"data": "world"}])
    assert out == [{"type": "chunk", "data": "Hello "}, {"type": "chunk", "data": "world"}]


def test_specialist_call_becomes_one_agent_event():
    # Strands repeats current_tool_use for each input delta.
    repeated = {"current_tool_use": tool_use("t1", "maintenance_specialist")}
    out, mapper = map_all([repeated, repeated, repeated])
    assert out == [{"type": "agent", "name": "Maintenance Agent"}]
    assert mapper.specialists == ["Maintenance Agent"]


def test_both_specialists_are_reported_in_order():
    out, mapper = map_all(
        [
            {"current_tool_use": tool_use("t1", "operations_specialist")},
            {"current_tool_use": tool_use("t2", "maintenance_specialist")},
        ]
    )
    assert [e["name"] for e in out] == ["Operations Agent", "Maintenance Agent"]
    assert mapper.specialists == ["Operations Agent", "Maintenance Agent"]


def test_graph_tool_inside_specialist_becomes_tool_event():
    inner = {"current_tool_use": tool_use("m1", "graph_query_tool")}
    out, _ = map_all([specialist_event("t1", inner), specialist_event("t1", inner)])
    assert out == [{"type": "tool", "name": "graph_query_tool"}]


def test_specialist_text_is_not_forwarded():
    out, _ = map_all([specialist_event("t1", {"data": "inner draft"})])
    assert out == []


def test_events_without_text_or_tools_are_dropped():
    out, _ = map_all([{"init_event_loop": True}, {"reasoningText": "thinking"}, {"result": None}])
    assert out == []


def test_tool_use_without_id_is_ignored():
    out, _ = map_all([{"current_tool_use": {"name": "maintenance_specialist"}}])
    assert out == []


def test_a_call_cancelled_before_it_ran_completes_from_the_result_message(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(events, "monotonic", lambda: clock[0])
    mapper = EventMapper(trace=True)
    list(mapper.map({"current_tool_use": tool_use("t1", "maintenance_specialist")}))
    clock[0] += 0.25
    message = {
        "role": "user",
        "content": [
            {"toolResult": {"toolUseId": "t1", "status": "error", "content": [{"text": "x"}]}}
        ],
    }
    assert list(mapper.map({"message": message})) == [
        {"type": "tool_complete", "call_id": "t1", "status": "error", "duration_ms": 250},
    ]


def test_a_cancelled_graph_tool_inside_a_specialist_keeps_its_parent(monkeypatch):
    monkeypatch.setattr(events, "monotonic", lambda: 5.0)
    mapper = EventMapper(trace=True)
    list(
        mapper.map(
            specialist_event("outer", {"current_tool_use": tool_use("inner", "graph_query_tool")})
        )
    )
    message = {
        "content": [
            {"text": "ignored"},
            {"toolResult": {"toolUseId": "inner", "status": "error", "content": []}},
        ]
    }
    assert list(mapper.map(specialist_event("outer", {"message": message}))) == [
        {"type": "tool_complete", "call_id": "outer/inner", "status": "error", "duration_ms": 0},
    ]


def test_a_result_already_reported_is_not_repeated_by_the_message():
    mapper = EventMapper(trace=True)
    list(mapper.map({"current_tool_use": tool_use("t1", "graph_query_tool")}))
    result = {"toolUseId": "t1", "status": "success", "content": [{"text": "AC1001"}]}
    (completed,) = mapper.map({"fleet_tool_result": result, "duration_ms": 3})
    assert completed["evidence_ids"] == ["AC1001"]
    assert list(mapper.map({"message": {"content": [{"toolResult": result}]}})) == []


def test_result_messages_are_ignored_with_trace_off():
    mapper = EventMapper()
    list(mapper.map({"current_tool_use": tool_use("t1", "maintenance_specialist")}))
    message = {"content": [{"toolResult": {"toolUseId": "t1", "status": "error", "content": []}}]}
    assert list(mapper.map({"message": message})) == []
