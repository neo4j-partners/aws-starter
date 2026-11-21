"""The extraction prompt and schema name the fleet types from the generator specs."""

from __future__ import annotations

import re

import pytest

from generator.specs import COMPONENT_TYPES_BY_SYSTEM, SENSOR_TYPES
from populate_aircraft_db.pipeline import EXTRACTION_PROMPT
from populate_aircraft_db.schema import (
    SYSTEM_TYPE_BY_COMPONENT_TYPE,
    build_extraction_schema,
    system_type_by_component_type,
)

PROMPT = EXTRACTION_PROMPT.format(schema="", examples="", text="")


def _rule(number: int) -> str:
    """Return the text of numbered prompt rule, up to the next blank line."""
    return PROMPT.split(f"\n{number}. ")[1].split("\n\n")[0]


def _property_description(label: str, prop: str) -> str:
    node = next(n for n in build_extraction_schema().node_types if n.label == label)
    return next(p.description for p in node.properties if p.name == prop)


def _system_lists(text: str) -> dict[str, list[str]]:
    """Parse "Engine: A, B; Avionics: C" into {"Engine": ["A", "B"], ...}."""
    pairs = re.findall(r"(\w+): ([^;.)]+)", text)
    return {system: items.split(", ") for system, items in pairs}


def test_prompt_lists_every_component_type_by_system() -> None:
    rule = _rule(7)
    listed = rule.split("listed for the part's system: ")[1].split(". Use the type")[0]
    assert _system_lists(listed) == COMPONENT_TYPES_BY_SYSTEM


def test_prompt_lists_every_system_type() -> None:
    listed = _rule(7).split("exactly one of ")[1].split(", and omit")[0]
    assert listed.split(", ") == list(COMPONENT_TYPES_BY_SYSTEM)


def test_prompt_sensor_names_are_the_fleet_sensor_types() -> None:
    listed = _rule(4).split("fleet sensor types ")[1].split(" when the limit")[0]
    assert listed.split(", ") == [sensor_type for sensor_type, _, _ in SENSOR_TYPES]
    assert "Use Vibration for every engine vibration limit" in _rule(4)


def test_prompt_example_uses_a_listed_component_type() -> None:
    example_types = re.findall(r'"componentType": "([^"]+)"', PROMPT)
    assert example_types
    assert all(t.lower() in SYSTEM_TYPE_BY_COMPONENT_TYPE for t in example_types)


def test_schema_descriptions_list_the_same_types() -> None:
    component = _property_description("ComponentReference", "componentType")
    listed = component.split("(")[1].split(")")[0]
    assert _system_lists(listed) == COMPONENT_TYPES_BY_SYSTEM
    system = _property_description("SystemReference", "systemType")
    assert system.split("exactly one of: ")[1].split(".")[0].split(", ") == list(
        COMPONENT_TYPES_BY_SYSTEM
    )
    parameter = _property_description("OperatingLimit", "parameterName")
    listed = parameter.split("for one: ")[1].split(". ")[0]
    assert listed.split(", ") == [sensor_type for sensor_type, _, _ in SENSOR_TYPES]


def test_each_component_type_maps_to_its_system() -> None:
    expected = {
        component.lower(): system
        for system, components in COMPONENT_TYPES_BY_SYSTEM.items()
        for component in components
    }
    assert expected == SYSTEM_TYPE_BY_COMPONENT_TYPE


@pytest.mark.parametrize(
    ("components_by_system", "message"),
    [
        pytest.param(
            {"Engine": ["Pump"], "Hydraulics": ["pump"]},
            "component type 'pump' is listed under 'Engine' and 'Hydraulics'; "
            "a component type must belong to one system type",
            id="two-systems",
        ),
        pytest.param(
            {"Engine": ["Pump", "PUMP"]},
            "component type 'PUMP' is listed twice under 'Engine', ignoring case; "
            "a component type must be listed once",
            id="one-system",
        ),
    ],
)
def test_a_component_type_in_two_places_raises_value_error(
    components_by_system: dict[str, list[str]], message: str
) -> None:
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        system_type_by_component_type(components_by_system)
