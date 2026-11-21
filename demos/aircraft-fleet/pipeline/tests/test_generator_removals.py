"""Removal records need enough airframe hours before the data window."""

from __future__ import annotations

import csv
import random
from collections import Counter, defaultdict
from datetime import datetime
from itertools import pairwise
from pathlib import Path

import pytest

from generator.config import GeneratorConfig
from generator.fleet import generate_fleet
from generator.removals import _BASE_REMOVALS_PER_YEAR, generate_removals


def test_start_date_too_soon_after_entry_into_service_is_rejected() -> None:
    # The latest A220-300 enters service on 2023-05-31. A window that opens
    # a month later leaves fewer airframe hours than the install minimum.
    config = GeneratorConfig(n_aircraft=6, n_days=5, start_date=datetime(2023, 7, 1))
    fleet = generate_fleet(GeneratorConfig(n_aircraft=6))

    with pytest.raises(ValueError, match="start_date"):
        generate_removals(fleet, [], config, random.Random(0))


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


def test_a_busy_component_is_removed_again_after_its_replacement() -> None:
    # 200 critical events raise the first aircraft's removal count well above
    # its component count, so its components must come off more than once.
    config = GeneratorConfig(n_aircraft=2, n_days=365)
    fleet = generate_fleet(config)
    busy = fleet[0]
    events = [{"aircraft_id": busy.aircraft_id, "severity": "CRITICAL"}] * 200

    removals, _, _ = generate_removals(fleet, events, config, random.Random(0))

    busy_removals = [r for r in removals if r["aircraft_id"] == busy.aircraft_id]
    assert len(busy_removals) > sum(len(s.components) for s in busy.systems)
    assert _assert_no_overlap(removals) > 0


def test_a_year_makes_every_drawn_removal(year_dataset: Path) -> None:
    # A year draws more removals for the busiest aircraft than they have
    # components, so those aircraft remove some components twice.
    critical = Counter(
        e["aircraft_id"]
        for e in _rows(year_dataset / "nodes_maintenance.csv")
        if e["severity"] == "CRITICAL"
    )
    aircraft = [r[":ID(Aircraft)"] for r in _rows(year_dataset / "nodes_aircraft.csv")]
    drawn = sum(max(1, round(_BASE_REMOVALS_PER_YEAR * (1 + 0.15 * critical[a]))) for a in aircraft)
    removals = _rows(year_dataset / "nodes_removals.csv")

    assert len(removals) == drawn
    assert _assert_no_overlap(removals) > 0
