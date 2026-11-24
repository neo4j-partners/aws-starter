"""The extraction prompt and schema name the fleet types from the generator specs."""

from __future__ import annotations

import re

import pytest

from generator.specs import COMPONENT_TYPES_BY_SYSTEM, COMPONENTS_BY_SYSTEM
from populate_aircraft_db.pipeline import EXTRACTED_LABELS, EXTRACTION_PROMPT
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
    rule = _rule(6)
    listed = rule.split("listed for the part's system: ")[1].split(". Use these types")[0]
    assert _system_lists(listed) == COMPONENT_TYPES_BY_SYSTEM


# The aliases the prompt lists. Link-only aliases are left out to keep the
# prompt short; the join accepts them anyway.
PROMPT_ALIASES = {
    alias.lower()
    for specs in COMPONENTS_BY_SYSTEM.values()
    for spec in specs
    for alias in spec.aliases()
}


def _missing_aliases(text: str) -> set[str]:
    return {alias for alias in PROMPT_ALIASES if alias not in text.lower()}


def test_prompt_names_every_component_alias() -> None:
    assert not _missing_aliases(_rule(6))
    assert "Air Data Unit for ADC or ADIRU" in _rule(6)


def test_prompt_lists_every_system_type() -> None:
    listed = _rule(6).split("exactly one of ")[1].split(", and omit")[0]
    assert listed.split(", ") == list(COMPONENT_TYPES_BY_SYSTEM)


def test_prompt_example_uses_a_listed_component_type() -> None:
    example_types = re.findall(r'"componentType": "([^"]+)"', PROMPT)
    assert example_types
    assert all(t.lower() in SYSTEM_TYPE_BY_COMPONENT_TYPE for t in example_types)


def test_schema_descriptions_list_the_same_types() -> None:
    component = _property_description("ComponentReference", "componentType")
    listed = component.split("(")[1].split(")")[0]
    assert _system_lists(listed) == COMPONENT_TYPES_BY_SYSTEM
    assert not _missing_aliases(component)
    system = _property_description("SystemReference", "systemType")
    assert system.split("exactly one of: ")[1].split(".")[0].split(", ") == list(
        COMPONENT_TYPES_BY_SYSTEM
    )


def test_extraction_has_no_operating_limits() -> None:
    """The load writes the limits from the generator, so the LLM never extracts them."""
    schema = build_extraction_schema()
    assert "OperatingLimit" not in {node.label for node in schema.node_types}
    assert "HAS_LIMIT" not in {rel.label for rel in schema.relationship_types}
    assert all("OperatingLimit" not in (p.source, p.target) for p in schema.patterns)
    assert "OperatingLimit" not in EXTRACTED_LABELS
    assert "OperatingLimit" not in PROMPT
    assert "HAS_LIMIT" not in PROMPT


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
