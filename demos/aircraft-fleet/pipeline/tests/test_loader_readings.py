"""Reading rows with an unknown sensor_id are skipped and counted.

This test writes to Neo4j, so it runs only when NEO4J_TEST_URI points at a
local server. Set NEO4J_TEST_PASSWORD, and optionally NEO4J_TEST_USERNAME
and NEO4J_TEST_DATABASE. It removes the nodes it creates.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
from neo4j import Driver, GraphDatabase

from populate_aircraft_db.loader import _NODE_DEFINITIONS, _run_in_batches

TEST_URI = os.environ.get("NEO4J_TEST_URI", "")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
PREFIX = "pytest-loader-"

pytestmark = pytest.mark.skipif(not TEST_URI, reason="NEO4J_TEST_URI is not set")


@pytest.fixture
def driver() -> Iterator[Driver]:
    assert urlparse(TEST_URI).hostname in LOCAL_HOSTS, "loader tests only run against localhost"
    auth = (os.environ.get("NEO4J_TEST_USERNAME", "neo4j"), os.environ["NEO4J_TEST_PASSWORD"])
    with GraphDatabase.driver(TEST_URI, auth=auth) as drv:
        yield drv


@pytest.fixture
def database(driver: Driver) -> Iterator[str]:
    db = os.environ.get("NEO4J_TEST_DATABASE", "neo4j")
    cleanup = "MATCH (n) WHERE n.sensor_id STARTS WITH $prefix DETACH DELETE n"
    driver.execute_query(cleanup, prefix=PREFIX, database_=db)
    yield db
    driver.execute_query(cleanup, prefix=PREFIX, database_=db)


def test_reading_with_unknown_sensor_is_skipped(driver: Driver, database: str) -> None:
    query = next(q for label, _, q in _NODE_DEFINITIONS if label == "Reading")
    known, unknown = f"{PREFIX}known", f"{PREFIX}unknown"
    driver.execute_query("CREATE (:Sensor {sensor_id: $id})", id=known, database_=database)
    batch = [
        {
            "reading_id": f"{PREFIX}r1",
            "sensor_id": known,
            "ts": "2024-07-01T00:00:00",
            "value": "1",
        },
        {
            "reading_id": f"{PREFIX}r2",
            "sensor_id": unknown,
            "ts": "2024-07-01T00:00:00",
            "value": "2",
        },
        {
            "reading_id": f"{PREFIX}r3",
            "sensor_id": known,
            "ts": "2024-07-01T01:00:00",
            "value": "3",
        },
    ]

    total, skipped = _run_in_batches(driver, database, iter([batch]), query)

    assert (total, skipped) == (3, 1)
    records, _, _ = driver.execute_query(
        """
        MATCH (r:Reading) WHERE r.sensor_id STARTS WITH $prefix
        OPTIONAL MATCH (s:Sensor)-[:HAS_READING]->(r)
        RETURN r.reading_id AS reading, s.sensor_id AS sensor ORDER BY reading
        """,
        prefix=PREFIX,
        database_=database,
    )
    assert [(r["reading"], r["sensor"]) for r in records] == [
        (f"{PREFIX}r1", known),
        (f"{PREFIX}r3", known),
    ]
