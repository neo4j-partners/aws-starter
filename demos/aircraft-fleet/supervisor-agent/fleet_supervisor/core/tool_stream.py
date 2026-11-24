"""Surface individual tool results as they finish in the Strands stream."""

from collections.abc import AsyncIterator, Callable
from time import monotonic

from strands import Agent
from strands.middleware import ExecuteToolContext, ExecuteToolStage
from strands.types.events import ToolResultEvent, TypedEvent

TRACE_STATE_KEY = "fleet_ui_trace"
RESULT_EVENT_KEY = "fleet_tool_result"


async def _stream_result(
    context: ExecuteToolContext,
    next_handler: Callable[[ExecuteToolContext], AsyncIterator[TypedEvent]],
) -> AsyncIterator[TypedEvent]:
    start = monotonic()
    async for event in next_handler(context):
        if isinstance(event, ToolResultEvent) and not event.backgrounded:
            yield TypedEvent(
                {
                    RESULT_EVENT_KEY: event.tool_result,
                    "duration_ms": round((monotonic() - start) * 1000),
                }
            )
        yield event


def observe_tool_results(agent: Agent) -> None:
    """Emit each result without waiting for concurrent calls in the same turn."""
    agent.add_middleware(ExecuteToolStage, _stream_result)
