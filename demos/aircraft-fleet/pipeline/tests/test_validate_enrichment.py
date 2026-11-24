"""validate_enrichment runs a cross-link query only when the graph has its names."""

from __future__ import annotations

from typing import Any

import pytest

from populate_aircraft_db import pipeline


class TokenDriver:
    """Report fixed labels and types, and one row for each cross-link query."""

    def __init__(self, labels: set[str], rel_types: set[str]) -> None:
        self.labels = labels
        self.rel_types = rel_types
        self.cross_link_queries: list[str] = []

    def execute_query(self, cypher: str, /, **params: Any) -> tuple[list[dict], None, None]:
        if cypher.startswith("CALL db.labels()"):
            return [{"label": label} for label in self.labels], None, None
        if cypher.startswith("CALL db.relationshipTypes()"):
            return [{"relationshipType": t} for t in self.rel_types], None, None
        if "AS src" in cypher:
            self.cross_link_queries.append(cypher)
            return [{"src": "a", "tgt": "b"}], None, None
        return [], None, None


def test_cross_links_run_only_when_the_graph_has_their_labels_and_type(
    capsys: pytest.CaptureFixture[str],
) -> None:
    driver = TokenDriver(
        labels={"Aircraft", "Document", "AircraftModel", "Sensor", "OperatingLimit"},
        rel_types={"APPLIES_TO", "HAS_LIMIT", "DESCRIBES_COMPONENT"},
    )

    pipeline.validate_enrichment(driver, "db")

    out = capsys.readouterr().out
    after_cross = out.split("Cross-links to operational graph:\n")[1]
    cross_section, load_section = after_cross.split("\n  Load links from stage 2:\n")
    assert cross_section.splitlines() == [
        "    Document -[:APPLIES_TO]-> Aircraft: a->b",
        "    AircraftModel -[:DESCRIBES_MODEL]-> Aircraft: (none)",
        "    SystemReference -[:DESCRIBES_SYSTEM]-> System: (none)",
        "    ComponentReference -[:DESCRIBES_COMPONENT]-> Component: (none)",
        "    OperatingLimit -[:FROM_CHUNK]-> Chunk: (none)",
    ]
    assert load_section.splitlines() == [
        "    Sensor -[:HAS_LIMIT]-> OperatingLimit: a->b",
    ]
    assert [query.split(")")[0] for query in driver.cross_link_queries] == [
        "MATCH (d:Document",
        "MATCH (s:Sensor",
    ]
