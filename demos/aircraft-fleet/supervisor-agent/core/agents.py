"""Build the supervisor Agent and its specialist Agents.

The specialists become tools of the supervisor through ``Agent.as_tool``.
The tool descriptions drive routing, so they name each specialist's domain.

Build a new set of agents for each request. An agent wrapped by ``as_tool``
holds a lock while it runs, so two concurrent requests that shared one
specialist would get an error result instead of an answer.
"""

from collections.abc import Sequence
from typing import Any

from strands import Agent
from strands.models import Model
from strands.session import SessionManager

from core.prompts import (
    MAINTENANCE_SYSTEM_PROMPT,
    OPERATIONS_SYSTEM_PROMPT,
    SUPERVISOR_SYSTEM_PROMPT,
)

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
    "severity. Pass the user's full question."
)
OPERATIONS_DESCRIPTION = (
    "Answers questions about flight operations: flights, delays, delay causes, "
    "routes, airports, operators, schedules, and on-time performance. Also "
    "handles general questions such as the graph schema or simple counts. "
    "Pass the user's full question."
)


def build_supervisor(
    model: Model,
    specialist_tools: Sequence[Any],
    session_manager: SessionManager | None = None,
) -> Agent:
    """Build one supervisor with fresh Maintenance and Operations specialists.

    ``specialist_tools`` is the filtered Gateway tool list, shared by both
    specialists. ``session_manager`` attaches to the supervisor only.
    """
    maintenance = Agent(
        name="maintenance_agent",
        model=model,
        system_prompt=MAINTENANCE_SYSTEM_PROMPT,
        tools=list(specialist_tools),
        callback_handler=None,
    )
    operations = Agent(
        name="operations_agent",
        model=model,
        system_prompt=OPERATIONS_SYSTEM_PROMPT,
        tools=list(specialist_tools),
        callback_handler=None,
    )
    return Agent(
        name="fleet_supervisor",
        model=model,
        system_prompt=SUPERVISOR_SYSTEM_PROMPT,
        tools=[
            maintenance.as_tool(name=MAINTENANCE_TOOL, description=MAINTENANCE_DESCRIPTION),
            operations.as_tool(name=OPERATIONS_TOOL, description=OPERATIONS_DESCRIPTION),
        ],
        callback_handler=None,
        session_manager=session_manager,
    )
