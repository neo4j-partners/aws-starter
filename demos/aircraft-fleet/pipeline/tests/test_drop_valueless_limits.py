"""The cross-link step drops limits with no value before it links sensors."""

from __future__ import annotations

from typing import Any

from populate_aircraft_db import pipeline


class RecordingDriver:
    """Record each query and return one row with count 0."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute_query(self, cypher: str, /, **params: Any) -> tuple[list[dict], None, None]:
        self.queries.append(" ".join(cypher.split()))
        return [{"count": 0}], None, None


def _index(queries: list[str], fragment: str) -> int:
    return next(i for i, query in enumerate(queries) if fragment in query)


def test_limits_with_no_min_and_no_max_are_dropped_before_the_sensor_link() -> None:
    driver = RecordingDriver()

    pipeline.link_to_existing_graph(driver, "db")

    drop = _index(driver.queries, "DETACH DELETE ol")
    assert driver.queries[drop] == (
        "MATCH (ol:OperatingLimit) WHERE ol.minValue IS NULL AND ol.maxValue IS NULL "
        "DETACH DELETE ol RETURN count(*) AS count"
    )
    assert drop < _index(driver.queries, "MERGE (s)-[:HAS_LIMIT]->(ol)")
