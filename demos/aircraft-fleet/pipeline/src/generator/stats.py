"""Fleet statistics for the manuals, counted from a generated run.

`generate-data stats` writes them to manuals/fleet-stats.json, and the
manuals' statistics blocks render from that file.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterable, Mapping

import numpy as np

from .config import GeneratorConfig
from .fleet import AircraftNode, generate_fleet
from .maintenance import generate_maintenance_events
from .sensors import generate_system_readings
from .specs import EVENT_SEVERITIES, SYSTEM_SENSORS, sensors_for

# The dataset ./setup.sh loads by default, so the manuals describe the graph.
STATS_CONFIG = GeneratorConfig(n_aircraft=30, n_days=90, seed=42)


def fleet_stats(config: GeneratorConfig = STATS_CONFIG) -> dict:
    """Generate config's fleet and events in memory and count the events.

    The readings and events are drawn in the same order as a generate run,
    so the counts match the dataset that run writes.
    """
    rng = random.Random(config.seed)
    rng_np = np.random.default_rng(config.seed)
    fleet = generate_fleet(config)
    counter = [0]
    rows: list[Mapping[str, str]] = []
    for aircraft in fleet:
        series = {
            system.system_id: generate_system_readings(aircraft, system, config, rng_np)[0]
            for system in aircraft.systems
        }
        events = generate_maintenance_events(aircraft, series, config, counter, rng)
        rows.extend(event.row for event in events)
    return count_events(fleet, rows, config)


def count_events(
    fleet: list[AircraftNode], rows: Iterable[Mapping[str, str]], config: GeneratorConfig
) -> dict:
    """Count maintenance event rows per model by severity, system, and fault.

    Every severity, system, and routed fault is listed, with 0 when no event
    has it, so a renderer can look up any of them.
    """
    model_of = {a.aircraft_id: a.model for a in fleet}
    system_of = {s.system_id: s.type for a in fleet for s in a.systems}
    by_severity: dict[str, Counter[str]] = {}
    by_system: dict[str, Counter[str]] = {}
    by_fault: dict[tuple[str, str], Counter[str]] = {}
    for row in rows:
        model, system = model_of[row["aircraft_id"]], system_of[row["system_id"]]
        by_severity.setdefault(model, Counter())[row["severity"]] += 1
        by_system.setdefault(model, Counter())[system] += 1
        by_fault.setdefault((model, system), Counter())[row["fault"]] += 1

    models: dict[str, dict] = {}
    for model in sorted(set(model_of.values())):
        faults = {}
        for system in SYSTEM_SENSORS:
            routed = {r.fault for spec in sensors_for(system, model) for r in spec.faults}
            counts = by_fault.get((model, system), Counter())
            faults[system] = {f: counts[f] for f in sorted(routed | set(counts))}
        models[model] = {
            "aircraft": sum(m == model for m in model_of.values()),
            "events": sum(by_system.get(model, Counter()).values()),
            "by_severity": {s: by_severity.get(model, Counter())[s] for s in EVENT_SEVERITIES},
            "by_system": {s: by_system.get(model, Counter())[s] for s in SYSTEM_SENSORS},
            "by_fault": faults,
        }
    return {
        "config": {"aircraft": config.n_aircraft, "days": config.n_days, "seed": config.seed},
        "models": models,
    }
