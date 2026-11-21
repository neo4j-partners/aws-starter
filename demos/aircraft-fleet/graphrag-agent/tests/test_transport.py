"""Tests for the SSE parser and the status lookup in ``client.transport``."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from fleet_graphrag.client import transport
from fleet_graphrag.client.transport import (
    DeploymentNotFoundError,
    _consume_sse,
    _result,
    parse_status,
)


def _event(obj: dict) -> bytes:
    return f"data: {json.dumps(obj)}\n\n".encode()


# The server ends every successful response with this event.
COMPLETE = _event({"type": "complete"})


def test_chunks_join_in_order() -> None:
    raw = [
        _event({"type": "chunk", "data": "Hello"}),
        _event({"type": "chunk", "data": ", world"}),
        _event({"type": "complete"}),
    ]
    content, errors = _consume_sse(raw, stream=False)
    assert "".join(content) == "Hello, world"
    assert errors == []


def test_event_split_across_byte_chunks() -> None:
    whole = _event({"type": "chunk", "data": "split"}) + _event({"type": "chunk", "data": " ok"})
    raw = [whole[:7], whole[7:20], whole[20:]]
    content, _ = _consume_sse(raw, stream=False)
    assert content == ["split", " ok"]


def test_multibyte_utf8_split_across_byte_chunks() -> None:
    # BedrockAgentCoreApp serializes with ensure_ascii=False, so non-ASCII
    # text reaches the client as raw UTF-8 that can straddle two chunks.
    text = "3000 psi → OK"
    whole = f"data: {json.dumps({'type': 'chunk', 'data': text}, ensure_ascii=False)}\n\n"
    raw = whole.encode()
    cut = raw.index("→".encode()) + 1  # inside the three-byte sequence
    content, _ = _consume_sse([raw[:cut], raw[cut:]], stream=False)
    assert content == [text]


@pytest.mark.parametrize("separator", [b"\n\n", b"\r\n\r\n", b"\r\r"])
def test_each_line_ending_separates_events(separator: bytes) -> None:
    raw = separator.join(
        [
            b'data: {"type": "chunk", "data": "a"}',
            b'data: {"type": "chunk", "data": "b"}',
            b'data: {"type": "complete"}',
            b"",
        ]
    )
    content, errors = _consume_sse([raw], stream=False)
    assert content == ["a", "b"]
    assert errors == []


def test_crlf_split_across_chunks_is_one_line_ending() -> None:
    # \r ends one chunk and \n starts the next. Read as two line endings,
    # they would end the event early and split the second event's data line
    # from its blank-line terminator.
    first = b'data: {"type": "chunk", "data": "a"}\r\n\r'
    second = b'\ndata: {"type": "chunk", "data": "b"}\r'
    third = b"\n\r\n"
    content, errors = _consume_sse([first, second, third, COMPLETE], stream=False)
    assert content == ["a", "b"]
    assert errors == []


def test_trailing_cr_at_end_of_stream_ends_the_event() -> None:
    raw = [b'data: {"type": "chunk", "data": "a"}\r', b"\r"]
    content, _ = _consume_sse(raw, stream=False)
    assert content == ["a"]


def test_invalid_utf8_is_replaced_not_fatal() -> None:
    raw = [b'data: {"type": "chunk", "data": "ok \xff"}\n\n', COMPLETE]
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["ok \ufffd"]
    assert errors == []


@pytest.mark.parametrize(
    "raw",
    [
        # Cut between two events.
        [_event({"type": "chunk", "data": "partial"})],
        # Cut inside an event's JSON, at an ASCII byte.
        [_event({"type": "chunk", "data": "partial"}), b'data: {"type": "chu'],
    ],
)
def test_stream_cut_at_an_ascii_boundary_is_reported(raw: list[bytes]) -> None:
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["partial"]
    assert errors == [transport.TRUNCATED_STREAM]
    assert _result(content, errors)["status"] == "error"


def test_error_event_without_complete_is_not_truncation() -> None:
    raw = [_event({"type": "chunk", "data": "partial"}), _event({"type": "error", "error": "boom"})]
    _, errors = _consume_sse(raw, stream=False)
    assert errors == ["boom"]


def test_stream_cut_inside_a_character_is_reported() -> None:
    whole = _event({"type": "chunk", "data": "fine"}) + "→".encode()
    content, errors = _consume_sse([whole[:-1]], stream=False)
    assert content == ["fine"]
    assert errors == [transport.TRUNCATED_STREAM]


def test_newlines_in_chunk_data_survive() -> None:
    content, _ = _consume_sse([_event({"type": "chunk", "data": "a\n\nb"})], stream=False)
    assert content == ["a\n\nb"]


def test_tool_events_are_not_content() -> None:
    raw = [
        _event({"type": "tool", "name": "graph_query_tool"}),
        _event({"type": "chunk", "data": "42"}),
        COMPLETE,
    ]
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["42"]
    assert errors == []


def test_error_event_is_collected() -> None:
    content, errors = _consume_sse([_event({"type": "error", "error": "boom"})], stream=False)
    assert content == []
    assert errors == ["boom"]
    assert _result(content, errors) == {"status": "error", "errors": ["boom"]}


@pytest.mark.parametrize(
    "tail",
    [
        b'data: {"type": "chunk", "data": "tail"}',
        b'data: {"type": "chunk", "data": "tail"}\n',
        b'data: {"type": "complete"}\n',
    ],
)
def test_trailing_block_without_blank_line_is_discarded(tail: bytes, caplog) -> None:
    raw = [_event({"type": "chunk", "data": "ok"}), tail]
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["ok"]
    assert errors == [transport.TRUNCATED_STREAM]
    assert "Response stream ended inside an event" in caplog.text


@pytest.mark.parametrize(
    "raw",
    [
        [b"\xef\xbb\xbf" + _event({"type": "chunk", "data": "a"}), COMPLETE],
        # The byte order mark split across two chunks.
        [b"\xef", b"\xbb\xbf" + _event({"type": "chunk", "data": "a"}), COMPLETE],
    ],
)
def test_leading_byte_order_mark_is_dropped(raw: list[bytes]) -> None:
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["a"]
    assert errors == []


def test_sdk_error_event_without_type_is_an_error(caplog) -> None:
    sdk_error = {
        "error": "boom",
        "error_type": "RuntimeError",
        "message": "An error occurred during streaming",
    }
    raw = [_event({"type": "chunk", "data": "partial"}), _event(sdk_error)]
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["partial"]
    assert errors == ["boom"]
    assert "Response stream" not in caplog.text


@pytest.mark.parametrize("value", [None, 42, ["boom"], {"text": "boom"}])
def test_error_event_without_string_text_is_skipped_with_a_warning(value: object, caplog) -> None:
    raw = [_event({"type": "chunk", "data": "partial"}), _event({"type": "error", "error": value})]
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["partial"]
    # With the error skipped, the stream has no final event, so it was cut off.
    assert errors == [transport.TRUNCATED_STREAM]
    assert "Skipped an error event whose error is" in caplog.text


def test_bare_json_without_data_field_is_ignored() -> None:
    # Per the SSE format this line is a field named '{"type"', not data.
    content, errors = _consume_sse([b'{"type": "chunk", "data": "x"}\n\n'], stream=False)
    assert content == []
    assert errors == [transport.TRUNCATED_STREAM]


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ("data: x", "x"),
        # One optional space after the colon is removed, and only one.
        ("data:x", "x"),
        ("data:  x", " x"),
        # A field name with no colon has an empty value.
        ("data", ""),
        # Data lines join with a newline.
        ("data: a\ndata: b", "a\nb"),
        ("data: a\ndata\ndata: b", "a\n\nb"),
        # Comments and the event, id, retry, and unknown fields are ignored.
        (": note\nevent: message\nid: 7\nretry: 1000\nother: v\ndata: x", "x"),
        ("event: message\nid: 7", None),
        (": keep-alive", None),
    ],
)
def test_event_data_follows_the_sse_format(block: str, expected: str | None) -> None:
    assert transport._event_data(block) == expected


def test_data_split_over_several_lines_is_one_event() -> None:
    raw = [
        b'event: message\nid: 1\n: comment\ndata: {"type": "chunk",\ndata:"data": "x"}\n\n',
        b"retry: 500\n" + COMPLETE,
    ]
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["x"]
    assert errors == []


@pytest.mark.parametrize(
    "data",
    [b"[1, 2]", b'"text"', b"42", b"null", b"true"],
)
def test_non_object_json_is_skipped_with_a_warning(data: bytes, caplog) -> None:
    raw = [b"data: " + data + b"\n\n", _event({"type": "chunk", "data": "ok"}), COMPLETE]
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["ok"]
    assert errors == []
    assert "Skipped an SSE event whose data is a JSON" in caplog.text


@pytest.mark.parametrize("value", [None, 42, ["a"], {"text": "a"}])
def test_chunk_without_string_data_is_skipped_with_a_warning(value: object, caplog) -> None:
    raw = [
        _event({"type": "chunk", "data": value}),
        _event({"type": "chunk"}),
        _event({"type": "chunk", "data": "ok"}),
        COMPLETE,
    ]
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["ok"]
    assert errors == []
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 2
    assert all("Skipped a chunk event" in r.getMessage() for r in warnings)


def test_non_string_type_is_ignored() -> None:
    raw = [_event({"type": ["chunk"], "data": "x"}), COMPLETE]
    content, errors = _consume_sse(raw, stream=False)
    assert content == []
    assert errors == []


def test_non_json_and_blank_events_are_ignored() -> None:
    raw = [b"\n\n", b": keep-alive\n\n", _event({"type": "chunk", "data": "y"}), COMPLETE]
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["y"]
    assert errors == []


def test_success_result_shape() -> None:
    assert _result(["a", "b"], []) == {"status": "success", "response": "ab"}


def test_stream_false_prints_nothing(capsys) -> None:
    _consume_sse([_event({"type": "chunk", "data": "quiet"})], stream=False)
    assert capsys.readouterr().out == ""


ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/AircraftFleet_graphrag_agent-abc"


@pytest.fixture(autouse=True)
def _clear_status_cache() -> None:
    transport.get_agent_config.cache_clear()


def _status(**overrides: object) -> str:
    status: dict[str, object] = {
        "projectName": "AircraftFleet",
        "target": "default",
        "region": "us-east-1",
        "resources": [
            {
                "resourceType": "runtime",
                "name": "graphrag_agent",
                "deploymentState": "deployed",
                "arn": ARN,
            },
        ],
    }
    status.update(overrides)
    return json.dumps(status)


def test_parse_status_returns_deployed_runtime_arn() -> None:
    output = json.dumps(
        {
            "projectName": "AircraftFleet",
            "target": "default",
            "region": "us-west-2",
            "resources": [
                {
                    "resourceType": "credential",
                    "name": "x",
                    "deploymentState": "deployed",
                    "arn": "arn:other",
                },
                {
                    "resourceType": "runtime",
                    "name": "graphrag_agent",
                    "deploymentState": "deployed",
                    "arn": ARN,
                },
            ],
        }
    )
    assert parse_status(output) == (ARN, "us-west-2")


def test_parse_status_refuses_local_only_runtime() -> None:
    output = json.dumps(
        {
            "region": "us-east-1",
            "resources": [
                {
                    "resourceType": "runtime",
                    "name": "graphrag_agent",
                    "deploymentState": "local-only",
                },
            ],
        }
    )
    with pytest.raises(DeploymentNotFoundError, match="not deployed"):
        parse_status(output)


def test_parse_status_refuses_non_json() -> None:
    with pytest.raises(DeploymentNotFoundError, match="did not return JSON"):
        parse_status("Error: something")


def test_status_failure_raises_with_cli_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Error: No deployment targets are configured for project 'AircraftFleet'.",
        )

    monkeypatch.setattr(transport.subprocess, "run", fake_run)
    with pytest.raises(DeploymentNotFoundError, match="No deployment targets"):
        transport.get_agent_config()


def test_missing_cli_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("agentcore")

    monkeypatch.setattr(transport.subprocess, "run", fake_run)
    with pytest.raises(DeploymentNotFoundError, match="not installed"):
        transport.get_agent_config()


def test_status_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="agentcore", timeout=60)

    monkeypatch.setattr(transport.subprocess, "run", fake_run)
    with pytest.raises(DeploymentNotFoundError, match="did not finish"):
        transport.get_agent_config()


@pytest.mark.parametrize("output", ["[]", "null", '"text"', "42"])
def test_parse_status_refuses_non_object(output: str) -> None:
    with pytest.raises(DeploymentNotFoundError, match="did not return an object"):
        parse_status(output)


@pytest.mark.parametrize("region", [None, ""])
def test_parse_status_requires_region(region: str | None) -> None:
    with pytest.raises(DeploymentNotFoundError, match="region"):
        parse_status(_status(region=region))


def test_parse_status_matches_runtime_by_name() -> None:
    other = {
        "resourceType": "runtime",
        "name": "other_agent",
        "deploymentState": "deployed",
        "arn": "arn:other",
    }
    with pytest.raises(DeploymentNotFoundError, match="no Runtime named 'graphrag_agent'"):
        parse_status(_status(resources=[other]))


def test_parse_status_ignores_malformed_resources() -> None:
    with pytest.raises(DeploymentNotFoundError, match="no Runtime named"):
        parse_status(_status(resources={"runtime": ARN}))


def test_parse_status_refuses_deployed_runtime_without_arn() -> None:
    runtime = {"resourceType": "runtime", "name": "graphrag_agent", "deploymentState": "deployed"}
    with pytest.raises(DeploymentNotFoundError, match="not deployed"):
        parse_status(_status(resources=[runtime]))


def test_status_names_target_and_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=_status(), stderr="")

    monkeypatch.setattr(transport.subprocess, "run", fake_run)
    assert transport.get_agent_config() == (ARN, "us-east-1")
    assert transport.get_agent_config() == (ARN, "us-east-1")
    assert calls == [["agentcore", "status", "--json", "--target", "default"]]


def test_status_failure_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter(
        [
            SimpleNamespace(returncode=1, stdout="", stderr="Error: throttled"),
            SimpleNamespace(returncode=0, stdout=_status(), stderr=""),
        ]
    )
    monkeypatch.setattr(transport.subprocess, "run", lambda *a, **k: next(results))
    with pytest.raises(DeploymentNotFoundError, match="throttled"):
        transport.get_agent_config()
    assert transport.get_agent_config() == (ARN, "us-east-1")


def _local_with(monkeypatch: pytest.MonkeyPatch, seen: list[httpx.Request]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_event({"type": "chunk", "data": "ok"}) + COMPLETE)

    real_client = httpx.Client

    def client(**kwargs: object) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(transport.httpx, "Client", client)


def test_local_call_sends_the_session_header(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    _local_with(monkeypatch, seen)
    result = transport.invoke({"prompt": "hi"}, stream=False, session_id="s" * 36)
    assert result == {"status": "success", "response": "ok"}
    assert seen[0].headers[transport.SESSION_HEADER] == "s" * 36


def test_local_call_without_session_sends_no_header(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    _local_with(monkeypatch, seen)
    transport.invoke({"prompt": "hi"}, stream=False)
    assert transport.SESSION_HEADER not in seen[0].headers


class _FakeAgentCore:
    def __init__(self) -> None:
        self.session_ids: list[str] = []

    def invoke_agent_runtime(self, **kwargs: object) -> dict:
        self.session_ids.append(str(kwargs["runtimeSessionId"]))
        return {"response": [_event({"type": "chunk", "data": "ok"}), COMPLETE]}


def _deployed(monkeypatch: pytest.MonkeyPatch) -> _FakeAgentCore:
    fake = _FakeAgentCore()
    monkeypatch.setattr(transport, "get_agent_config", lambda: ("arn", "us-east-1"))
    monkeypatch.setattr(transport.boto3, "client", lambda *a, **k: fake)
    return fake


def test_deployed_calls_reuse_the_given_session(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _deployed(monkeypatch)
    session_id = transport.new_session_id()
    for _ in range(2):
        transport.invoke({"prompt": "hi"}, target="deployed", stream=False, session_id=session_id)
    assert fake.session_ids == [session_id, session_id]


def test_deployed_calls_without_session_get_new_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _deployed(monkeypatch)
    for _ in range(2):
        transport.invoke({"prompt": "hi"}, target="deployed", stream=False)
    first, second = fake.session_ids
    assert first != second
    assert len(first) >= 33


PROMPT = "Which aircraft had an EGT exceedance last week?"


def _client_log_lines(caplog: pytest.LogCaptureFixture, level: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == level]


def test_deployed_call_logs_the_prompt_only_at_debug(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = _deployed(monkeypatch)
    with caplog.at_level("DEBUG", logger="fleet_graphrag.client"):
        transport.invoke({"prompt": PROMPT}, target="deployed", stream=False, session_id="s" * 33)
    info = _client_log_lines(caplog, "INFO")
    assert f"session={'s' * 33} prompt_chars={len(PROMPT)}" in info[0]
    assert not any(PROMPT in line for line in info)
    assert any(PROMPT in line for line in _client_log_lines(caplog, "DEBUG"))
    assert fake.session_ids == ["s" * 33]


def test_deployed_call_logs_the_session_it_creates(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = _deployed(monkeypatch)
    with caplog.at_level("INFO", logger="fleet_graphrag.client"):
        transport.invoke({"prompt": PROMPT}, target="deployed", stream=False)
    [session_id] = fake.session_ids
    assert f"session={session_id} " in _client_log_lines(caplog, "INFO")[0]


@pytest.mark.parametrize(("session_id", "logged"), [(None, "session=new"), ("s-1", "session=s-1")])
def test_local_call_logs_the_prompt_only_at_debug(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    session_id: str | None,
    logged: str,
) -> None:
    _local_with(monkeypatch, [])
    payload = {"mode": "graph_query", "query": PROMPT}
    with caplog.at_level("DEBUG", logger="fleet_graphrag.client"):
        transport.invoke(payload, stream=False, session_id=session_id)
    info = _client_log_lines(caplog, "INFO")
    assert f"{logged} prompt_chars={len(PROMPT)}" in info[0]
    assert not any(PROMPT in line for line in info)
    assert any(PROMPT in line for line in _client_log_lines(caplog, "DEBUG"))
