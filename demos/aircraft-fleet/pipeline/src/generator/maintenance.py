"""
Correlated maintenance event generation.

Every sensor on every system is scanned hour by hour. A reading that enters a
higher band than the hour before may raise an event, with a probability that
rises with the band. A reading that stays in its band does not roll again.
The event's severity is the band of that reading: advisory is MINOR, caution
is MAJOR, and warning is CRITICAL. The side of the crossing picks the sensor's
fault routes, and the route picks the fault and the component it hits.

This produces the causal signal the GDS algorithms need: aircraft with steeper
degradation slopes accumulate more events and form distinct kNN/Louvain clusters.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

import numpy as np

from .config import GeneratorConfig
from .fleet import AircraftNode, ComponentNode, SystemNode
from .specs import CORRECTIVE_ACTIONS, Direction, FaultRoute, SensorSpec, sensors_for

# Probability that entering the advisory, caution, or warning band raises an event.
# Tuned once, with the spike rates in sensors.py, so the default run lands near
# the manuals' historic 52/31/17 MINOR/MAJOR/CRITICAL mix.
_EVENT_PROB: dict[int, float] = {1: 0.012, 2: 0.030, 3: 0.05}
SEVERITY_BY_LEVEL: dict[int, str] = {1: "MINOR", 2: "MAJOR", 3: "CRITICAL"}

# Minimum hours between events of one fault on one system, unless the new
# event is more severe than the last one. An escalation is always reported.
_MIN_EVENT_SPACING_HOURS = 72


@dataclass(frozen=True)
class MaintenanceEvent:
    """One event's CSV row, plus the sensor whose reading raised it."""

    row: dict[str, str]
    sensor_id: str


def _band_levels(spec: SensorSpec, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Band level of each reading (0 to 3) and the side it sits on (+1 high, -1 low)."""
    match spec.direction:
        case Direction.HIGH:
            sides = np.ones(len(values))
        case Direction.LOW:
            sides = -np.ones(len(values))
        case Direction.DEVIATION:
            sides = np.where(values >= spec.baseline, 1.0, -1.0)
    distance = (values - spec.baseline) * sides
    levels = sum((distance >= offset).astype(int) for offset in spec.offsets())
    return levels, sides


def _entries(levels: np.ndarray, sides: np.ndarray) -> np.ndarray:
    """Keep each hour's level only where the reading enters a band.

    A reading enters a band when its level is higher than the hour before,
    or when it is in a band on the other side of the baseline from the
    hour before.
    """
    previous = np.concatenate(([0], levels[:-1]))
    previous_sides = np.concatenate((sides[:1], sides[:-1]))
    entered = (levels > previous) | ((sides != previous_sides) & (levels > 0))
    return np.where(entered, levels, 0)


def _pick_route(routes: list[FaultRoute], rng: random.Random) -> FaultRoute:
    return rng.choices(routes, weights=[r.weight for r in routes])[0]


def _pick_component(
    system: SystemNode, route: FaultRoute, rng: random.Random
) -> ComponentNode | None:
    candidates = [c for c in system.components if c.type in route.components]
    return rng.choice(candidates) if candidates else None


def generate_maintenance_events(
    aircraft: AircraftNode,
    system_series: dict[str, dict[str, np.ndarray]],  # system_id -> type -> written values
    config: GeneratorConfig,
    event_counter: list[int],  # mutable counter for global event IDs
    rng: random.Random,
) -> list[MaintenanceEvent]:
    """
    Scan every system's written sensor series, spikes included, for band
    entries and emit maintenance events with routed faults and components.
    """
    events: list[MaintenanceEvent] = []

    for system in aircraft.systems:
        series = system_series.get(system.system_id)
        if series is None:
            continue
        specs = {spec.type: spec for spec in sensors_for(system.type, aircraft.model)}
        scans = []
        for sensor in system.sensors:
            levels, sides = _band_levels(specs[sensor.type], series[sensor.type])
            scans.append((sensor, specs[sensor.type], _entries(levels, sides), sides))

        last_event: dict[str, tuple[int, int]] = {}  # fault -> (hour, level) on this system
        for h in range(config.n_hours):
            for sensor, spec, levels, sides in scans:
                level = int(levels[h])
                if level == 0 or rng.random() >= _EVENT_PROB[level]:
                    continue
                side = Direction.HIGH if sides[h] > 0 else Direction.LOW
                routes = [r for r in spec.faults if r.side is side]
                if not routes:
                    continue
                route = _pick_route(routes, rng)
                last_hour, last_level = last_event.get(route.fault, (-_MIN_EVENT_SPACING_HOURS, 0))
                if h - last_hour < _MIN_EVENT_SPACING_HOURS and level <= last_level:
                    continue
                component = _pick_component(system, route, rng)
                if component is None:
                    continue
                event_counter[0] += 1
                reported_at = config.start_date + timedelta(hours=h)
                row = {
                    ":ID(MaintenanceEvent)": f"ME{event_counter[0]:04d}",
                    "component_id": component.component_id,
                    "system_id": system.system_id,
                    "aircraft_id": aircraft.aircraft_id,
                    "fault": route.fault,
                    "severity": SEVERITY_BY_LEVEL[level],
                    "reported_at": reported_at.strftime("%Y-%m-%dT%H:%M:%S"),
                    "corrective_action": CORRECTIVE_ACTIONS[route.fault],
                }
                events.append(MaintenanceEvent(row=row, sensor_id=sensor.sensor_id))
                last_event[route.fault] = (h, level)

    return events
