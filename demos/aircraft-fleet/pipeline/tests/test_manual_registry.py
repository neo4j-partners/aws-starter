"""The manual tail registry in specs.py must match the maintenance manuals."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from generator.config import GeneratorConfig
from generator.fleet import _distribute, generate_fleet
from generator.specs import MANUAL_FLEET_TAILS, MODEL_DISTRIBUTION
from populate_aircraft_db.pipeline import DOCUMENTS

MANUALS_DIR = Path(__file__).resolve().parent.parent / "manuals"
FLEET_LINE = re.compile(r"^\*\*Fleet:\*\*\s*(.+)$", re.MULTILINE)
EXAMPLE_AIRCRAFT = re.compile(r"Aircraft: (AC\d+) \((N\w+)\)")
TABLE_AIRCRAFT = re.compile(r"^\| (AC\d+) \| (N\w+) \|", re.MULTILINE)


def _manual_text(filename: str) -> str:
    return (MANUALS_DIR / filename).read_text(encoding="utf-8")


def test_registry_covers_every_manual() -> None:
    assert set(MANUAL_FLEET_TAILS) == {doc.aircraft_type for doc in DOCUMENTS}


@pytest.mark.parametrize("doc", DOCUMENTS, ids=lambda doc: doc.aircraft_type)
def test_fleet_line_matches_registry(doc) -> None:
    match = FLEET_LINE.search(_manual_text(doc.filename))
    assert match, f"{doc.filename} has no **Fleet:** line"
    tails = [tail.strip() for tail in match.group(1).split(",")]
    assert tails == MANUAL_FLEET_TAILS[doc.aircraft_type]


@pytest.mark.parametrize("n_aircraft", [20, 30, 100])
def test_generated_fleet_assigns_registry_first(n_aircraft: int) -> None:
    fleet = generate_fleet(GeneratorConfig(n_aircraft=n_aircraft))
    by_tail = {ac.tail_number: ac.model for ac in fleet}
    assert len(fleet) == n_aircraft
    assert len(by_tail) == n_aircraft, "tail numbers must be unique"
    registry_size = sum(len(tails) for tails in MANUAL_FLEET_TAILS.values())
    registry_tails = {tail for tails in MANUAL_FLEET_TAILS.values() for tail in tails}
    for ac in fleet[registry_size:]:
        assert ac.tail_number not in registry_tails
        assert re.fullmatch(r"N9\d{4}", ac.tail_number), ac.tail_number
    if n_aircraft >= registry_size:
        for model, tails in MANUAL_FLEET_TAILS.items():
            for tail in tails:
                assert by_tail.get(tail) == model, f"{tail} should be a {model}"


@pytest.mark.parametrize("doc", DOCUMENTS, ids=lambda doc: doc.aircraft_type)
def test_manual_example_aircraft_matches_fleet(doc) -> None:
    text = _manual_text(doc.filename)
    examples = EXAMPLE_AIRCRAFT.findall(text)
    assert examples, f"{doc.filename} has no example aircraft ID"
    fleet = {ac.aircraft_id: ac for ac in generate_fleet(GeneratorConfig(n_aircraft=30))}
    for aircraft_id, tail in examples + TABLE_AIRCRAFT.findall(text):
        aircraft = fleet[aircraft_id]
        assert (aircraft.tail_number, aircraft.model) == (tail, doc.aircraft_type)


@pytest.mark.parametrize("n", [0, 1, 7, 20, 70])
def test_distribute_uses_largest_remainder(n: int) -> None:
    models = _distribute(n)
    assert len(models) == n
    for model, fraction in MODEL_DISTRIBUTION:
        assert abs(models.count(model) - n * fraction) < 1
