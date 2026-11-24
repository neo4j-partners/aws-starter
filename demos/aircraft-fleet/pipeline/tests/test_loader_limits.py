"""The limit load leaves the graph's OperatingLimits exactly the CSV's rows.

This test writes to Neo4j, so it runs only when NEO4J_TEST_URI points at a
local server. Set NEO4J_TEST_PASSWORD, and optionally NEO4J_TEST_USERNAME
and NEO4J_TEST_DATABASE. The load replaces every OperatingLimit and HAS_LIMIT
in the database, so the test skips unless the database starts empty, and it
deletes everything it created.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from neo4j import Driver, GraphDatabase

from generator.limits import LIMITS_FILE, operating_limit_rows
from generator.writers import write_csv
from populate_aircraft_db.loader import load_operating_limits

TEST_URI = os.environ.get("NEO4J_TEST_URI", "")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}

pytestmark = pytest.mark.skipif(not TEST_URI, reason="NEO4J_TEST_URI is not set")

ROWS = [
    row
    for row in operating_limit_rows()
    if row["aircraftType"] == "E190" and row["parameterName"] in {"EGT", "N2"}
]


@pytest.fixture
def driver() -> Iterator[Driver]:
    assert urlparse(TEST_URI).hostname in LOCAL_HOSTS, "loader tests only run against localhost"
    auth = (os.environ.get("NEO4J_TEST_USERNAME", "neo4j"), os.environ["NEO4J_TEST_PASSWORD"])
    with GraphDatabase.driver(TEST_URI, auth=auth) as drv:
        yield drv


@pytest.fixture
def database(driver: Driver) -> Iterator[str]:
    db = os.environ.get("NEO4J_TEST_DATABASE", "neo4j")
    records, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS count", database_=db)
    if records[0]["count"]:
        pytest.skip("the limit load replaces every OperatingLimit, so it needs an empty database")
    yield db
    driver.execute_query("MATCH (n) DETACH DELETE n", database_=db)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    write_csv(ROWS, tmp_path / LIMITS_FILE)
    return tmp_path


def _seed(driver: Driver, database: str) -> None:
    """An E190 with two sensors, plus the leftovers an earlier load or enrich left."""
    egt = next(row["name"] for row in ROWS if row["regime"] == "Takeoff")
    driver.execute_query(
        """
        CREATE (a:Aircraft {model: 'E190'})-[:HAS_SYSTEM]->(sys:System)
        CREATE (sys)-[:HAS_SENSOR]->(:Sensor {type: 'EGT'})
        CREATE (sys)-[:HAS_SENSOR]->(off:Sensor {type: 'AirDataDisagree'})
        CREATE (:OperatingLimit {name: 'EGT Exceedance - E190', maxValue: 1})
        CREATE (:OperatingLimit {parameterName: 'EGT'})
        CREATE (kept:OperatingLimit:__Entity__:__KGBuilder__ {
            name: $egt, maxValue: '890°C', source: 'chunk'
        })
        CREATE (:Chunk)-[:HAS_LIMIT]->(kept)
        CREATE (off)-[:HAS_LIMIT]->(kept)
        """,
        egt=egt,
        database_=database,
    )


def _limits(driver: Driver, database: str) -> list[dict]:
    records, _, _ = driver.execute_query(
        "MATCH (ol:OperatingLimit) RETURN ol {.*, labels: labels(ol)} AS ol ORDER BY ol.name",
        database_=database,
    )
    return [record["ol"] for record in records]


def _links(driver: Driver, database: str) -> list[tuple[list[str], str | None, str]]:
    records, _, _ = driver.execute_query(
        """
        MATCH (n)-[:HAS_LIMIT]->(ol)
        RETURN labels(n) AS labels, n.type AS type, ol.name AS limit
        ORDER BY limit
        """,
        database_=database,
    )
    return [(record["labels"], record["type"], record["limit"]) for record in records]


_VALUE_KEYS = ("minValue", "maxValue", "nominalValue")


def _expected_limits() -> list[dict]:
    def value(cell: str) -> float | None:
        return float(cell) if cell else None

    return sorted(
        (
            {
                "name": row["name"],
                "parameterName": row["parameterName"],
                "regime": row["regime"],
                "aircraftType": row["aircraftType"],
                "unit": row["unit"],
                **{key: value(row[key]) for key in _VALUE_KEYS if row[key]},
                "labels": ["OperatingLimit"],
            }
            for row in ROWS
        ),
        key=lambda limit: limit["name"],
    )


def test_load_replaces_leftover_limits_and_links(
    driver: Driver, database: str, data_dir: Path
) -> None:
    _seed(driver, database)

    load_operating_limits(driver, database, data_dir)

    limits = _limits(driver, database)
    assert limits == _expected_limits()
    assert all(
        isinstance(limit[key], float) for limit in limits for key in _VALUE_KEYS if key in limit
    )
    egt = sorted(row["name"] for row in ROWS if row["parameterName"] == "EGT")
    assert _links(driver, database) == [(["Sensor"], "EGT", name) for name in egt]


def test_a_second_load_changes_nothing(driver: Driver, database: str, data_dir: Path) -> None:
    _seed(driver, database)
    load_operating_limits(driver, database, data_dir)
    limits, links = _limits(driver, database), _links(driver, database)

    load_operating_limits(driver, database, data_dir)

    assert (_limits(driver, database), _links(driver, database)) == (limits, links)
