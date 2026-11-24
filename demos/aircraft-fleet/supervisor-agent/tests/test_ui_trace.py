"""Verify the browser's trace against a real Strands supervisor stream."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import neo4j
import pytest
from neo4j_graphrag.exceptions import Text2CypherRetrievalError
from strands import Agent, tool

from fleet_supervisor.core.agents import MAINTENANCE_TOOL, SpecialistTool
from fleet_supervisor.core.events import EventMapper
from fleet_supervisor.core.graph import tools as graph_tools
from tests.test_agents import FakeModel


@tool
def graph_query_tool(question: str) -> str:
    """Return a fleet record for the requested question."""
    return "{'event_id': 'ME0042', 'tail_number': 'N95040A', 'duplicate': 'ME0042'}"


class ToolModel(FakeModel):
    def __init__(self, name: str, arguments: dict[str, str]):
        super().__init__(delay=0)
        self.name = name
        self.arguments = arguments
        self.called = False

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        if self.called:
            async for event in super().stream(*args, **kwargs):
                yield event
            return
        self.called = True
        yield {"messageStart": {"role": "assistant"}}
        yield {
            "contentBlockStart": {"start": {"toolUse": {"name": self.name, "toolUseId": "call"}}}
        }
        yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(self.arguments)}}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}


def test_nested_tool_completion_carries_evidence_before_the_chat_answer():
    specialist = SpecialistTool(
        MAINTENANCE_TOOL,
        "Look up maintenance events",
        lambda: Agent(
            model=ToolModel("graph_query_tool", {"question": "Hydraulics"}),
            tools=[graph_query_tool],
            callback_handler=None,
        ),
    )
    supervisor = Agent(
        model=ToolModel(MAINTENANCE_TOOL, {"input": "Hydraulics"}),
        tools=[specialist],
        callback_handler=None,
    )

    async def collect() -> list[dict]:
        mapper = EventMapper(trace=True)
        stream = mapper.stream(supervisor, "Hydraulics")
        return [mapped async for event in stream for mapped in mapper.map(event)]

    routed, started, completed, routed_completed, answer = asyncio.run(collect())
    assert routed == {
        "type": "agent",
        "name": "Maintenance Agent",
        "call_id": "call",
        "parent_id": None,
    }
    assert started == {
        "type": "tool",
        "name": "graph_query_tool",
        "call_id": "call/call",
        "parent_id": "call",
    }
    assert completed["call_id"] == "call/call"
    assert completed["status"] == "success"
    assert completed["evidence_ids"] == ["ME0042", "N95040A"]
    assert completed["duration_ms"] >= 0
    assert routed_completed["call_id"] == "call"
    assert answer == {"type": "chunk", "data": "answer"}


def test_an_error_status_does_not_become_evidence():
    mapper = EventMapper(trace=True)
    list(mapper.map({"current_tool_use": {"toolUseId": "t", "name": "graph_query_tool"}}))
    result = {
        "toolUseId": "t",
        "status": "error",
        "content": [
            {"text": "The generated Cypher query failed: ID ME0042."},
        ],
    }
    assert list(mapper.map({"fleet_tool_result": result, "duration_ms": 4})) == [
        {"type": "tool_complete", "call_id": "t", "status": "error", "duration_ms": 4},
    ]


def test_success_status_is_reported_as_success_whatever_the_text():
    mapper = EventMapper(trace=True)
    list(mapper.map({"current_tool_use": {"toolUseId": "t", "name": "graph_query_tool"}}))
    text = f"{graph_tools.QUERY_ERROR_PREFIX} appears in AC1001's notes."
    result = {"toolUseId": "t", "status": "success", "content": [{"text": text}]}
    (completed,) = mapper.map({"fleet_tool_result": result, "duration_ms": 4})
    assert completed["status"] == "success"
    assert completed["evidence_ids"] == ["AC1001"]


def _trace_one_graph_call(tool: Any, arguments: dict[str, str]) -> dict:
    """Run a real graph tool under a specialist and return its tool_complete event."""
    specialist = SpecialistTool(
        MAINTENANCE_TOOL,
        "Look up maintenance events",
        lambda: Agent(
            model=ToolModel(tool.tool_name, arguments),
            tools=[tool],
            callback_handler=None,
        ),
    )
    supervisor = Agent(
        model=ToolModel(MAINTENANCE_TOOL, {"input": "Hydraulics"}),
        tools=[specialist],
        callback_handler=None,
    )

    async def collect() -> list[dict]:
        mapper = EventMapper(trace=True)
        stream = mapper.stream(supervisor, "Hydraulics")
        return [mapped async for event in stream for mapped in mapper.map(event)]

    (completed,) = [
        event
        for event in asyncio.run(collect())
        if event["type"] == "tool_complete" and event["call_id"] == "call/call"
    ]
    return completed


@pytest.mark.parametrize(
    ("tool", "arguments", "patched", "error"),
    [
        (
            graph_tools.graph_query_tool,
            {"question": "q"},
            "graph_query",
            Text2CypherRetrievalError("Invalid input 'MATCHH' near ME0042"),
        ),
        (
            graph_tools.graph_query_tool,
            {"question": "q"},
            "graph_query",
            neo4j.exceptions.ServiceUnavailable("down"),
        ),
        (
            graph_tools.graph_query_tool,
            {"question": "q"},
            "graph_query",
            neo4j.exceptions.Neo4jError._hydrate_neo4j(
                code="Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration",
                message="timed out",
            ),
        ),
        (
            graph_tools.graph_query_tool,
            {"question": "q"},
            "graph_query",
            neo4j.exceptions.Neo4jError._hydrate_neo4j(
                code="Neo.ClientError.Security.Forbidden", message="denied"
            ),
        ),
        (graph_tools.graph_query_tool, {"question": "q"}, "graph_query", RuntimeError("x")),
        (graph_tools.vector_search_tool, {"query": "q"}, "vector_search", RuntimeError("x")),
    ],
    ids=["query_error", "unavailable", "timeout", "database_error", "query_failed", "search"],
)
def test_each_graph_tool_failure_is_reported_as_an_error(
    monkeypatch: pytest.MonkeyPatch, tool: Any, arguments: dict[str, str], patched: str, error
):
    def fail(*args: object) -> str:
        raise error

    monkeypatch.setattr(graph_tools, patched, fail)
    completed = _trace_one_graph_call(tool, arguments)
    assert completed["status"] == "error"
    assert "evidence_ids" not in completed


def test_a_successful_graph_tool_is_reported_as_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_tools, "graph_query", lambda question: "ME0042 on N95040A")
    completed = _trace_one_graph_call(graph_tools.graph_query_tool, {"question": "q"})
    assert completed["status"] == "success"
    assert completed["evidence_ids"] == ["ME0042", "N95040A"]
