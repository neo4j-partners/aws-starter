"""The manual tail registry in specs.py must match the maintenance manuals."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pytest

from generator.config import GeneratorConfig
from generator.fleet import _distribute, _registry_fleet, entry_into_service, generate_fleet
from generator.specs import (
    ENTRY_INTO_SERVICE_RANGES,
    MANUAL_FLEET_TAILS,
    MANUAL_TAIL_ENTRY_INTO_SERVICE,
    MANUAL_TAIL_OPERATORS,
    MODEL_DISTRIBUTION,
    OPERATORS,
)
from populate_aircraft_db.pipeline import DOCUMENTS

MANUALS_DIR = Path(__file__).resolve().parent.parent / "manuals"
FLEET_LINE = re.compile(r"^\*\*Fleet:\*\*\s*(.+)$", re.MULTILINE)
EXAMPLE_AIRCRAFT = re.compile(r"Aircraft: (AC\d+) \((N\w+)\)")
# A fleet table row: aircraft ID, tail, and an ICAO 24 address if listed.
TABLE_AIRCRAFT = re.compile(r"^\| (AC\d+) \| (N\w+) \|(?: ([0-9a-f]{6}) \|)?", re.MULTILINE)
OPERATOR_LINE = re.compile(r"^\*\*Operator:\*\*\s*(.+)$", re.MULTILINE)
_OPERATOR_NAMES = "|".join(op.name for op in OPERATORS)
SERVICE_RANGE = re.compile(r"entered service between (\d{4}) and (\d{4})")
SERVICE_TABLE_ROW = re.compile(
    r"^\| AC\d+ \| (N\w+) \| [0-9a-f]{6} \| (\w+ \d{4}) \|$", re.MULTILINE
)
REGISTRATION_ROW = re.compile(rf"^\| ({_OPERATOR_NAMES}) \| (N\w+(?:, N\w+)*) \|", re.MULTILINE)


def _manual_text(filename: str) -> str:
    return (MANUALS_DIR / filename).read_text(encoding="utf-8")


def test_registry_covers_every_manual() -> None:
    assert set(MANUAL_FLEET_TAILS) == {doc.aircraft_type for doc in DOCUMENTS}
    registry_tails = {tail for tails in MANUAL_FLEET_TAILS.values() for tail in tails}
    assert set(MANUAL_TAIL_OPERATORS) == registry_tails


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
    head = min(n_aircraft, registry_size)
    assert [(ac.model, ac.tail_number) for ac in fleet[:head]] == _registry_fleet()[:n_aircraft]
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
    for aircraft_id, tail in examples:
        aircraft = fleet[aircraft_id]
        assert (aircraft.tail_number, aircraft.model) == (tail, doc.aircraft_type)
    for aircraft_id, tail, icao in TABLE_AIRCRAFT.findall(text):
        aircraft = fleet[aircraft_id]
        assert (aircraft.tail_number, aircraft.model) == (tail, doc.aircraft_type)
        if icao:
            assert aircraft.icao24 == icao, aircraft_id


def _manual_tail_operators(text: str, model: str) -> dict[str, str]:
    """Map each manual tail to its operator.

    The Registrations column of the fleet table gives the mapping. A manual
    without that column gives every tail the single operator on its
    **Operator:** line.
    """
    rows = REGISTRATION_ROW.findall(text)
    if rows:
        return {tail: operator for operator, tails in rows for tail in tails.split(", ")}
    (operator,) = OPERATOR_LINE.search(text).group(1).split(", ")
    return dict.fromkeys(MANUAL_FLEET_TAILS[model], operator)


@pytest.mark.parametrize("doc", DOCUMENTS, ids=lambda doc: doc.aircraft_type)
def test_registry_operators_match_manual(doc) -> None:
    text = _manual_text(doc.filename)
    manual = _manual_tail_operators(text, doc.aircraft_type)
    assert sorted(manual) == sorted(MANUAL_FLEET_TAILS[doc.aircraft_type])
    line_operators = OPERATOR_LINE.search(text).group(1).split(", ")
    assert set(line_operators) == set(manual.values())
    tail_counts = [list(manual.values()).count(op) for op in line_operators]
    assert tail_counts[0] == max(tail_counts), "the primary operator is listed first"
    fleet = generate_fleet(GeneratorConfig(n_aircraft=30))
    generated = {ac.tail_number: ac.operator_profile.name for ac in fleet}
    assert {tail: generated[tail] for tail in manual} == manual


def test_registry_order_is_round_robin_by_model() -> None:
    first = [tails[0] for tails in MANUAL_FLEET_TAILS.values()]
    assert [tail for _, tail in _registry_fleet()[: len(first)]] == first


def test_distribute_gives_remainders_to_largest_fractions() -> None:
    # Quotas at n=3: B737 1.05, A320 0.75, A321neo 0.60, E190 0.30, A220 0.30.
    assert _distribute(3) == ["B737-800", "A320-200", "A321neo"]


@pytest.mark.parametrize("n", [0, 1, 7, 20, 70])
def test_distribute_uses_largest_remainder(n: int) -> None:
    models = _distribute(n)
    assert len(models) == n
    for model, fraction in MODEL_DISTRIBUTION:
        assert abs(models.count(model) - n * fraction) < 1


@pytest.mark.parametrize("doc", DOCUMENTS, ids=lambda doc: doc.aircraft_type)
def test_entry_into_service_matches_manual(doc) -> None:
    """Each model's range, and any per-tail month, matches its manual."""
    text = _manual_text(doc.filename)
    first, last = ENTRY_INTO_SERVICE_RANGES[doc.aircraft_type]
    if match := SERVICE_RANGE.search(text):
        start_year, end_year = (int(year) for year in match.groups())
        assert (first, last) == (date(start_year, 1, 1), date(end_year, 12, 31))
    else:
        table = {
            tail: datetime.strptime(month, "%B %Y").date()
            for tail, month in SERVICE_TABLE_ROW.findall(text)
        }
        assert set(table) == set(MANUAL_FLEET_TAILS[doc.aircraft_type])
        assert {tail: MANUAL_TAIL_ENTRY_INTO_SERVICE[tail] for tail in table} == table
        assert first == min(table.values())
        assert last.replace(day=1) == max(table.values())


def test_every_entry_into_service_is_in_its_model_range() -> None:
    for aircraft in generate_fleet(GeneratorConfig(n_aircraft=200)):
        first, last = ENTRY_INTO_SERVICE_RANGES[aircraft.model]
        assert first <= aircraft.entry_into_service <= last, aircraft.tail_number
        assert aircraft.entry_into_service == entry_into_service(
            aircraft.model, aircraft.tail_number
        )
