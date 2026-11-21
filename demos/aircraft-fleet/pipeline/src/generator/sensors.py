"""
Sensor time-series generation with per-sensor degradation drift.

Each sensor draws a drift rate from its spec's range, scaled by the operator's
maintenance quality factor. The drift moves the value toward the bad side of
the sensor's bands over the generation window. Readings that cross the bands
then trigger correlated maintenance events in maintenance.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from .config import GeneratorConfig
from .fleet import AircraftNode, SystemNode
from .specs import Direction, SensorSpec, sensors_for

# Fraction of hours that spike past advisory on one sensor, at a degradation
# multiplier of 1.0. Avionics and Hydraulics drift never reaches advisory in
# 90 days, so their events come from spikes. Tuned once with the event
# probabilities in maintenance.py so the default run is mostly Engine events.
_SPIKE_RATE: dict[str, float] = {"Engine": 0.009, "Avionics": 0.013, "Hydraulics": 0.013}

# Mean overshoot past advisory, in band widths. One width carries a spike from
# advisory to caution, and two carry it to warning.
_OVERSHOOT_SCALE = 0.85


def _spike_rate(system_type: str, degradation_multiplier: float) -> float:
    """Fraction of readings that get a spike. It rises with degradation."""
    return _SPIKE_RATE.get(system_type, 0.0) * degradation_multiplier


def _timestamps(start: datetime, n_hours: int) -> list[str]:
    return [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S") for h in range(n_hours)]


def _overshoot(offsets: tuple[float, float, float], widths: np.ndarray) -> np.ndarray:
    """Map overshoots in band widths to distances from baseline toward the bad side.

    0 to 1 width lands in the advisory band, 1 to 2 in the caution band, and 2
    or more at or past warning, where the last band's width continues.
    """
    advisory, caution, warning = offsets
    return np.where(
        widths < 1,
        advisory + widths * (caution - advisory),
        np.where(
            widths < 2,
            caution + (widths - 1) * (warning - caution),
            warning + (widths - 2) * (warning - caution),
        ),
    )


def _add_spikes(
    values: np.ndarray, spec: SensorSpec, spike_rate: float, rng: np.random.Generator
) -> np.ndarray:
    """Push a fraction of readings past advisory, most of them only just past.

    A spike never makes a reading less severe than it already was.
    """
    n = len(values)
    n_spikes = int(rng.binomial(n, min(spike_rate, 1.0)))
    if n_spikes == 0:
        return values
    spike_idx = rng.choice(n, size=n_spikes, replace=False)
    distance = _overshoot(spec.offsets(), rng.exponential(_OVERSHOOT_SCALE, n_spikes))
    match spec.direction:
        case Direction.HIGH:
            sides = np.ones(n_spikes)
        case Direction.LOW:
            sides = -np.ones(n_spikes)
        case Direction.DEVIATION:
            sides = rng.choice((-1.0, 1.0), size=n_spikes)
    current = (values[spike_idx] - spec.baseline) * sides
    values = values.copy()
    values[spike_idx] = spec.baseline + sides * np.maximum(current, distance)
    return values


def _drift_sign(direction: Direction, rng: np.random.Generator) -> float:
    match direction:
        case Direction.HIGH:
            return 1.0
        case Direction.LOW:
            return -1.0
        case Direction.DEVIATION:
            return float(rng.choice((-1.0, 1.0)))


def _series(
    spec: SensorSpec,
    degradation_multiplier: float,
    spike_rate: float,
    n_hours: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return one sensor's hourly values: baseline, drift, noise, and spikes."""
    drift_per_day = float(rng.uniform(*spec.drift_per_day)) * degradation_multiplier
    slope = _drift_sign(spec.direction, rng) * drift_per_day / 24
    values = spec.baseline + slope * np.arange(n_hours, dtype=float)
    values = values + rng.normal(0, spec.noise_std, n_hours)
    values = _add_spikes(values, spec, spike_rate, rng)
    if spec.minimum is not None:
        values = np.maximum(values, spec.minimum)
    return values


def generate_system_readings(
    aircraft: AircraftNode,
    system: SystemNode,
    config: GeneratorConfig,
    rng: np.random.Generator,
) -> tuple[dict[str, np.ndarray], list[dict]]:
    """
    Generate hourly readings for every sensor on one system.

    Returns each sensor type's values exactly as written, for the maintenance
    module to scan, and a flat list of reading dicts ready for CSV
    serialisation.
    """
    specs = {spec.type: spec for spec in sensors_for(system.type, aircraft.model)}
    multiplier = aircraft.operator_profile.degradation_multiplier
    spike_rate = _spike_rate(system.type, multiplier)
    timestamps = _timestamps(config.start_date, config.n_hours)

    series_by_type: dict[str, np.ndarray] = {}
    rows: list[dict] = []
    for sensor in system.sensors:
        values = _series(specs[sensor.type], multiplier, spike_rate, config.n_hours, rng)
        series_by_type[sensor.type] = values
        # The reading number is the hour offset from the first timestamp.
        for h, (ts, val) in enumerate(zip(timestamps, values, strict=True)):
            rows.append(
                {
                    "reading_id": f"{sensor.sensor_id}-R{h:05d}",
                    "sensor_id": sensor.sensor_id,
                    "ts": ts,
                    "value": round(float(val), 5),
                }
            )

    return series_by_type, rows
