"""Systems and components follow the manuals' names, and aliases resolve to types."""

from __future__ import annotations

import re

import pytest

from generator.config import GeneratorConfig
from generator.fleet import generate_fleet
from generator.specs import (
    COMPONENT_ALIASES,
    COMPONENT_TYPES_BY_SYSTEM,
    COMPONENTS_BY_SYSTEM,
    ComponentSpec,
    component_aliases,
)

ENGINE_TYPES = ["Fan Module", "HP Compressor", "HP Turbine", "Main Fuel Pump", "Thrust Bearing"]


@pytest.fixture(scope="module")
def fleet_by_model() -> dict[str, object]:
    fleet = generate_fleet(GeneratorConfig(n_aircraft=30, seed=42))
    return {aircraft.model: aircraft for aircraft in reversed(fleet)}


def _system(aircraft, index: int):
    return aircraft.systems[index - 1]


def test_system_names(fleet_by_model) -> None:
    a320 = fleet_by_model["A320-200"]
    assert [s.name for s in a320.systems] == [
        "V2500-A1 #1",
        "V2500-A1 #2",
        "Avionics",
        "Hydraulics",
    ]


def test_engine_components_keep_one_order_and_the_gearbox_is_a220_only(fleet_by_model) -> None:
    for model, aircraft in fleet_by_model.items():
        engine = _system(aircraft, 1)
        types = [c.type for c in engine.components]
        expected = ENGINE_TYPES + (["Reduction Gearbox"] if model == "A220-300" else [])
        assert types == expected, model
        ids = [c.component_id.rsplit("-", 1)[1] for c in engine.components]
        assert ids == [f"C{i:02d}" for i in range(1, len(expected) + 1)], model


@pytest.mark.parametrize(
    ("model", "system", "component", "name"),
    [
        ("B737-800", 3, "Air Data Unit", "ADC"),
        ("E190", 3, "Air Data Unit", "ADIRU"),
        ("A220-300", 3, "Navigation Receiver", "MMR"),
        ("A320-200", 3, "Navigation Receiver", "NAV"),
        ("A320-200", 1, "HP Turbine", "High-Pressure Turbine"),
        ("A321neo", 1, "Fan Module", "Fan Module (Carbon Fiber Composite)"),
        ("B737-800", 1, "Fan Module", "Fan Module"),
        ("E190", 4, "Hydraulic Pump", "Engine-Driven Pump"),
        ("B737-800", 4, "Hydraulic Pump", "Main Hydraulic Pump"),
        ("A220-300", 4, "Flight Control Actuator", "Electrohydraulic Servo Actuators"),
    ],
)
def test_components_carry_the_manual_name(
    fleet_by_model, model: str, system: int, component: str, name: str
) -> None:
    names = {c.type: c.name for c in _system(fleet_by_model[model], system).components}
    assert names[component] == name


def test_types_by_system_follow_the_component_specs() -> None:
    assert {
        system: [spec.type for spec in specs] for system, specs in COMPONENTS_BY_SYSTEM.items()
    } == COMPONENT_TYPES_BY_SYSTEM
    assert list(COMPONENT_TYPES_BY_SYSTEM) == ["Engine", "Avionics", "Hydraulics"]


@pytest.mark.parametrize(
    ("alias", "component_type"),
    [
        ("adiru", "Air Data Unit"),
        ("adc", "Air Data Unit"),
        ("high-pressure turbine", "HP Turbine"),
        ("hp turbine", "HP Turbine"),
        ("engine-driven pump", "Hydraulic Pump"),
        ("fms", "Flight Management System"),
    ],
)
def test_an_alias_resolves_to_its_type(alias: str, component_type: str) -> None:
    assert COMPONENT_ALIASES[alias] == component_type


def test_every_type_is_its_own_alias() -> None:
    for types in COMPONENT_TYPES_BY_SYSTEM.values():
        for component_type in types:
            assert COMPONENT_ALIASES[component_type.lower()] == component_type


def test_fuel_filter_and_nozzle_have_no_type() -> None:
    assert not {"fuel filter", "fuel nozzle", "filter", "nozzle"} & COMPONENT_ALIASES.keys()


def test_an_alias_of_two_types_raises_value_error() -> None:
    specs = {
        "Engine": (ComponentSpec("HP Turbine", names={"E190": "Turbine"}),),
        "Hydraulics": (ComponentSpec("Turbine Pump", names={"E190": "turbine"}),),
    }
    message = "alias 'turbine' names both 'HP Turbine' and 'Turbine Pump'"
    with pytest.raises(ValueError, match=f"^{re.escape(message)}"):
        component_aliases(specs)
