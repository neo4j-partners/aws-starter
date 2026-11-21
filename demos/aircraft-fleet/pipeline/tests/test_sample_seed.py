"""Sections 9 and 11-14 search from one random seed chunk per run."""

from __future__ import annotations

from typing import Any

import pytest

from populate_aircraft_db import samples
from populate_aircraft_db.samples import pick_seed_chunk

SEEDED_SECTIONS = [
    "_vector_similarity",
    "_vector_document_context",
    "_adjacent_chunks",
    "_vector_topology",
    "_hybrid_comparison",
]
UNSEEDED_SECTIONS = [
    "_aircraft_fleet",
    "_system_hierarchy",
    "_flight_operations",
    "_maintenance_events",
    "_sensors",
    "_document_chunks",
    "_extracted_entities",
    "_cross_links",
    "_fulltext_search",
]


class RecordingDriver:
    """Return `rows` for every query and record each query with its parameters."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def execute_query(self, cypher: str, /, **params: Any) -> tuple[list[dict], None, None]:
        self.queries.append((cypher, params))
        return self.rows, None, None


def test_pick_seed_chunk_chooses_among_embedded_chunks(monkeypatch) -> None:
    driver = RecordingDriver([{"chunk_id": "A:0"}, {"chunk_id": "A:1"}, {"chunk_id": "B:0"}])
    monkeypatch.setattr(samples.random, "choice", lambda ids: ids[-1])

    assert pick_seed_chunk(driver, "db") == "B:0"
    [(cypher, _)] = driver.queries
    assert "c.embedding IS NOT NULL" in cypher
    assert "c.text IS NOT NULL" in cypher


def test_pick_seed_chunk_returns_none_without_chunks() -> None:
    assert pick_seed_chunk(RecordingDriver(), "db") is None


@pytest.mark.parametrize("section", SEEDED_SECTIONS)
def test_section_searches_from_the_given_seed(section: str) -> None:
    driver = RecordingDriver()

    getattr(samples, section)(driver, "db", 3, "DOC-1:4")

    assert driver.queries
    for cypher, params in driver.queries:
        assert "MATCH (seed:Chunk {chunkId: $seed_id})" in cypher
        assert "rand()" not in cypher
        assert params["seed_id"] == "DOC-1:4"


@pytest.mark.parametrize("section", SEEDED_SECTIONS)
def test_section_without_a_seed_skips_its_query(capsys, section: str) -> None:
    driver = RecordingDriver()

    getattr(samples, section)(driver, "db", 3, None)

    assert driver.queries == []
    assert "no chunks with embeddings" in capsys.readouterr().out


def test_run_all_samples_picks_one_seed_for_every_seeded_section(monkeypatch, capsys) -> None:
    picks: list[str] = []
    received: dict[str, str | None] = {}

    def pick(driver: object, database: str) -> str:
        picks.append(database)
        return "DOC-2:7"

    monkeypatch.setattr(samples, "pick_seed_chunk", pick)
    for name in UNSEEDED_SECTIONS:
        monkeypatch.setattr(samples, name, lambda *args: None)
    for name in SEEDED_SECTIONS:
        monkeypatch.setattr(
            samples, name, lambda d, db, n, seed_id, name=name: received.update({name: seed_id})
        )

    samples.run_all_samples(object(), "db", 3)

    assert picks == ["db"]
    assert received == dict.fromkeys(SEEDED_SECTIONS, "DOC-2:7")
    assert "Seed chunk for sections 9 and 11-14: DOC-2:7" in capsys.readouterr().out
