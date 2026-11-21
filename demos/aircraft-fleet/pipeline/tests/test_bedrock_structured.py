"""StructuredBedrockLLM tool-argument validation, with stubbed Converse replies."""

from __future__ import annotations

from typing import Any

import pytest
from neo4j_graphrag.components.types import Neo4jGraph
from neo4j_graphrag.types import LLMMessage

from populate_aircraft_db.bedrock_structured import (
    _MISS_PREFIX,
    _TOOL_NAME,
    StructuredBedrockLLM,
)

_VALID = {"nodes": [{"id": "0", "label": "Fault", "properties": {}}], "relationships": []}
# A node with no label fails Neo4jGraph validation.
_INVALID = {"nodes": [{"id": "0", "properties": {}}], "relationships": []}
_INPUT: list[LLMMessage] = [{"role": "user", "content": "Extract the graph."}]


def _tool_reply(arguments: dict[str, Any]) -> dict[str, Any]:
    block = {"toolUse": {"toolUseId": "t1", "name": _TOOL_NAME, "input": arguments}}
    return {"stopReason": "tool_use", "output": {"message": {"content": [block]}}}


@pytest.fixture
def llm() -> StructuredBedrockLLM:
    # Creating the boto3 client makes no network call, and _converse is stubbed.
    return StructuredBedrockLLM(model_name="test-model", region_name="us-east-1")


def _stub_replies(
    monkeypatch: pytest.MonkeyPatch, llm: StructuredBedrockLLM, *replies: dict[str, Any]
) -> list[dict[str, Any]]:
    """Make _converse return the replies in order, and record each call."""
    queue = list(replies)
    calls: list[dict[str, Any]] = []

    def converse(kwargs: dict[str, Any]) -> dict[str, Any]:
        calls.append(kwargs)
        return queue.pop(0)

    monkeypatch.setattr(llm, "_converse", converse)
    return calls


def test_valid_arguments_are_returned(
    monkeypatch: pytest.MonkeyPatch, llm: StructuredBedrockLLM
) -> None:
    calls = _stub_replies(monkeypatch, llm, _tool_reply(_VALID))

    result = llm.invoke(_INPUT, response_format=Neo4jGraph)

    assert Neo4jGraph.model_validate_json(result.content).nodes[0].label == "Fault"
    assert (len(calls), llm.miss_count) == (1, 0)


def test_invalid_arguments_are_retried(
    monkeypatch: pytest.MonkeyPatch, llm: StructuredBedrockLLM
) -> None:
    calls = _stub_replies(monkeypatch, llm, _tool_reply(_INVALID), _tool_reply(_VALID))

    result = llm.invoke(_INPUT, response_format=Neo4jGraph)

    assert Neo4jGraph.model_validate_json(result.content).nodes[0].label == "Fault"
    assert (len(calls), llm.miss_count) == (2, 0)


def test_invalid_arguments_twice_are_a_miss(
    monkeypatch: pytest.MonkeyPatch, llm: StructuredBedrockLLM
) -> None:
    calls = _stub_replies(monkeypatch, llm, _tool_reply(_INVALID), _tool_reply(_INVALID))

    result = llm.invoke(_INPUT, response_format=Neo4jGraph)

    assert result.content.startswith(_MISS_PREFIX)
    assert "failed Neo4jGraph validation" in result.content
    assert "nodes.0.label" in result.content
    assert (len(calls), llm.miss_count) == (2, 1)
