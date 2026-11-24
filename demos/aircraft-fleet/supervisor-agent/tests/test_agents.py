"""Supervisor wiring and SpecialistTool behavior, with a fake model."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from strands import Agent, tool
from strands.models import Model
from strands.types.events import ToolResultEvent

from fleet_supervisor.core import agents, graph
from fleet_supervisor.core.agents import (
    MAINTENANCE_DESCRIPTION,
    MAINTENANCE_TOOL,
    OPERATIONS_TOOL,
    SPECIALIST_ERROR,
    SPECIALIST_NAMES,
    SpecialistTool,
    build_supervisor,
)
from fleet_supervisor.core.model import build_model

SCHEMA = "Node labels: Aircraft, MaintenanceEvent, Flight, Delay"


@tool
def graph_query_tool(question: str) -> str:
    """Stand-in for the graph query tool."""
    return question


@tool
def vector_search_tool(query: str, top_k: int = 5, aircraft_type: str | None = None) -> str:
    """Stand-in for the manual search tool."""
    return query


class FakeModel(Model):
    """Answers with fixed text after a short pause, or raises ``error``."""

    def __init__(self, text: str = "answer", delay: float = 0.05, error: Exception | None = None):
        self.text = text
        self.delay = delay
        self.error = error

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> Any:
        return {}

    def structured_output(self, *args: Any, **kwargs: Any):
        raise NotImplementedError

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        # The pause keeps both calls in flight at once in the concurrency test.
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockDelta": {"delta": {"text": self.text}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}


@pytest.fixture(autouse=True)
def empty_spec_cache(monkeypatch):
    monkeypatch.setattr(agents, "_SPEC_CACHE", {})


@pytest.fixture
def fake_tools(monkeypatch):
    """Replace the graph tools that agents hands to each specialist."""
    monkeypatch.setattr(agents, "MAINTENANCE_TOOLS", (graph_query_tool, vector_search_tool))
    monkeypatch.setattr(agents, "OPERATIONS_TOOLS", (graph_query_tool,))


def specialist_agent(supervisor: Agent, name: str) -> Agent:
    """Build the agent behind one of the supervisor's specialist tools."""
    return supervisor.tool_registry.registry[name]._build_agent()


def specialist_tool(model: Model) -> SpecialistTool:
    return SpecialistTool(
        MAINTENANCE_TOOL,
        "test specialist",
        lambda: Agent(model=model, tools=[], callback_handler=None),
    )


async def final_result(specialist: SpecialistTool, tool_use_id: str) -> dict[str, Any]:
    """Run one specialist call and return its tool result."""
    tool_use = {"toolUseId": tool_use_id, "name": MAINTENANCE_TOOL, "input": {"input": "q"}}
    result = None
    async for event in specialist.stream(tool_use, {}):
        if isinstance(event, ToolResultEvent):
            result = event.tool_result
    assert result is not None
    return result


def test_supervisor_has_both_specialist_tools(fake_tools):
    supervisor = build_supervisor(build_model(), SCHEMA)
    assert sorted(supervisor.tool_names) == sorted([MAINTENANCE_TOOL, OPERATIONS_TOOL])


def test_maintenance_gets_graph_query_and_manual_search(fake_tools):
    agent = specialist_agent(build_supervisor(FakeModel(), SCHEMA), MAINTENANCE_TOOL)
    assert sorted(agent.tool_names) == ["graph_query_tool", "vector_search_tool"]


def test_operations_gets_graph_query_only(fake_tools):
    agent = specialist_agent(build_supervisor(FakeModel(), SCHEMA), OPERATIONS_TOOL)
    assert agent.tool_names == ["graph_query_tool"]


def test_specialists_use_the_graph_package_tools_by_default():
    assert agents.MAINTENANCE_TOOLS is graph.MAINTENANCE_TOOLS
    assert agents.OPERATIONS_TOOLS is graph.OPERATIONS_TOOLS


@pytest.mark.parametrize("name", [MAINTENANCE_TOOL, OPERATIONS_TOOL])
def test_specialist_prompt_holds_the_schema(fake_tools, name):
    prompt = specialist_agent(build_supervisor(FakeModel(), SCHEMA), name).system_prompt
    assert SCHEMA in prompt
    assert "{schema}" not in prompt
    # The schema is in the prompt, so no schema or raw Cypher tool is named.
    assert "get_neo4j_schema" not in prompt
    assert "read_neo4j_cypher" not in prompt


def test_schema_braces_reach_the_prompt_unchanged(fake_tools):
    schema = "Aircraft {tail_number: STRING}"
    prompt = specialist_agent(build_supervisor(FakeModel(), schema), OPERATIONS_TOOL).system_prompt
    assert schema in prompt


def test_maintenance_prompt_asks_for_manual_document_ids(fake_tools):
    prompt = specialist_agent(build_supervisor(FakeModel(), SCHEMA), MAINTENANCE_TOOL).system_prompt
    assert "[Source: ...]" in prompt
    assert "vector_search_tool" in prompt


# A manual search for limits can rank a nearby table first, such as the
# A320 normal operating parameters above its EGT limits table. The
# OperatingLimit nodes hold each type's values directly.
def test_maintenance_prompt_gets_limit_values_from_the_graph(fake_tools):
    prompt = specialist_agent(build_supervisor(FakeModel(), SCHEMA), MAINTENANCE_TOOL).system_prompt
    assert "Limit values, such as a maximum EGT, are `OperatingLimit` nodes" in prompt
    assert "Get them with `graph_query_tool`" in prompt
    assert '"EGT operating limits" with\n   `aircraft_type` "B737-800"' in prompt


# One query for a fleet-wide procedure ranks chunks from every manual against
# each other, so one type's procedure can fall out of the top results.
def test_maintenance_prompt_searches_manuals_once_per_aircraft_type(fake_tools):
    prompt = specialist_agent(build_supervisor(FakeModel(), SCHEMA), MAINTENANCE_TOOL).system_prompt
    assert "A procedure question that names no aircraft type" in prompt
    assert "Call `vector_search_tool` once per aircraft type" in prompt
    assert "pass the\n   type as `aircraft_type`" in prompt


def test_operations_prompt_names_no_manual_search_tool(fake_tools):
    prompt = specialist_agent(build_supervisor(FakeModel(), SCHEMA), OPERATIONS_TOOL).system_prompt
    assert "vector_search_tool" not in prompt


def test_manual_questions_route_to_maintenance(fake_tools):
    assert "manuals" in MAINTENANCE_DESCRIPTION
    prompt = build_supervisor(FakeModel(), SCHEMA).system_prompt
    assert "If the question asks what a manual says" in prompt


# Memory stores no tool calls, so restored turns hold only text. The
# supervisor must not read a missing specialist call as no call.
def test_supervisor_prompt_says_restored_turns_hold_no_tool_calls(fake_tools):
    prompt = build_supervisor(build_model(), SCHEMA).system_prompt
    assert "Earlier turns restored from memory contain only user and assistant text" in prompt
    assert "does not mean no specialist ran" in prompt
    assert "call the specialist again rather than comment on it" in prompt


def test_every_specialist_tool_has_a_display_name():
    assert set(SPECIALIST_NAMES) == {MAINTENANCE_TOOL, OPERATIONS_TOOL}


def test_spec_matches_as_tool_input_schema():
    spec = specialist_tool(FakeModel()).tool_spec
    assert spec["name"] == MAINTENANCE_TOOL
    assert spec["inputSchema"]["json"]["required"] == ["input"]


def test_parallel_calls_to_one_specialist_both_succeed():
    # A single as_tool wrapper would fail the second call with
    # "already processing a request".
    specialist = specialist_tool(FakeModel(text="ok", delay=0.2))

    async def both():
        return await asyncio.gather(final_result(specialist, "a"), final_result(specialist, "b"))

    results = asyncio.run(both())
    assert [r["status"] for r in results] == ["success", "success"]
    assert all("ok" in r["content"][0]["text"] for r in results)


def test_each_call_builds_a_fresh_agent():
    built: list[Agent] = []
    model = FakeModel()

    def build() -> Agent:
        agent = Agent(model=model, tools=[], callback_handler=None)
        built.append(agent)
        return agent

    specialist = SpecialistTool(MAINTENANCE_TOOL, "test", build)
    asyncio.run(final_result(specialist, "a"))
    asyncio.run(final_result(specialist, "b"))
    # One agent for the spec, then one per call.
    assert len({id(a) for a in built}) == 3


def test_spec_agent_is_built_once_across_requests():
    built: list[Agent] = []
    model = FakeModel()

    def build() -> Agent:
        agent = Agent(model=model, tools=[], callback_handler=None)
        built.append(agent)
        return agent

    first = SpecialistTool(MAINTENANCE_TOOL, "test", build)
    second = SpecialistTool(MAINTENANCE_TOOL, "test", build)
    assert len(built) == 1
    assert second.tool_spec is first.tool_spec
    # A different description is a different spec.
    other = SpecialistTool(MAINTENANCE_TOOL, "other", build)
    assert len(built) == 2
    assert other.tool_spec["description"] == "other"


def test_supervisors_built_per_request_reuse_the_specs(monkeypatch, fake_tools):
    built: list[str] = []
    real_agent = agents.Agent

    def counting_agent(*args, **kwargs):
        built.append(kwargs.get("name", ""))
        return real_agent(*args, **kwargs)

    monkeypatch.setattr(agents, "Agent", counting_agent)
    model = FakeModel()
    build_supervisor(model, SCHEMA)
    build_supervisor(model, SCHEMA)
    # Two spec agents on the first request, then only the supervisors.
    assert sorted(built) == sorted(
        ["maintenance_agent", "operations_agent", "fleet_supervisor", "fleet_supervisor"]
    )


def test_specialist_error_text_is_generic(caplog):
    specialist = specialist_tool(FakeModel(error=RuntimeError("password=hunter2")))
    result = asyncio.run(final_result(specialist, "a"))
    assert result["status"] == "error"
    assert result["content"] == [{"text": SPECIALIST_ERROR}]
    assert "hunter2" in caplog.text
