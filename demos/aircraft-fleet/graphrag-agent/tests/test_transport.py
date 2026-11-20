"""Tests for the SSE parser and the status lookup in ``client.transport``."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from client import transport
from client.transport import DeploymentNotFoundError, _consume_sse, _result, parse_status


def _event(obj: dict) -> bytes:
    return f"data: {json.dumps(obj)}\n\n".encode()


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
    whole = _event({"type": "chunk", "data": "split"}) + _event(
        {"type": "chunk", "data": " ok"}
    )
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


def test_newlines_in_chunk_data_survive() -> None:
    content, _ = _consume_sse(
        [_event({"type": "chunk", "data": "a\n\nb"})], stream=False
    )
    assert content == ["a\n\nb"]


def test_tool_events_are_not_content() -> None:
    raw = [
        _event({"type": "tool", "name": "graph_query_tool"}),
        _event({"type": "chunk", "data": "42"}),
    ]
    content, errors = _consume_sse(raw, stream=False)
    assert content == ["42"]
    assert errors == []


def test_error_event_is_collected() -> None:
    content, errors = _consume_sse(
        [_event({"type": "error", "error": "boom"})], stream=False
    )
    assert content == []
    assert errors == ["boom"]
    assert _result(content, errors) == {"status": "error", "errors": ["boom"]}


def test_trailing_event_without_blank_line() -> None:
    raw = [b'data: {"type": "chunk", "data": "tail"}']
    content, _ = _consume_sse(raw, stream=False)
    assert content == ["tail"]


def test_bare_json_without_data_prefix() -> None:
    content, _ = _consume_sse([b'{"type": "chunk", "data": "x"}\n\n'], stream=False)
    assert content == ["x"]


def test_non_json_and_blank_events_are_ignored() -> None:
    raw = [b"\n\n", b": keep-alive\n\n", _event({"type": "chunk", "data": "y"})]
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
            {"resourceType": "runtime", "name": "graphrag_agent",
             "deploymentState": "deployed", "arn": ARN},
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
                {"resourceType": "credential", "name": "x", "deploymentState": "deployed",
                 "arn": "arn:other"},
                {"resourceType": "runtime", "name": "graphrag_agent",
                 "deploymentState": "deployed", "arn": ARN},
            ],
        }
    )
    assert parse_status(output) == (ARN, "us-west-2")


def test_parse_status_refuses_local_only_runtime() -> None:
    output = json.dumps(
        {
            "region": "us-east-1",
            "resources": [
                {"resourceType": "runtime", "name": "graphrag_agent",
                 "deploymentState": "local-only"},
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
    other = {"resourceType": "runtime", "name": "other_agent",
             "deploymentState": "deployed", "arn": "arn:other"}
    with pytest.raises(DeploymentNotFoundError, match="no Runtime named 'graphrag_agent'"):
        parse_status(_status(resources=[other]))


def test_parse_status_ignores_malformed_resources() -> None:
    with pytest.raises(DeploymentNotFoundError, match="no Runtime named"):
        parse_status(_status(resources={"runtime": ARN}))


def test_parse_status_refuses_deployed_runtime_without_arn() -> None:
    runtime = {"resourceType": "runtime", "name": "graphrag_agent",
               "deploymentState": "deployed"}
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
