"""EventMapper turns Strands stream events into client SSE events."""

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


def test_mcp_tool_inside_specialist_becomes_tool_event():
    inner = {"current_tool_use": tool_use("m1", "gw___read_neo4j_cypher")}
    out, _ = map_all([specialist_event("t1", inner), specialist_event("t1", inner)])
    assert out == [{"type": "tool", "name": "gw___read_neo4j_cypher"}]


def test_specialist_text_is_not_forwarded():
    out, _ = map_all([specialist_event("t1", {"data": "inner draft"})])
    assert out == []


def test_events_without_text_or_tools_are_dropped():
    out, _ = map_all([{"init_event_loop": True}, {"reasoningText": "thinking"}, {"result": None}])
    assert out == []


def test_tool_use_without_id_is_ignored():
    out, _ = map_all([{"current_tool_use": {"name": "maintenance_specialist"}}])
    assert out == []
