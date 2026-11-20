"""
Sensor time-series generation with per-aircraft degradation profiles.

Each engine draws a random degradation slope from the model's range, scaled by
the operator's maintenance quality factor. The slope determines how fast the engine
degrades over the 90-day window. Higher slopes produce threshold exceedances that
then trigger correlated maintenance events in maintenance.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from .config import GeneratorConfig
from .fleet import AircraftNode, SystemNode
from .specs import ENGINE_SPECS, EngineSpec


@dataclass(frozen=True, slots=True)
class EngineSeries:
    """The EGT and vibration values written for one engine, spikes included.

    maintenance.py scans these same values, so every event traces back to
    readings that are in the graph.
    """

    egt: np.ndarray
    vib: np.ndarray


@dataclass
class DegradationProfile:
    egt_slope: float  # °C per operational hour
    vib_slope: float  # ips per operational hour
    # Fraction of readings that receive random anomaly spikes (0–1)
    anomaly_rate: float


def _draw_profile(
    spec: EngineSpec, degradation_multiplier: float, rng: np.random.Generator
) -> DegradationProfile:
    egt_slope = float(rng.uniform(*spec.egt_degradation_range)) * degradation_multiplier
    vib_slope = float(rng.uniform(*spec.vib_degradation_range)) * degradation_multiplier
    # Anomaly rate correlates loosely with degradation speed
    anomaly_rate = 0.003 + 0.015 * (degradation_multiplier - 0.75)
    return DegradationProfile(egt_slope=egt_slope, vib_slope=vib_slope, anomaly_rate=anomaly_rate)


def _timestamps(start: datetime, n_hours: int) -> list[str]:
    return [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S") for h in range(n_hours)]


def _add_spikes(
    values: np.ndarray, threshold: float, anomaly_rate: float, rng: np.random.Generator
) -> np.ndarray:
    """Randomly spike a fraction of readings above the warning threshold."""
    n = len(values)
    n_spikes = max(1, int(n * anomaly_rate))
    spike_idx = rng.choice(n, size=n_spikes, replace=False)
    # Spike amplitude: 0.5–2.5× the gap between current value and threshold
    gap = threshold - values[spike_idx]
    amplitude = rng.uniform(0.5, 2.5, size=n_spikes) * np.abs(gap)
    values = values.copy()
    values[spike_idx] += amplitude
    return values


def generate_engine_readings(
    aircraft: AircraftNode,
    system: SystemNode,
    config: GeneratorConfig,
    rng: np.random.Generator,
) -> tuple[EngineSeries, list[dict]]:
    """
    Generate sensor readings for one engine system.

    Returns the EGT and vibration series exactly as written, for the
    maintenance module to scan, and a flat list of reading dicts ready for
    CSV serialisation.
    """
    spec: EngineSpec = ENGINE_SPECS[aircraft.model]
    profile = _draw_profile(spec, aircraft.operator_profile.degradation_multiplier, rng)
    timestamps = _timestamps(config.start_date, config.n_hours)
    t = np.arange(config.n_hours, dtype=float)

    # Build per-sensor time series
    sensor_series: dict[str, np.ndarray] = {}
    series_by_type: dict[str, np.ndarray] = {}
    for sensor in system.sensors:
        if sensor.type == "EGT":
            base = spec.egt_baseline + profile.egt_slope * t
            noise = rng.normal(0, spec.egt_noise_std, config.n_hours)
            values = base + noise
            values = _add_spikes(values, spec.egt_warning, profile.anomaly_rate, rng)
        elif sensor.type == "Vibration":
            base = spec.vib_baseline + profile.vib_slope * t
            noise = rng.normal(0, spec.vib_noise_std, config.n_hours)
            values = base + noise
            values = _add_spikes(values, spec.vib_warning, profile.anomaly_rate, rng)
        elif sensor.type == "N1Speed":
            values = rng.normal(spec.n1_baseline, spec.n1_noise_std, config.n_hours)
        else:  # FuelFlow
            values = rng.normal(spec.fuel_baseline, spec.fuel_noise_std, config.n_hours)

        sensor_series[sensor.sensor_id] = values
        series_by_type[sensor.type] = values

    rows: list[dict] = []
    for sensor in system.sensors:
        values = sensor_series[sensor.sensor_id]
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

    return EngineSeries(egt=series_by_type["EGT"], vib=series_by_type["Vibration"]), rows
