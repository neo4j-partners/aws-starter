"""build_supervisor wires each specialist in as a tool. No model call is made."""

from strands import tool

from core.agents import MAINTENANCE_TOOL, OPERATIONS_TOOL, SPECIALIST_NAMES, build_supervisor
from core.model import build_model


@tool
def read_neo4j_cypher(query: str) -> str:
    """Stand-in for the Gateway read tool."""
    return query


def test_supervisor_has_both_specialist_tools():
    supervisor = build_supervisor(build_model(), [read_neo4j_cypher])
    assert sorted(supervisor.tool_names) == sorted([MAINTENANCE_TOOL, OPERATIONS_TOOL])


def test_each_call_builds_new_specialists():
    model = build_model()
    first = build_supervisor(model, [read_neo4j_cypher])
    second = build_supervisor(model, [read_neo4j_cypher])
    a = first.tool_registry.registry[MAINTENANCE_TOOL]
    b = second.tool_registry.registry[MAINTENANCE_TOOL]
    assert a is not b


def test_every_specialist_tool_has_a_display_name():
    assert set(SPECIALIST_NAMES) == {MAINTENANCE_TOOL, OPERATIONS_TOOL}
