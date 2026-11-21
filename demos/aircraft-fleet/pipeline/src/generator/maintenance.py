"""
Correlated maintenance event generation.

Events are triggered probabilistically when engine EGT and vibration readings
cross their model's caution and warning bands. The fault type is determined by which sensor
crossed its threshold, and severity follows from how far above the threshold it went.

This produces the causal signal the GDS algorithms need: aircraft with steeper
degradation slopes accumulate more events and form distinct kNN/Louvain clusters.
"""

from __future__ import annotations

import random
from datetime import timedelta

import numpy as np

from .config import GeneratorConfig
from .fleet import AircraftNode, ComponentNode, SystemNode
from .specs import CORRECTIVE_ACTIONS, SENSOR_FAULT_MAP, sensors_for

# Per-reading probability of generating a maintenance event when above threshold
_WARN_EVENT_PROB = 0.015
_CRIT_EVENT_PROB = 0.060

# Minimum hours between events on the same engine (prevents unrealistic clusters)
_MIN_EVENT_SPACING_HOURS = 72


def _fault_and_severity(
    sensor_type: str,
    value: float,
    warning: float,
    critical: float,
    rng: random.Random,
) -> tuple[str, str]:
    options = SENSOR_FAULT_MAP[sensor_type]
    if value >= critical:
        # Highest severity option for this sensor type
        for fault, sev in options:
            if sev == "CRITICAL":
                return fault, sev
    # Warning level — pick MAJOR or MINOR randomly, weighted toward MAJOR
    above_warn = [o for o in options if o[1] in ("MAJOR", "MINOR")]
    weights = [2 if sev == "MAJOR" else 1 for _, sev in above_warn]
    return rng.choices(above_warn, weights=weights)[0]


def _pick_component(system: SystemNode, rng: random.Random) -> ComponentNode:
    return rng.choice(system.components)


def generate_maintenance_events(
    aircraft: AircraftNode,
    system_series: dict[str, dict[str, np.ndarray]],  # system_id -> type -> written values
    config: GeneratorConfig,
    event_counter: list[int],  # mutable counter for global event IDs
    rng: random.Random,
) -> list[dict]:
    """
    Scan each engine's written sensor series, spikes included, for threshold
    exceedances and emit maintenance events with realistic fault types and
    corrective actions.
    """
    specs = {spec.type: spec for spec in sensors_for("Engine", aircraft.model)}
    egt_bands = specs["EGT"].bands
    vib_bands = specs["Vibration"].bands
    events: list[dict] = []

    for system in aircraft.systems:
        if system.type != "Engine":
            continue

        series = system_series.get(system.system_id)
        if series is None:
            continue

        egt_vals = series["EGT"]
        vib_vals = series["Vibration"]

        last_event_hour: dict[str, int] = {}  # sensor_type -> last event hour

        for h in range(config.n_hours):
            # Check EGT threshold
            egt = egt_vals[h]
            if egt >= egt_bands.caution:
                p = _CRIT_EVENT_PROB if egt >= egt_bands.warning else _WARN_EVENT_PROB
                last_h = last_event_hour.get("EGT", -_MIN_EVENT_SPACING_HOURS)
                if h - last_h >= _MIN_EVENT_SPACING_HOURS and rng.random() < p:
                    fault, severity = _fault_and_severity(
                        "EGT", egt, egt_bands.caution, egt_bands.warning, rng
                    )
                    events.append(
                        _make_event(
                            aircraft, system, fault, severity, h, config, event_counter, rng
                        )
                    )
                    last_event_hour["EGT"] = h

            # Check Vibration threshold
            vib = vib_vals[h]
            if vib >= vib_bands.caution:
                p = _CRIT_EVENT_PROB if vib >= vib_bands.warning else _WARN_EVENT_PROB
                last_h = last_event_hour.get("Vibration", -_MIN_EVENT_SPACING_HOURS)
                if h - last_h >= _MIN_EVENT_SPACING_HOURS and rng.random() < p:
                    fault, severity = _fault_and_severity(
                        "Vibration", vib, vib_bands.caution, vib_bands.warning, rng
                    )
                    events.append(
                        _make_event(
                            aircraft, system, fault, severity, h, config, event_counter, rng
                        )
                    )
                    last_event_hour["Vibration"] = h

    return events


def _make_event(
    aircraft: AircraftNode,
    system: SystemNode,
    fault: str,
    severity: str,
    hour_offset: int,
    config: GeneratorConfig,
    event_counter: list[int],
    rng: random.Random,
) -> dict:
    event_counter[0] += 1
    event_id = f"ME{event_counter[0]:04d}"
    component = _pick_component(system, rng)
    reported_at = config.start_date + timedelta(hours=hour_offset)
    return {
        ":ID(MaintenanceEvent)": event_id,
        "component_id": component.component_id,
        "system_id": system.system_id,
        "aircraft_id": aircraft.aircraft_id,
        "fault": fault,
        "severity": severity,
        "reported_at": reported_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "corrective_action": CORRECTIVE_ACTIONS.get(fault, "Inspected and cleared"),
    }
