"""Drift ends the window near warning, and spikes stay within one band width of it.

The tests build sensor series directly, for every model, sensor, and
operator, so the most degraded operator is always in the sample.
"""

from __future__ import annotations

import numpy as np
import pytest

from generator.sensors import _series, _spike_rate
from generator.specs import OPERATORS, SYSTEM_SENSORS, Direction, SensorSpec

SEEDS = (42, 7, 11)
WINDOWS = (90, 365)
UNITS = 10
# The worst unit may end a little past warning from noise and day-to-day spread.
END_TOLERANCE = 0.05
# Readings may sit this many noise standard deviations past a limit.
NOISE_SIGMAS = 5


def _toward_bad_side(spec: SensorSpec, values: np.ndarray) -> np.ndarray:
    """Distance from baseline toward the bad side. Deviations count either way."""
    match spec.direction:
        case Direction.HIGH:
            return values - spec.baseline
        case Direction.LOW:
            return spec.baseline - values
        case Direction.DEVIATION:
            return np.abs(values - spec.baseline)


def _all_series(days: int, seed: int):
    """Yield (system type, spec, values) for every model, sensor, and operator."""
    rng = np.random.default_rng(seed)
    for system_type, by_model in SYSTEM_SENSORS.items():
        for specs in by_model.values():
            for spec in specs:
                for operator in OPERATORS:
                    multiplier = operator.degradation_multiplier
                    rate = _spike_rate(system_type, multiplier)
                    for _ in range(UNITS):
                        yield system_type, spec, _series(spec, multiplier, rate, days * 24, rng)


def _worst_end_drift(days: int) -> dict[tuple[str, str], float]:
    """Each sensor's largest end-of-window drift, as a share of the warning gap.

    The median of the last day's readings sets aside noise and spikes.
    """
    worst: dict[tuple[str, str], float] = {}
    for seed in SEEDS:
        for system_type, spec, values in _all_series(days, seed):
            gap = spec.offsets()[2]
            end = float(np.median(_toward_bad_side(spec, values[-24:]))) / gap
            key = (system_type, spec.type)
            worst[key] = max(worst.get(key, 0.0), end)
    return worst


@pytest.fixture(scope="module")
def worst_by_window() -> dict[int, dict[tuple[str, str], float]]:
    return {days: _worst_end_drift(days) for days in WINDOWS}


@pytest.mark.parametrize("days", WINDOWS)
def test_the_most_degraded_unit_ends_the_window_near_warning(worst_by_window, days: int) -> None:
    for key, share in worst_by_window[days].items():
        assert share <= 1 + END_TOLERANCE, (days, key, share)


def test_a_year_drifts_no_further_than_ninety_days(worst_by_window) -> None:
    short, year = worst_by_window[90], worst_by_window[365]
    for key in short:
        assert year[key] <= short[key] + END_TOLERANCE, (key, short[key], year[key])


def test_engine_drift_reaches_warning_for_the_worst_operator(worst_by_window) -> None:
    # Drift, not only spikes, drives the most degraded engines to warning.
    for days in WINDOWS:
        for sensor in ("EGT", "Vibration"):
            assert worst_by_window[days][("Engine", sensor)] >= 0.9, (days, sensor)


@pytest.mark.parametrize("days", WINDOWS)
def test_readings_stay_within_physical_bounds(days: int) -> None:
    for seed in SEEDS:
        for _, spec, values in _all_series(days, seed):
            match spec.type:
                case "HydQuantity":
                    assert values.min() >= 0 and values.max() <= 100, (seed, spec.type)
                case "HydPressure" | "BusVoltage":
                    assert values.min() >= 0, (seed, spec.type)
            _, caution, warning = spec.offsets()
            limit = warning + (warning - caution) + NOISE_SIGMAS * spec.noise_std
            farthest = float(_toward_bad_side(spec, values).max())
            assert farthest <= limit, (seed, days, spec.type, farthest, limit)
