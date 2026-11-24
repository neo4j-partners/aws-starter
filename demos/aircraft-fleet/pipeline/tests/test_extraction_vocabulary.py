"""The extraction prompt and schema name the fleet types from the generator specs."""

from __future__ import annotations

import re

import pytest

from generator import manuals
from generator.specs import COMPONENT_TYPES_BY_SYSTEM, COMPONENTS_BY_SYSTEM, SENSOR_TYPES
from populate_aircraft_db.pipeline import EXTRACTION_PROMPT
from populate_aircraft_db.schema import (
    OPERATING_LIMIT_REGIMES,
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
    assert not _missing_aliases(_rule(7))
    assert "Air Data Unit for ADC or ADIRU" in _rule(7)


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
    assert not _missing_aliases(component)
    system = _property_description("SystemReference", "systemType")
    assert system.split("exactly one of: ")[1].split(".")[0].split(", ") == list(
        COMPONENT_TYPES_BY_SYSTEM
    )
    parameter = _property_description("OperatingLimit", "parameterName")
    listed = parameter.split("for one: ")[1].split(". ")[0]
    assert listed.split(", ") == [sensor_type for sensor_type, _, _ in SENSOR_TYPES]


def _block(model: str, block_id: str) -> str:
    """Return the body of one generated block in a model's manual."""
    text = (manuals.MANUALS_DIR / manuals.MANUAL_FILES[model]).read_text(encoding="utf-8")
    return text.split(f"<!-- BEGIN GENERATED: {block_id} -->\n")[1].split("<!-- END")[0]


def _columns(table: str) -> list[str]:
    """Return a table's header cells after the first, without their notes."""
    header = table.splitlines()[0]
    return [re.sub(r" \(.*\)", "", cell.strip()) for cell in header.split("|")[2:-1]]


def _manual_regimes(model: str) -> list[str]:
    """Return the regimes one manual's limit tables use, in list order."""
    hard = re.findall(r"^\| EGT \(([^,)]+)", _block(model, "egt-limits"), re.MULTILINE)
    normal = [f"{column} Normal" for column in _columns(_block(model, "normal-parameters"))]
    assert _columns(_block(model, "quick-ref-engine")) == _columns(
        _block(model, "normal-parameters")
    )
    trend = re.findall(r"(Advisory|Caution|Warning) at", _block(model, "egt-trend-note"))
    vibration = re.findall(r"^\| (\w+) \|", _block(model, "vibration-bands"), re.MULTILINE)
    band = [level for level in vibration[1:] if level != "Normal"]
    for block_id in ("quick-ref-avionics", "quick-ref-hydraulics"):
        assert _columns(_block(model, block_id))[2:] == band
    return hard + normal + [f"Trend {level}" for level in trend] + band + ["All"]


@pytest.mark.parametrize("model", sorted(manuals.MANUAL_FILES))
def test_regimes_are_the_ones_the_manuals_limit_tables_use(model: str) -> None:
    regimes = _manual_regimes(model)
    # The A320 manual has no EGT (Start) row.
    assert [r for r in OPERATING_LIMIT_REGIMES if r != "Start" or "Start" in regimes] == regimes


def test_prompt_and_schema_list_the_same_regimes() -> None:
    listed = _rule(8).split("exactly one of ")[1].split(", and use the same")[0]
    assert listed.split(", ") == OPERATING_LIMIT_REGIMES
    regime = _property_description("OperatingLimit", "regime")
    assert regime.split("exactly one of: ")[1].split(". Use All")[0].split(", ") == (
        OPERATING_LIMIT_REGIMES
    )


def _limit_name(parameter: str, regime: str, aircraft_type: str) -> str:
    """Build a limit name the way rule 5 says: parameter, regime, aircraft type."""
    return f"{parameter} {regime} - {aircraft_type}"


def test_prompt_examples_name_limits_by_parameter_and_regime() -> None:
    examples = re.findall(r'"([^"]+ - [^"]+)" with', _rule(8))
    assert examples == [
        _limit_name("EGT", "Takeoff", "A320-200"),
        _limit_name("EGT", "Takeoff Normal", "A320-200"),
        _limit_name("Vibration N1", "Warning", "A220-300"),
    ]


@pytest.mark.parametrize("regime", ["Takeoff", "Max Continuous"])
def test_a_normal_range_name_differs_from_the_hard_limit_name(regime: str) -> None:
    assert f"{regime} Normal" in OPERATING_LIMIT_REGIMES
    hard = _limit_name("EGT", regime, "A220-300")
    normal = _limit_name("EGT", f"{regime} Normal", "A220-300")
    assert hard.lower() != normal.lower()


def test_each_regime_gives_a_parameter_its_own_limit_name() -> None:
    for sensor_type, _, _ in SENSOR_TYPES:
        names = {_limit_name(sensor_type, r, "A220-300").lower() for r in OPERATING_LIMIT_REGIMES}
        assert len(names) == len(OPERATING_LIMIT_REGIMES)


def test_prompt_takes_hard_limits_only_from_the_maximum_column() -> None:
    rule = _rule(8)
    assert "Emit an OperatingLimit only when the text gives a numeric minValue or maxValue" in (
        rule
    )
    assert "Takeoff, Max Continuous, and Start come only from the Operating Limits table" in rule
    assert "Set maxValue from its Maximum column" in rule
    assert "Normal Operating Parameters table and its Quick Reference" in rule


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
