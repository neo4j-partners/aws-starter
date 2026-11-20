"""Tests for the SSE parser in ``client.transport``."""

from __future__ import annotations

import json

import pytest

from client.transport import _consume_sse, _result


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


@pytest.mark.xfail(
    strict=True,
    raises=UnicodeDecodeError,
    reason="Known bug, fix pending review: each byte chunk is decoded alone.",
)
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
