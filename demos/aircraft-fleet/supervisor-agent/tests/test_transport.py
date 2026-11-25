"""SSE parsing in the client transport."""

import json
import sys
from itertools import pairwise

import pytest
import urllib3.exceptions

from fleet_supervisor.client import cli, transport
from fleet_supervisor.client.invoke import load_queries
from fleet_supervisor.client.transport import (
    collect,
    invoke_deployed,
    iter_deployed_events,
    iter_events,
)


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
    result = collect(iter_events([body]))
    assert result.text == "line 1\nline 2"
    assert result.specialists == ["Maintenance Agent"]
    assert result.tools == ["gw___read_neo4j_cypher"]
    assert result.ok


def test_collect_records_errors_and_skips_junk():
    result = collect(
        iter_events([b"data: not json\n\n" + sse({"type": "error", "error": "failed"})])
    )
    assert result.errors == ["failed"]
    assert not result.ok


def test_the_cli_ignores_the_followups_event(capsys):
    events = iter_events(
        [
            sse(
                {"type": "chunk", "data": "Two aircraft."},
                {"type": "followups", "questions": ["Which tails?"]},
                {"type": "complete"},
            )
        ]
    )

    result = collect(events, on_event=cli.print_event)

    assert result.text == "Two aircraft."
    assert result.ok
    assert capsys.readouterr().out == "Two aircraft.\n"


def test_the_cli_ignores_the_memory_event(capsys):
    memory = {"type": "memory", "entries": [{"kind": "entity", "id": "e-1", "text": "N12345"}]}
    events = iter_events(
        [sse(memory, {"type": "chunk", "data": "Two aircraft."}, {"type": "complete"})]
    )

    result = collect(events, on_event=cli.print_event)

    assert result.text == "Two aircraft."
    assert result.ok
    assert capsys.readouterr().out == "Two aircraft.\n"


def test_queries_file_sets_expected_agent_from_headers():
    queries = load_queries()
    assert [q.number for q in queries] == list(range(1, 34))
    by_number = {q.number: q.expected_agent for q in queries}
    assert by_number[1] == by_number[18] == "Maintenance Agent"
    assert by_number[19] == by_number[33] == "Operations Agent"


class _FakeRawStream:
    """The urllib3 response under botocore's body, returning one read at a time."""

    def __init__(self, reads: list[bytes | Exception]) -> None:
        self._reads = list(reads)

    def read1(self, _size: int) -> bytes:
        if not self._reads:
            return b""
        if isinstance(read := self._reads.pop(0), Exception):
            raise read
        return read


class _FakeStream:
    """botocore's ``StreamingBody``, which the AgentCore reader reads through."""

    def __init__(self, *reads: bytes | Exception) -> None:
        self._raw_stream = _FakeRawStream(list(reads))
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeRuntimeClient:
    def __init__(self, *reads: bytes | Exception) -> None:
        self.kwargs: dict = {}
        self.stream = _FakeStream(*(reads or [sse({"type": "chunk", "data": "ok"})]))
        self.closed = False

    def invoke_agent_runtime(self, **kwargs):
        self.kwargs = kwargs
        return {"response": self.stream}

    def close(self) -> None:
        self.closed = True


def test_invoke_deployed_names_no_runtime_user(monkeypatch):
    """The agent needs no workload access token, so the call names no user."""
    fake = _FakeRuntimeClient()
    monkeypatch.setattr(transport.boto3, "client", lambda *args, **kwargs: fake)

    result = invoke_deployed("hi", "arn:aws:bedrock-agentcore:us-east-1:0:runtime/x", "us-east-1")

    assert "runtimeUserId" not in fake.kwargs
    assert len(fake.kwargs["runtimeSessionId"]) >= 33
    assert result.text == "ok"


def test_deployed_events_split_across_reads_and_characters():
    """Reads can end inside an event and inside a multi-byte character."""
    body = (
        sse({"type": "agent", "name": "Maintenance Agent"})
        + b"data: not json\n\n"
        + b"data: [1, 2]\n\n"
        + sse({"type": "chunk", "data": "naïve – ✈"}, {"type": "complete"})
    )
    plane = body.index("✈".encode())
    cuts = [5, body.index(b"\n\n") + 1, plane + 1, plane + 2, len(body) - 3]
    reads = [body[start:end] for start, end in pairwise([0, *cuts, len(body)])]
    stream = _FakeStream(*reads)

    events = list(iter_deployed_events({"response": stream}))

    assert events == [
        {"type": "agent", "name": "Maintenance Agent"},
        {"type": "chunk", "data": "naïve – ✈"},
        {"type": "complete"},
    ]
    assert stream.closed


def test_cli_reports_a_deployed_stream_that_fails_partway(monkeypatch, capsys):
    """A read timeout mid-stream prints an error line and exits 1, with no traceback."""
    timeout = urllib3.exceptions.ReadTimeoutError(None, None, "Read timed out.")
    fake = _FakeRuntimeClient(sse({"type": "chunk", "data": "Two aircraft"}), timeout)
    monkeypatch.setattr(transport.boto3, "client", lambda *args, **kwargs: fake)
    monkeypatch.setenv("AGENT_ARN", "arn:aws:bedrock-agentcore:us-east-1:0:runtime/x")
    monkeypatch.setattr(sys, "argv", ["fleet-supervisor-cli", "--remote", "hi"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 1
    out = capsys.readouterr().out
    assert "Two aircraft" in out
    assert "ERROR: The deployed supervisor stream failed:" in out
    assert fake.stream.closed
    assert fake.closed
