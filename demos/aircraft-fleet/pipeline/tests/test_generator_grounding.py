"""A CRITICAL maintenance event grounds its aircraft for the rest of that day."""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest

from generator.config import GeneratorConfig
from generator.fleet import AircraftNode, generate_fleet
from generator.main import generate
from generator.operations import generate_operations

CONFIG = GeneratorConfig(n_aircraft=1, n_days=3, seed=5)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _event(aircraft: AircraftNode, severity: str, reported_at: str) -> dict[str, str]:
    return {"aircraft_id": aircraft.aircraft_id, "severity": severity, "reported_at": reported_at}


def _departures(events: list[dict[str, str]]) -> list[datetime]:
    _, flights, *_ = generate_operations(
        generate_fleet(CONFIG), CONFIG, random.Random(CONFIG.seed), events
    )
    return [datetime.fromisoformat(f["scheduled_departure"]) for f in flights]


def test_no_event_flies_every_leg() -> None:
    aircraft = generate_fleet(CONFIG)[0]

    assert len(_departures([])) == aircraft.legs_per_day * CONFIG.n_days


def test_an_event_before_the_first_leg_grounds_the_whole_day() -> None:
    aircraft = generate_fleet(CONFIG)[0]

    departures = _departures([_event(aircraft, "CRITICAL", "2024-07-02T01:00:00")])

    assert {d.day for d in departures} == {1, 3}
    assert len(departures) == aircraft.legs_per_day * 2


def test_a_mid_day_event_cancels_only_the_later_legs() -> None:
    aircraft = generate_fleet(CONFIG)[0]
    ungrounded = [d for d in _departures([]) if d.day == 2]
    grounded_at = ungrounded[1]

    departures = _departures(
        [_event(aircraft, "CRITICAL", grounded_at.strftime("%Y-%m-%dT%H:%M:%S"))]
    )

    # The first leg left before the event. Every leg from then to midnight is cancelled.
    assert [d for d in departures if d.day == 2] == ungrounded[:1]
    assert sum(d.day == 3 for d in departures) == aircraft.legs_per_day


@pytest.mark.parametrize("severity", ["MINOR", "MAJOR"])
def test_a_less_severe_event_grounds_nothing(severity: str) -> None:
    aircraft = generate_fleet(CONFIG)[0]

    departures = _departures([_event(aircraft, severity, "2024-07-02T01:00:00")])

    assert len(departures) == aircraft.legs_per_day * CONFIG.n_days


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("grounding")
    generate(aircraft=30, airports=40, days=90, seed=42, output=output)
    return output


def test_no_leg_departs_between_a_critical_event_and_midnight(dataset: Path) -> None:
    departures: dict[str, list[datetime]] = defaultdict(list)
    for f in _rows(dataset / "nodes_flights.csv"):
        departures[f["aircraft_id"]].append(datetime.fromisoformat(f["scheduled_departure"]))
    critical = [e for e in _rows(dataset / "nodes_maintenance.csv") if e["severity"] == "CRITICAL"]

    assert critical
    for event in critical:
        reported = datetime.fromisoformat(event["reported_at"])
        grounded = [
            d
            for d in departures[event["aircraft_id"]]
            if d >= reported and d.date() == reported.date()
        ]
        assert not grounded, (event[":ID(MaintenanceEvent)"], grounded)


def test_each_leg_departs_from_where_the_last_one_landed(dataset: Path) -> None:
    # Cancelled legs never fly, so the aircraft stays where it last landed.
    legs: dict[str, list[dict[str, str]]] = defaultdict(list)
    for f in _rows(dataset / "nodes_flights.csv"):
        legs[f["aircraft_id"]].append(f)
    for aircraft, flights in legs.items():
        flights.sort(key=lambda f: f["scheduled_departure"])
        for before, after in zip(flights, flights[1:], strict=False):
            assert after["origin"] == before["destination"], (aircraft, before, after)
