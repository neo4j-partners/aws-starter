"""Every system carries its own sensors, with realistic units, bands, and readings."""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

import pytest

from generator.config import GeneratorConfig
from generator.fleet import generate_fleet
from generator.main import generate
from generator.specs import (
    ENGINE_SPECS,
    SENSOR_TYPES,
    Bands,
    Direction,
    SensorSpec,
    sensors_for,
)

MODELS = list(ENGINE_SPECS)

SENSORS_BY_SYSTEM = {
    "Engine": ["EGT", "Vibration", "N1Speed", "FuelFlow"],
    "Avionics": ["BusVoltage", "AirDataDisagree"],
    "Hydraulics": ["HydPressure", "HydQuantity"],
}

UNITS = {
    "EGT": "°C",
    "Vibration": "ips",
    "N1Speed": "%",
    "FuelFlow": "kg/s",
    "BusVoltage": "V DC",
    "AirDataDisagree": "kt",
    "HydPressure": "psi",
    "HydQuantity": "%",
}

# Design table: EGT base / advisory / caution / warning, vibration the same,
# then cruise N1 and cruise fuel flow.
ENGINE_TABLE = {
    "B737-800": ((658, 678, 688, 698), (0.8, 2.0, 3.5, 4.5), 88, 0.36),
    "A320-200": ((560, 580, 590, 600), (0.8, 2.0, 3.5, 5.0), 87, 0.34),
    "A321neo": ((634, 654, 664, 674), (0.7, 2.0, 3.0, 4.0), 86, 0.38),
    "E190": ((641, 661, 671, 681), (0.8, 2.0, 3.0, 4.0), 87, 0.27),
    "A220-300": ((625, 645, 655, 665), (0.6, 1.5, 2.5, 3.5), 85, 0.28),
}


def _sensor(system_type: str, model: str, sensor_type: str) -> SensorSpec:
    return {s.type: s for s in sensors_for(system_type, model)}[sensor_type]


def _band_values(spec: SensorSpec) -> tuple[float, float, float, float]:
    return (spec.baseline, spec.bands.advisory, spec.bands.caution, spec.bands.warning)


def test_every_aircraft_has_twelve_sensors_on_their_systems() -> None:
    for aircraft in generate_fleet(GeneratorConfig(n_aircraft=30, seed=42)):
        by_system = [(s.type, [sensor.type for sensor in s.sensors]) for s in aircraft.systems]
        assert by_system == [
            ("Engine", SENSORS_BY_SYSTEM["Engine"]),
            ("Engine", SENSORS_BY_SYSTEM["Engine"]),
            ("Avionics", SENSORS_BY_SYSTEM["Avionics"]),
            ("Hydraulics", SENSORS_BY_SYSTEM["Hydraulics"]),
        ], aircraft.aircraft_id
        sensor_ids = [sensor.sensor_id for s in aircraft.systems for sensor in s.sensors]
        assert len(set(sensor_ids)) == 12


def test_sensor_units_are_realistic() -> None:
    for aircraft in generate_fleet(GeneratorConfig(n_aircraft=30, seed=42)):
        for system in aircraft.systems:
            for sensor in system.sensors:
                assert sensor.unit == UNITS[sensor.type], sensor.sensor_id


def test_sensor_types_list_every_system_sensor_once() -> None:
    assert [t for t, _, _ in SENSOR_TYPES] == [
        t for types in SENSORS_BY_SYSTEM.values() for t in types
    ]
    assert {t: unit for t, _, unit in SENSOR_TYPES} == UNITS


def test_sensor_name_and_unit_agree_across_models() -> None:
    for system_type in SENSORS_BY_SYSTEM:
        for sensor_type, name, unit in SENSOR_TYPES:
            specs = [
                s
                for model in MODELS
                for s in sensors_for(system_type, model)
                if s.type == sensor_type
            ]
            assert all((s.name, s.unit) == (name, unit) for s in specs), sensor_type


@pytest.mark.parametrize("model", MODELS)
def test_engine_bands_follow_the_design_table(model: str) -> None:
    egt, vib, n1_cruise, fuel_cruise = ENGINE_TABLE[model]
    assert _band_values(_sensor("Engine", model, "EGT")) == egt
    assert _band_values(_sensor("Engine", model, "Vibration")) == vib

    n1 = _sensor("Engine", model, "N1Speed")
    assert n1.direction is Direction.DEVIATION
    assert _band_values(n1) == (n1_cruise, 2, 4, 6)

    fuel = _sensor("Engine", model, "FuelFlow")
    assert fuel.direction is Direction.DEVIATION
    assert fuel.baseline == fuel_cruise
    offsets = (fuel.bands.advisory, fuel.bands.caution, fuel.bands.warning)
    assert offsets == pytest.approx(tuple(fuel_cruise * p for p in (0.08, 0.15, 0.25)))


@pytest.mark.parametrize("model", MODELS)
def test_hydraulics_and_avionics_bands(model: str) -> None:
    advisory = 2900 if model == "A321neo" else 2800
    pressure = _sensor("Hydraulics", model, "HydPressure")
    assert pressure.direction is Direction.LOW
    assert _band_values(pressure) == (3000, advisory, 2600, 2400)

    quantity = _sensor("Hydraulics", model, "HydQuantity")
    assert quantity.direction is Direction.LOW
    assert _band_values(quantity) == (90, 70, 60, 50)

    voltage = _sensor("Avionics", model, "BusVoltage")
    assert voltage.direction is Direction.LOW
    assert _band_values(voltage) == (28.0, 26.0, 25.0, 24.0)

    disagree = _sensor("Avionics", model, "AirDataDisagree")
    assert disagree.direction is Direction.HIGH
    assert _band_values(disagree) == (0.5, 3, 5, 8)


@pytest.mark.parametrize(
    ("direction", "baseline", "bands"),
    [
        (Direction.HIGH, 10.0, Bands(9.0, 12.0, 13.0)),
        (Direction.HIGH, 10.0, Bands(11.0, 13.0, 12.0)),
        (Direction.LOW, 10.0, Bands(11.0, 8.0, 7.0)),
        (Direction.LOW, 10.0, Bands(9.0, 7.0, 8.0)),
        (Direction.DEVIATION, 10.0, Bands(0.0, 1.0, 2.0)),
        (Direction.DEVIATION, 10.0, Bands(1.0, 3.0, 2.0)),
    ],
)
def test_out_of_order_bands_are_rejected(
    direction: Direction, baseline: float, bands: Bands
) -> None:
    with pytest.raises(ValueError, match="bands"):
        SensorSpec(
            type="T",
            name="Test",
            unit="u",
            baseline=baseline,
            noise_std=0.1,
            drift_fraction=(0.0, 0.1),
            direction=direction,
            bands=bands,
        )


def test_drift_range_must_be_ordered_and_not_negative() -> None:
    for drift in [(0.2, 0.1), (-0.1, 0.1)]:
        with pytest.raises(ValueError, match="drift"):
            SensorSpec(
                type="T",
                name="Test",
                unit="u",
                baseline=10.0,
                noise_std=0.1,
                drift_fraction=drift,
                direction=Direction.HIGH,
                bands=Bands(11.0, 12.0, 13.0),
            )


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def short_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("sensors")
    generate(aircraft=5, airports=40, days=3, seed=42, output=output)
    return output


def test_every_sensor_reads_hourly(short_run: Path) -> None:
    sensors = _rows(short_run / "nodes_sensors.csv")
    assert len(sensors) == 5 * 12
    counts: dict[str, int] = {}
    for r in _rows(short_run / "nodes_readings.csv"):
        counts[r["sensor_id"]] = counts.get(r["sensor_id"], 0) + 1
    assert counts == {s[":ID(Sensor)"]: 3 * 24 for s in sensors}


def test_readings_start_on_the_normal_side_of_advisory(short_run: Path) -> None:
    model = {r[":ID(Aircraft)"]: r["model"] for r in _rows(short_run / "nodes_aircraft.csv")}
    systems = {r[":ID(System)"]: r for r in _rows(short_run / "nodes_systems.csv")}
    values: dict[str, list[float]] = {}
    for r in _rows(short_run / "nodes_readings.csv"):
        values.setdefault(r["sensor_id"], []).append(float(r["value"]))

    for sensor in _rows(short_run / "nodes_sensors.csv"):
        system = systems[sensor["system_id"]]
        spec = _sensor(system["type"], model[system["aircraft_id"]], sensor["type"])
        # Drift spreads over the whole window, however short, so only the
        # first hours sit near baseline.
        median = statistics.median(values[sensor[":ID(Sensor)"]][:6])
        match spec.direction:
            case Direction.HIGH:
                assert median < spec.bands.advisory, sensor
            case Direction.LOW:
                assert median > spec.bands.advisory, sensor
            case Direction.DEVIATION:
                assert abs(median - spec.baseline) < spec.bands.advisory, sensor
        if sensor["type"] == "AirDataDisagree":
            assert min(values[sensor[":ID(Sensor)"]]) >= 0.0, sensor
