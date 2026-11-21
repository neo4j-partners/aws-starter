"""Flights, airframe hours, and cycles follow one utilization per aircraft."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest

from generator.main import generate
from generator.specs import UTILIZATION

DAYS = 90


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("utilization")
    generate(aircraft=30, airports=40, days=DAYS, seed=42, output=output)
    return output


@pytest.fixture(scope="module")
def flights_by_aircraft(dataset: Path) -> dict[str, list[tuple[datetime, datetime]]]:
    flights: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for f in _rows(dataset / "nodes_flights.csv"):
        flights[f["aircraft_id"]].append(
            (_ts(f["scheduled_departure"]), _ts(f["scheduled_arrival"]))
        )
    return {aircraft: sorted(legs) for aircraft, legs in flights.items()}


@pytest.fixture(scope="module")
def removals_by_aircraft(dataset: Path) -> dict[str, list[dict[str, str]]]:
    removals: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in _rows(dataset / "nodes_removals.csv"):
        removals[r["aircraft_id"]].append(r)
    return {a: sorted(rs, key=lambda r: r["removal_date"]) for a, rs in removals.items()}


def test_mean_block_hours_per_day_is_within_utilization(flights_by_aircraft) -> None:
    low, high = UTILIZATION.hours_per_day
    for aircraft, legs in flights_by_aircraft.items():
        block_hours = sum((arr - dep).total_seconds() for dep, arr in legs) / 3600
        assert low <= block_hours / DAYS <= high, aircraft


def test_an_aircraft_flies_one_leg_at_a_time(flights_by_aircraft) -> None:
    for aircraft, legs in flights_by_aircraft.items():
        for (_, arrival), (departure, _) in zip(legs, legs[1:], strict=False):
            assert departure >= arrival, (aircraft, arrival, departure)


def test_cycles_rise_with_airframe_hours(removals_by_aircraft) -> None:
    for aircraft, removals in removals_by_aircraft.items():
        hours = [int(r["flight_hours_at_removal"]) for r in removals]
        cycles = [int(r["flight_cycles_at_removal"]) for r in removals]
        assert hours == sorted(hours), aircraft
        assert cycles == sorted(cycles), aircraft


def test_hours_per_cycle_stays_in_the_model_band(dataset: Path, removals_by_aircraft) -> None:
    model = {r[":ID(Aircraft)"]: r["model"] for r in _rows(dataset / "nodes_aircraft.csv")}
    jitter = UTILIZATION.cycle_jitter
    for aircraft, removals in removals_by_aircraft.items():
        nominal = UTILIZATION.hours_per_cycle[model[aircraft]]
        for r in removals:
            ratio = int(r["flight_hours_at_removal"]) / int(r["flight_cycles_at_removal"])
            # 1 % slack covers rounding both counts to whole numbers.
            assert nominal * (1 - jitter) * 0.99 <= ratio <= nominal * (1 + jitter) * 1.01, (
                aircraft,
                ratio,
            )


def test_airframe_hours_between_removals_match_the_flights(
    flights_by_aircraft, removals_by_aircraft
) -> None:
    # Airframe hours grow continuously, flights in daily blocks, so the two
    # can differ by up to one day of flying, plus 1 for whole-hour rounding.
    tolerance = UTILIZATION.hours_per_day[1] + 1
    pairs = 0
    for aircraft, removals in removals_by_aircraft.items():
        for first, last in zip(removals, removals[1:], strict=False):
            start, end = _ts(first["removal_date"]), _ts(last["removal_date"])
            flown = sum(
                (arr - dep).total_seconds() / 3600
                for dep, arr in flights_by_aircraft[aircraft]
                if start <= dep < end
            )
            gained = int(last["flight_hours_at_removal"]) - int(first["flight_hours_at_removal"])
            assert abs(gained - flown) <= tolerance, (aircraft, gained, flown)
            pairs += 1
    assert pairs, "expected an aircraft with two removals"


def test_cycles_between_removals_match_the_legs_flown(
    flights_by_aircraft, removals_by_aircraft
) -> None:
    # A cycle is one leg. Cycles grow continuously and legs in daily blocks,
    # so the two can differ by up to one day's legs, plus 1 for rounding.
    pairs = 0
    for aircraft, removals in removals_by_aircraft.items():
        legs = flights_by_aircraft[aircraft]
        tolerance = len(legs) / DAYS + 1
        for first, last in zip(removals, removals[1:], strict=False):
            start, end = _ts(first["removal_date"]), _ts(last["removal_date"])
            flown = sum(1 for dep, _ in legs if start <= dep < end)
            gained = int(last["flight_cycles_at_removal"]) - int(first["flight_cycles_at_removal"])
            assert abs(gained - flown) <= tolerance, (aircraft, gained, flown)
            pairs += 1
    assert pairs, "expected an aircraft with two removals"
