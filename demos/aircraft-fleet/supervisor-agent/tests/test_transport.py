"""SSE parsing in the client transport."""

import json

from client.invoke import load_queries
from client.transport import collect, iter_events


def sse(*events: dict) -> bytes:
    return b"".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n".encode() for e in events)


def test_events_split_across_chunks_are_reassembled():
    body = sse({"type": "chunk", "data": "a"}, {"type": "complete"})
    chunks = [body[i : i + 7] for i in range(0, len(body), 7)]
    assert [e["type"] for e in iter_events(chunks)] == ["chunk", "complete"]


def test_multibyte_character_split_across_chunks():
    body = sse({"type": "chunk", "data": "naïve – ✈"})
    split = body.index("✈".encode()) + 1
    events = list(iter_events([body[:split], body[split:]]))
    assert events == [{"type": "chunk", "data": "naïve – ✈"}]


def test_collect_keeps_newlines_and_routing():
    body = sse(
        {"type": "agent", "name": "Maintenance Agent"},
        {"type": "tool", "name": "gw___read_neo4j_cypher"},
        {"type": "chunk", "data": "line 1\nline 2"},
        {"type": "complete"},
    )
    result = collect([body])
    assert result.text == "line 1\nline 2"
    assert result.specialists == ["Maintenance Agent"]
    assert result.tools == ["gw___read_neo4j_cypher"]
    assert result.ok


def test_collect_records_errors_and_skips_junk():
    result = collect([b"data: not json\n\n" + sse({"type": "error", "error": "failed"})])
    assert result.errors == ["failed"]
    assert not result.ok


def test_queries_file_sets_expected_agent_from_headers():
    queries = load_queries()
    assert len(queries) == 20
    by_number = {q.number: q.expected_agent for q in queries}
    assert by_number[1] == "Maintenance Agent"
    assert by_number[11] == "Operations Agent"
