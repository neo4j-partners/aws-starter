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

# The sensors that maintenance.py scans get random spikes past caution.
_SPIKED_SENSORS = frozenset({"EGT", "Vibration"})


def _anomaly_rate(degradation_multiplier: float) -> float:
    """Fraction of readings that get a spike. It rises with degradation."""
    return 0.003 + 0.015 * (degradation_multiplier - 0.75)


def _timestamps(start: datetime, n_hours: int) -> list[str]:
    return [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S") for h in range(n_hours)]


def _add_spikes(
    values: np.ndarray, threshold: float, anomaly_rate: float, rng: np.random.Generator
) -> np.ndarray:
    """Randomly spike a fraction of readings above the threshold."""
    n = len(values)
    n_spikes = max(1, int(n * anomaly_rate))
    spike_idx = rng.choice(n, size=n_spikes, replace=False)
    # Spike amplitude: 0.5–2.5× the gap between current value and threshold
    gap = threshold - values[spike_idx]
    amplitude = rng.uniform(0.5, 2.5, size=n_spikes) * np.abs(gap)
    values = values.copy()
    values[spike_idx] += amplitude
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
    anomaly_rate: float,
    n_hours: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return one sensor's hourly values: baseline, drift, noise, and spikes."""
    drift_per_day = float(rng.uniform(*spec.drift_per_day)) * degradation_multiplier
    slope = _drift_sign(spec.direction, rng) * drift_per_day / 24
    values = spec.baseline + slope * np.arange(n_hours, dtype=float)
    values = values + rng.normal(0, spec.noise_std, n_hours)
    if spec.type in _SPIKED_SENSORS:
        values = _add_spikes(values, spec.bands.caution, anomaly_rate, rng)
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
    anomaly_rate = _anomaly_rate(multiplier)
    timestamps = _timestamps(config.start_date, config.n_hours)

    series_by_type: dict[str, np.ndarray] = {}
    rows: list[dict] = []
    for sensor in system.sensors:
        values = _series(specs[sensor.type], multiplier, anomaly_rate, config.n_hours, rng)
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
