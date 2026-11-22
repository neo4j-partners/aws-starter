"""Removal records need enough airframe hours before the data window."""

from __future__ import annotations

import csv
import random
from collections import Counter, defaultdict
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path

import pytest

from generator import removals as removal_module
from generator.config import GeneratorConfig
from generator.fleet import AircraftNode, ComponentNode, SystemNode, generate_fleet
from generator.main import generate
from generator.removals import (
    _BASE_REMOVALS_PER_YEAR,
    _MIN_HOURS_SINCE_INSTALL,
    _causing_event,
    _events_by_component,
    _inspection_routes,
    _most_hours_since_install,
    generate_removals,
)
from generator.specs import CORRECTIVE_ACTIONS


def _event(
    event_id: str,
    aircraft: AircraftNode,
    system: SystemNode,
    component: ComponentNode,
    fault: str,
    severity: str,
    reported_at: str,
) -> dict[str, str]:
    """A maintenance event row with the columns removals read."""
    return {
        ":ID(MaintenanceEvent)": event_id,
        "component_id": component.component_id,
        "system_id": system.system_id,
        "aircraft_id": aircraft.aircraft_id,
        "fault": fault,
        "severity": severity,
        "reported_at": reported_at,
    }


def test_start_date_too_soon_after_entry_into_service_is_rejected() -> None:
    # The latest A320-200 and A321neo enter service on 2023-12-31. A window
    # that opens on 2023-07-01 comes before that, so those aircraft have no
    # airframe hours at all.
    config = GeneratorConfig(n_aircraft=6, n_days=5, start_date=datetime(2023, 7, 1))
    fleet = generate_fleet(GeneratorConfig(n_aircraft=6))

    with pytest.raises(ValueError, match="start_date"):
        generate_removals(fleet, [], config, random.Random(0))


def test_generate_checks_the_start_date_before_writing_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Removals come last, so without an early check a bad start date fails
    # only after the readings and flights are written.
    monkeypatch.setattr(removal_module, "_LATEST_ENTRY_INTO_SERVICE", date(2030, 1, 1))

    with pytest.raises(ValueError, match="start_date"):
        generate(aircraft=6, airports=40, days=2, seed=42, output=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_default_start_date_is_accepted() -> None:
    config = GeneratorConfig(n_aircraft=6, n_days=5)

    removals, _, _ = generate_removals(generate_fleet(config), [], config, random.Random(0))

    assert removals


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _assert_no_overlap(removals: list[dict]) -> int:
    """Assert each component's install-to-removal intervals are disjoint; return repeats."""
    by_component: dict[str, list[dict]] = defaultdict(list)
    for r in removals:
        by_component[r["component_id"]].append(r)
    for rows in by_component.values():
        rows.sort(key=lambda r: r["removal_date"])
        for before, after in pairwise(rows):
            assert after["installation_date"] >= before["removal_date"], (before, after)
    return len(removals) - len(by_component)


def _assert_spread(removals: list[dict], fleet: list[AircraftNode]) -> None:
    """Assert no removal repeats a component while an eligible one has none yet.

    Replays each aircraft's removals in date order and recomputes which
    components could come off on each date.
    """
    by_aircraft: dict[str, list[dict]] = defaultdict(list)
    for r in removals:
        by_aircraft[r["aircraft_id"]].append(r)
    for aircraft in fleet:
        components = [c.component_id for s in aircraft.systems for c in s.components]
        counts: Counter[str] = Counter()
        last: dict[str, datetime] = {}
        for r in sorted(by_aircraft[aircraft.aircraft_id], key=lambda r: r["removal_date"]):
            date = datetime.fromisoformat(r["removal_date"])
            hours = int(r["flight_hours_at_removal"])
            eligible = [
                c
                for c in components
                if _most_hours_since_install(date, last.get(c), hours, aircraft.hours_per_day)
                >= _MIN_HOURS_SINCE_INSTALL
            ]
            if counts[r["component_id"]]:
                unused = [c for c in eligible if not counts[c]]
                assert not unused, (r, unused)
            counts[r["component_id"]] += 1
            last[r["component_id"]] = date


def test_a_busy_component_is_removed_again_after_its_replacement() -> None:
    # 200 critical events raise the first aircraft's removal count well above
    # its component count, so its components must come off more than once.
    config = GeneratorConfig(n_aircraft=2, n_days=365)
    fleet = generate_fleet(config)
    busy = fleet[0]
    engine = busy.systems[0]
    part = engine.components[0]
    events = [
        _event(f"ME{n:04d}", busy, engine, part, "Overheat", "CRITICAL", "2024-07-01T00:00:00")
        for n in range(200)
    ]

    removals, _, _ = generate_removals(fleet, events, config, random.Random(0))

    busy_removals = [r for r in removals if r["aircraft_id"] == busy.aircraft_id]
    assert len(busy_removals) > sum(len(s.components) for s in busy.systems)
    assert _assert_no_overlap(removals) > 0


def test_a_year_makes_every_drawn_removal(year_dataset: Path) -> None:
    # A year draws about four removals per aircraft, more with more critical
    # events. A component comes off a second time only once every component
    # eligible on that date has come off at least once.
    critical = Counter(
        e["aircraft_id"]
        for e in _rows(year_dataset / "nodes_maintenance.csv")
        if e["severity"] == "CRITICAL"
    )
    aircraft = [r[":ID(Aircraft)"] for r in _rows(year_dataset / "nodes_aircraft.csv")]
    drawn = sum(max(1, round(_BASE_REMOVALS_PER_YEAR * (1 + 0.15 * critical[a]))) for a in aircraft)
    removals = _rows(year_dataset / "nodes_removals.csv")

    assert len(removals) == drawn
    _assert_no_overlap(removals)
    fleet = generate_fleet(GeneratorConfig(n_aircraft=30, n_airports=40, n_days=365, seed=42))
    assert [a.aircraft_id for a in fleet] == aircraft
    _assert_spread(removals, fleet)


def test_the_causing_event_is_the_parts_latest_event_after_its_install() -> None:
    fleet = generate_fleet(GeneratorConfig(n_aircraft=1))
    aircraft = fleet[0]
    engine = aircraft.systems[0]
    part = engine.components[0]
    events = _events_by_component(
        [
            _event("ME0002", aircraft, engine, part, "Leak", "MAJOR", "2024-07-20T10:00:00"),
            _event("ME0001", aircraft, engine, part, "Overheat", "MINOR", "2024-07-05T08:00:00"),
            _event("ME0003", aircraft, engine, part, "Overheat", "CRITICAL", "2024-08-02T00:00:00"),
        ]
    )[part.component_id]
    removed = datetime(2024, 7, 25)

    # The latest event at or before the removal wins, whatever the row order.
    assert _causing_event(events, datetime(2024, 1, 1), removed)[":ID(MaintenanceEvent)"] == (
        "ME0002"
    )
    # An event on the part this one replaced cannot cause its removal.
    assert _causing_event(events, datetime(2024, 7, 21), removed) is None
    # An event after the removal cannot cause it either.
    assert _causing_event(events, datetime(2024, 1, 1), datetime(2024, 7, 1)) is None


def test_every_component_type_has_an_inspection_fault() -> None:
    for aircraft in generate_fleet(GeneratorConfig(n_aircraft=100)):
        for system in aircraft.systems:
            for component in system.components:
                routes = _inspection_routes(aircraft.model, system, component)
                assert routes, (aircraft.model, system.type, component.type)
                assert {r.fault for r in routes} <= set(CORRECTIVE_ACTIONS)


def test_removal_reasons_name_the_causing_event_or_an_inspection_fault(
    year_dataset: Path,
) -> None:
    events: dict[str, list[dict[str, str]]] = defaultdict(list)
    for e in _rows(year_dataset / "nodes_maintenance.csv"):
        events[e["component_id"]].append(e)
    caused = inspected = 0
    for r in _rows(year_dataset / "nodes_removals.csv"):
        prior = [
            e
            for e in events[r["component_id"]]
            if r["installation_date"] <= e["reported_at"] <= r["removal_date"]
        ]
        if prior:
            last = max(prior, key=lambda e: e["reported_at"])
            expected = (
                f"{last['fault']} after {last['severity']} event {last[':ID(MaintenanceEvent)']}"
            )
            assert r["RMV_REA_TX"] == expected, r
            caused += 1
        else:
            fault, _, rest = r["RMV_REA_TX"].partition(" found on inspection")
            assert fault in CORRECTIVE_ACTIONS and rest == "", r
            inspected += 1
    # A year of events gives both kinds of removal.
    assert caused and inspected


def test_removal_reasons_are_the_same_for_a_seed() -> None:
    config = GeneratorConfig(n_aircraft=6, n_days=30)
    fleet = generate_fleet(config)

    first, _, _ = generate_removals(fleet, [], config, random.Random(7))
    second, _, _ = generate_removals(fleet, [], config, random.Random(7))

    assert [r["RMV_REA_TX"] for r in first] == [r["RMV_REA_TX"] for r in second]
