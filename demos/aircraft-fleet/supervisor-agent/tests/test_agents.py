"""Supervisor wiring and SpecialistTool behavior, with a fake model."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from strands import Agent, tool
from strands.models import Model
from strands.types.events import ToolResultEvent

from core.agents import (
    MAINTENANCE_TOOL,
    OPERATIONS_TOOL,
    SPECIALIST_ERROR,
    SPECIALIST_NAMES,
    SpecialistTool,
    build_supervisor,
)
from core.model import build_model


@tool
def read_neo4j_cypher(query: str) -> str:
    """Stand-in for the Gateway read tool."""
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


def test_supervisor_has_both_specialist_tools():
    supervisor = build_supervisor(build_model(), [read_neo4j_cypher])
    assert sorted(supervisor.tool_names) == sorted([MAINTENANCE_TOOL, OPERATIONS_TOOL])


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


def test_specialist_error_text_is_generic(caplog):
    specialist = specialist_tool(FakeModel(error=RuntimeError("password=hunter2")))
    result = asyncio.run(final_result(specialist, "a"))
    assert result["status"] == "error"
    assert result["content"] == [{"text": SPECIALIST_ERROR}]
    assert "hunter2" in caplog.text
