"""Event severity follows the trigger reading's band, and faults follow their routes."""

from __future__ import annotations

import csv
import random
from collections import Counter
from datetime import datetime
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from generator.config import GeneratorConfig
from generator.fleet import AircraftNode, generate_fleet
from generator.main import generate
from generator.maintenance import MaintenanceEvent, generate_maintenance_events
from generator.sensors import generate_system_readings
from generator.specs import (
    COMPONENTS_BY_SYSTEM,
    CORRECTIVE_ACTIONS,
    ENGINE_SPECS,
    SYSTEM_SENSORS,
    Bands,
    Direction,
    FaultRoute,
    SensorSpec,
    sensors_for,
)

SEED = 42
# The manuals' historic MINOR/MAJOR/CRITICAL shares, in percent.
TARGET_MIX = {"MINOR": 52, "MAJOR": 31, "CRITICAL": 17}
SEVERITY_BY_LEVEL = {1: "MINOR", 2: "MAJOR", 3: "CRITICAL"}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def default_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The default dataset: 30 aircraft over 90 days."""
    output = tmp_path_factory.mktemp("default")
    generate(aircraft=30, airports=40, days=90, seed=SEED, output=output)
    return output


@pytest.fixture(scope="module")
def in_memory() -> list[tuple[AircraftNode, dict[str, dict[str, np.ndarray]], MaintenanceEvent]]:
    """Every event of a default-size fleet, with the series it was scanned from."""
    config = GeneratorConfig(n_aircraft=30, n_days=90, seed=SEED)
    rng_np = np.random.default_rng(SEED)
    rng = random.Random(SEED)
    counter = [0]
    out = []
    for aircraft in generate_fleet(config):
        series = {
            s.system_id: generate_system_readings(aircraft, s, config, rng_np)[0]
            for s in aircraft.systems
        }
        for event in generate_maintenance_events(aircraft, series, config, counter, rng):
            out.append((aircraft, series, event))
    return out


def _level(spec: SensorSpec, value: float) -> tuple[int, Direction]:
    """Band level and side of a value, compared with absolute thresholds."""
    b = spec.bands
    match spec.direction:
        case Direction.HIGH:
            return sum(value >= t for t in (b.advisory, b.caution, b.warning)), Direction.HIGH
        case Direction.LOW:
            return sum(value <= t for t in (b.advisory, b.caution, b.warning)), Direction.LOW
        case Direction.DEVIATION:
            if value >= spec.baseline:
                limits = [spec.baseline + o for o in (b.advisory, b.caution, b.warning)]
                return sum(value >= t for t in limits), Direction.HIGH
            limits = [spec.baseline - o for o in (b.advisory, b.caution, b.warning)]
            return sum(value <= t for t in limits), Direction.LOW


def test_event_severity_is_exactly_the_band_of_its_trigger_reading(in_memory) -> None:
    assert len(in_memory) > 100
    for aircraft, series, event in in_memory:
        system = next(s for s in aircraft.systems if s.system_id == event.row["system_id"])
        sensor = next(s for s in system.sensors if s.sensor_id == event.sensor_id)
        spec = {s.type: s for s in sensors_for(system.type, aircraft.model)}[sensor.type]
        hour = int(
            (
                datetime.fromisoformat(event.row["reported_at"]) - datetime(2024, 7, 1)
            ).total_seconds()
            // 3600
        )
        value = series[system.system_id][sensor.type][hour]
        level, side = _level(spec, value)
        assert level >= 1, event
        assert event.row["severity"] == SEVERITY_BY_LEVEL[level], (event, value)

        routes = [r for r in spec.faults if r.side is side]
        assert event.row["fault"] in {r.fault for r in routes}, (event, side)
        component = next(
            c for c in system.components if c.component_id == event.row["component_id"]
        )
        allowed = {t for r in routes if r.fault == event.row["fault"] for t in r.components}
        assert component.type in allowed, (event, component.type)


def test_severity_mix_is_near_the_historic_mix(default_run: Path) -> None:
    counts = Counter(e["severity"] for e in _rows(default_run / "nodes_maintenance.csv"))
    total = sum(counts.values())
    for severity, target in TARGET_MIX.items():
        assert abs(100 * counts[severity] / total - target) <= 8, counts
    assert counts["MINOR"] == max(counts.values()), counts


def test_event_volume_is_mostly_engine(default_run: Path) -> None:
    system_type = {r[":ID(System)"]: r["type"] for r in _rows(default_run / "nodes_systems.csv")}
    events = _rows(default_run / "nodes_maintenance.csv")
    assert 180 <= len(events) <= 300, len(events)
    by_type = Counter(system_type[e["system_id"]] for e in events)
    assert by_type["Engine"] / len(events) > 0.5, by_type
    assert by_type["Avionics"] > 0 and by_type["Hydraulics"] > 0, by_type


def test_every_fault_occurs(default_run: Path) -> None:
    faults = {e["fault"] for e in _rows(default_run / "nodes_maintenance.csv")}
    assert faults == set(CORRECTIVE_ACTIONS)


def test_events_of_one_fault_on_one_system_are_72_hours_apart(default_run: Path) -> None:
    times: dict[tuple[str, str], list[datetime]] = {}
    for e in _rows(default_run / "nodes_maintenance.csv"):
        times.setdefault((e["system_id"], e["fault"]), []).append(
            datetime.fromisoformat(e["reported_at"])
        )
    for key, stamps in times.items():
        stamps.sort()
        gaps = [(b - a).total_seconds() / 3600 for a, b in pairwise(stamps)]
        assert all(g >= 72 for g in gaps), (key, gaps)


def test_every_bad_side_has_a_route_to_a_component_on_every_model() -> None:
    for system_type, by_model in SYSTEM_SENSORS.items():
        for model, specs in by_model.items():
            types = {c.type for c in COMPONENTS_BY_SYSTEM[system_type] if c.fits(model)}
            for spec in specs:
                sides = (
                    {Direction.HIGH, Direction.LOW}
                    if spec.direction is Direction.DEVIATION
                    else {spec.direction}
                )
                assert {r.side for r in spec.faults} == sides, (model, spec.type)
                for route in spec.faults:
                    assert route.fault in CORRECTIVE_ACTIONS, route
                    assert set(route.components) & types, (model, spec.type, route)


def test_bearing_wear_reaches_the_gearbox_only_on_the_a220() -> None:
    for model in ENGINE_SPECS:
        vib = {s.type: s for s in sensors_for("Engine", model)}["Vibration"]
        bearing = next(r for r in vib.faults if r.fault == "Bearing wear")
        assert "Reduction Gearbox" in bearing.components
    assert not any(
        c.type == "Reduction Gearbox" and c.fits(m)
        for c in COMPONENTS_BY_SYSTEM["Engine"]
        for m in ENGINE_SPECS
        if m != "A220-300"
    )


@pytest.mark.parametrize(
    ("direction", "side"),
    [(Direction.HIGH, Direction.LOW), (Direction.LOW, Direction.HIGH)],
)
def test_route_side_must_match_the_sensor_direction(direction: Direction, side: Direction) -> None:
    baseline, bands = (10.0, Bands(11.0, 12.0, 13.0))
    if direction is Direction.LOW:
        bands = Bands(9.0, 8.0, 7.0)
    with pytest.raises(ValueError, match="side"):
        SensorSpec(
            type="T",
            name="Test",
            unit="u",
            baseline=baseline,
            noise_std=0.1,
            drift_per_day=(0.0, 0.1),
            direction=direction,
            bands=bands,
            faults=(FaultRoute("Leak", side, ("Hydraulic Pump",), 1.0),),
        )


@pytest.mark.parametrize(
    ("weight", "message"),
    [
        pytest.param(-0.5, "weight -0.5 is negative", id="negative"),
        pytest.param(float("nan"), "weight nan is not finite", id="nan"),
        pytest.param(float("inf"), "weight inf is not finite", id="inf"),
    ],
)
def test_an_invalid_route_weight_raises_value_error(weight: float, message: str) -> None:
    with pytest.raises(ValueError, match=f"^fault route 'Leak': {message}$"):
        FaultRoute("Leak", Direction.HIGH, ("Hydraulic Pump",), weight)


def test_a_side_whose_route_weights_sum_to_zero_raises_value_error() -> None:
    # The high side is fine. The low side's only route has weight 0, so a
    # low-side crossing could never pick a route.
    routes = (
        FaultRoute("Leak", Direction.HIGH, ("Hydraulic Pump",), 1.0),
        FaultRoute("Leak", Direction.LOW, ("Hydraulic Pump",), 0.0),
    )
    with pytest.raises(
        ValueError,
        match="^sensor 'T': low route weights sum to 0; at least one must be positive$",
    ):
        SensorSpec(
            type="T",
            name="Test",
            unit="u",
            baseline=10.0,
            noise_std=0.1,
            drift_per_day=(0.0, 0.1),
            direction=Direction.DEVIATION,
            bands=Bands(1.0, 2.0, 3.0),
            faults=routes,
        )
