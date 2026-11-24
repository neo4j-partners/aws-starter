"""Build the supervisor Agent and its specialist tools.

Each specialist is a :class:`SpecialistTool`. The tool descriptions drive
routing, so they name each specialist's domain. Maintenance gets the graph
query and manual search tools, and Operations gets the graph query tool. Both
specialist prompts hold the live graph schema.

A specialist ``Agent`` serves one call at a time: ``Agent.as_tool`` holds a
lock while the agent runs and fails a second call with "already processing a
request". The supervisor runs tool calls concurrently, so it can call the same
specialist twice in one turn. ``SpecialistTool`` builds a fresh ``Agent`` for
every call, so parallel calls never share one.
"""

import logging
from collections.abc import Callable, Sequence
from typing import Any

from strands import Agent
from strands.models import Model
from strands.session import SessionManager
from strands.types.events import ToolResultEvent
from strands.types.tools import AgentTool, ToolGenerator, ToolSpec, ToolUse

from fleet_supervisor.core.graph import MAINTENANCE_TOOLS, OPERATIONS_TOOLS
from fleet_supervisor.core.prompts import (
    MAINTENANCE_SYSTEM_PROMPT_TEMPLATE,
    OPERATIONS_SYSTEM_PROMPT_TEMPLATE,
    SUPERVISOR_SYSTEM_PROMPT,
)
from fleet_supervisor.core.tool_stream import TRACE_STATE_KEY, observe_tool_results

logger = logging.getLogger(__name__)

MAINTENANCE_TOOL = "maintenance_specialist"
OPERATIONS_TOOL = "operations_specialist"

# Supervisor tool name to the display name sent in ``agent`` events.
SPECIALIST_NAMES = {
    MAINTENANCE_TOOL: "Maintenance Agent",
    OPERATIONS_TOOL: "Operations Agent",
}

MAINTENANCE_DESCRIPTION = (
    "Answers questions about aircraft maintenance and reliability: maintenance "
    "events, faults, failures, components, systems, sensors, readings, and "
    "severity. Also answers questions about the maintenance manuals, such as "
    "procedures, troubleshooting steps, and limits, and cites the manual "
    "document IDs. Pass a self-contained question that resolves references "
    "from the conversation."
)
OPERATIONS_DESCRIPTION = (
    "Answers questions about flight operations: flights, delays, delay causes, "
    "routes, airports, operators, schedules, and on-time performance. Also "
    "handles general questions such as the graph schema or simple counts. "
    "Pass a self-contained question that resolves references from the conversation."
)

# Sent to the supervisor model in place of a specialist's error text. The
# error text can hold exception details, and the model may repeat it to the
# user. The details go to the server log instead.
SPECIALIST_ERROR = "The specialist could not answer this question."

# ``as_tool``'s spec depends only on the tool name and description, and the
# supervisor is built per request. So each spec is taken from Strands once,
# keyed by name and description, and reused. Two threads that miss together
# both store the same value.
_SPEC_CACHE: dict[tuple[str, str], ToolSpec] = {}


def _as_tool_spec(name: str, description: str, build_agent: Callable[[], Agent]) -> ToolSpec:
    key = (name, description)
    if (spec := _SPEC_CACHE.get(key)) is None:
        spec = build_agent().as_tool(name=name, description=description).tool_spec
        _SPEC_CACHE[key] = spec
    return spec


class SpecialistTool(AgentTool):
    """Expose a specialist as a supervisor tool, with a fresh Agent per call.

    Each call wraps a new Agent with ``Agent.as_tool`` and streams through
    it, so the client still receives the specialist's events. Error results
    are replaced with :data:`SPECIALIST_ERROR`.
    """

    def __init__(self, name: str, description: str, build_agent: Callable[[], Agent]) -> None:
        super().__init__()
        self._name = name
        self._description = description
        self._build_agent = build_agent
        # Take the spec from Strands so the input schema matches ``as_tool``.
        self._spec = _as_tool_spec(name, description, build_agent)

    def _wrap(self, agent: Agent) -> AgentTool:
        return agent.as_tool(name=self._name, description=self._description)

    @property
    def tool_name(self) -> str:
        return self._name

    @property
    def tool_spec(self) -> ToolSpec:
        return self._spec

    @property
    def tool_type(self) -> str:
        return "agent"

    async def stream(
        self, tool_use: ToolUse, invocation_state: dict[str, Any], **kwargs: Any
    ) -> ToolGenerator:
        agent = self._build_agent()
        if invocation_state.get(TRACE_STATE_KEY):
            observe_tool_results(agent)
        inner = self._wrap(agent)
        async for event in inner.stream(tool_use, invocation_state, **kwargs):
            if isinstance(event, ToolResultEvent) and event.tool_result["status"] == "error":
                logger.warning(
                    "Specialist %s failed (tool_use_id=%s): %s",
                    self._name,
                    event.tool_use_id,
                    event.tool_result.get("content"),
                )
                yield ToolResultEvent(
                    {**event.tool_result, "content": [{"text": SPECIALIST_ERROR}]},
                    event.exception,
                )
            else:
                yield event


def build_supervisor(
    model: Model,
    schema: str,
    session_manager: SessionManager | None = None,
) -> Agent:
    """Build one supervisor with its Maintenance and Operations specialist tools.

    ``schema`` is the live graph schema text, formatted into both specialist
    prompts. ``session_manager`` attaches to the supervisor only.
    """

    def specialist(name: str, template: str, tools: Sequence[Any]) -> Callable[[], Agent]:
        system_prompt = template.format(schema=schema)
        return lambda: Agent(
            name=name,
            model=model,
            system_prompt=system_prompt,
            tools=list(tools),
            callback_handler=None,
        )

    return Agent(
        name="fleet_supervisor",
        model=model,
        system_prompt=SUPERVISOR_SYSTEM_PROMPT,
        tools=[
            SpecialistTool(
                MAINTENANCE_TOOL,
                MAINTENANCE_DESCRIPTION,
                specialist(
                    "maintenance_agent", MAINTENANCE_SYSTEM_PROMPT_TEMPLATE, MAINTENANCE_TOOLS
                ),
            ),
            SpecialistTool(
                OPERATIONS_TOOL,
                OPERATIONS_DESCRIPTION,
                specialist("operations_agent", OPERATIONS_SYSTEM_PROMPT_TEMPLATE, OPERATIONS_TOOLS),
            ),
        ],
        callback_handler=None,
        session_manager=session_manager,
    )
