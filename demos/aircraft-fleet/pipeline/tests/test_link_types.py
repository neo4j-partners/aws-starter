"""Reference nodes and operating limits link on exact type, ignoring case.

This test writes to Neo4j, so it runs only when NEO4J_TEST_URI points at a
local server. Set NEO4J_TEST_PASSWORD, and optionally NEO4J_TEST_USERNAME
and NEO4J_TEST_DATABASE. link_to_existing_graph links across the whole
database, so the tests skip unless it holds only their own nodes. They
remove the nodes they create.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
from neo4j import Driver, GraphDatabase

from populate_aircraft_db.pipeline import link_to_existing_graph

TEST_URI = os.environ.get("NEO4J_TEST_URI", "")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
MODEL = "PYTEST-LINK"

pytestmark = pytest.mark.skipif(not TEST_URI, reason="NEO4J_TEST_URI is not set")

# One aircraft with an Engine (Turbine, Control Unit) and Hydraulics (Pump).
_SETUP = """
CREATE (a:Aircraft {aircraft_id: $model + '-A', model: $model})
CREATE (a)-[:HAS_SYSTEM]->(e:System {system_id: $model + '-E', type: 'Engine'})
CREATE (a)-[:HAS_SYSTEM]->(h:System {system_id: $model + '-H', type: 'Hydraulics'})
CREATE (e)-[:HAS_COMPONENT]->(:Component {component_id: $model + '-E1', type: 'Turbine', name: 'Turbine'})
CREATE (e)-[:HAS_COMPONENT]->(:Component {component_id: $model + '-E2', type: 'Control Unit', name: 'Control Unit'})
CREATE (h)-[:HAS_COMPONENT]->(:Component {component_id: $model + '-H1', type: 'Pump', name: 'Pump'})
WITH 1 AS _
UNWIND $systems AS sr
CREATE (n:SystemReference {name: sr.name + ' - ' + $model, aircraftType: $model})
SET n.systemType = sr.type
WITH count(*) AS _
UNWIND $components AS cr
CREATE (n:ComponentReference {name: cr.name + ' - ' + $model, aircraftType: $model})
SET n.componentType = cr.type
"""

_SYSTEMS = [
    {"name": "Engine", "type": "engine"},
    {"name": "Fuel System", "type": "Fuel"},
    {"name": "Hydraulics", "type": None},
]
_COMPONENTS = [
    {"name": "High-Pressure Turbine", "type": "turbine"},
    {"name": "FADEC", "type": "Control Unit"},
    {"name": "Engine-Driven Pump", "type": "PUMP"},
    {"name": "Fuel Pump", "type": "Fuel Pump"},
    {"name": "Turbine", "type": None},
    # The type decides the link, not the name.
    {"name": "Control Unit", "type": "Turbine"},
]


@pytest.fixture
def driver() -> Iterator[Driver]:
    assert urlparse(TEST_URI).hostname in LOCAL_HOSTS, "link tests only run against localhost"
    auth = (os.environ.get("NEO4J_TEST_USERNAME", "neo4j"), os.environ["NEO4J_TEST_PASSWORD"])
    with GraphDatabase.driver(TEST_URI, auth=auth) as drv:
        yield drv


# Matches every node the tests create.
_TEST_NODE = """
n.model = $model OR n.aircraftType STARTS WITH $model
OR n.system_id STARTS WITH $model OR n.component_id STARTS WITH $model
OR n.sensor_id STARTS WITH $model
"""


def _skip_unless_only_test_nodes(driver: Driver, database: str) -> None:
    records, _, _ = driver.execute_query(
        # A missing property makes the predicate null, so treat null as false.
        f"MATCH (n) WHERE NOT coalesce(({_TEST_NODE}), false) RETURN count(n) AS count",
        model=MODEL,
        database_=database,
    )
    if records[0]["count"]:
        pytest.skip(f"database {database!r} holds nodes the link tests did not create")


@pytest.fixture
def database(driver: Driver) -> Iterator[str]:
    db = os.environ.get("NEO4J_TEST_DATABASE", "neo4j")
    _skip_unless_only_test_nodes(driver, db)
    cleanup = f"MATCH (n) WHERE {_TEST_NODE} DETACH DELETE n"
    driver.execute_query(cleanup, model=MODEL, database_=db)
    yield db
    driver.execute_query(cleanup, model=MODEL, database_=db)


def test_references_link_on_exact_type(driver: Driver, database: str) -> None:
    driver.execute_query(
        _SETUP, model=MODEL, systems=_SYSTEMS, components=_COMPONENTS, database_=database
    )

    link_to_existing_graph(driver, database)

    records, _, _ = driver.execute_query(
        """
        MATCH (r)-[:DESCRIBES_SYSTEM|DESCRIBES_COMPONENT]->(t)
        WHERE r.aircraftType = $model
        RETURN r.name AS ref, coalesce(t.component_id, t.system_id) AS target
        ORDER BY ref
        """,
        model=MODEL,
        database_=database,
    )
    assert [(r["ref"], r["target"]) for r in records] == [
        (f"Control Unit - {MODEL}", f"{MODEL}-E1"),
        (f"Engine - {MODEL}", f"{MODEL}-E"),
        (f"Engine-Driven Pump - {MODEL}", f"{MODEL}-H1"),
        (f"FADEC - {MODEL}", f"{MODEL}-E2"),
        (f"High-Pressure Turbine - {MODEL}", f"{MODEL}-E1"),
    ]


# One aircraft with an engine EGT sensor, and operating limits.
_SENSOR_SETUP = """
CREATE (a:Aircraft {aircraft_id: $model + '-A', model: $model})
CREATE (a)-[:HAS_SYSTEM]->(e:System {system_id: $model + '-E', type: 'Engine'})
CREATE (e)-[:HAS_SENSOR]->(:Sensor {sensor_id: $model + '-SN1', type: 'EGT'})
WITH 1 AS _
UNWIND $limits AS ol
CREATE (:OperatingLimit {name: ol.name, parameterName: ol.parameter, aircraftType: ol.model})
"""

_LIMITS = [
    {"name": "EGT exact", "parameter": "EGT", "model": MODEL},
    {"name": "EGT lower", "parameter": "egt", "model": MODEL},
    {"name": "Vibration", "parameter": "Vibration", "model": MODEL},
    {"name": "EGT other model", "parameter": "EGT", "model": MODEL + "-OTHER"},
]


def test_sensor_links_to_limits_on_parameter_name_ignoring_case(
    driver: Driver, database: str
) -> None:
    driver.execute_query(_SENSOR_SETUP, model=MODEL, limits=_LIMITS, database_=database)

    link_to_existing_graph(driver, database)

    records, _, _ = driver.execute_query(
        """
        MATCH (s:Sensor)-[:HAS_LIMIT]->(ol:OperatingLimit)
        WHERE s.sensor_id STARTS WITH $model
        RETURN ol.name AS limit
        ORDER BY limit
        """,
        model=MODEL,
        database_=database,
    )
    assert [r["limit"] for r in records] == ["EGT exact", "EGT lower"]


def test_a_database_with_other_nodes_is_skipped(driver: Driver, database: str) -> None:
    driver.execute_query("CREATE (:PytestForeign)", database_=database)
    try:
        with pytest.raises(pytest.skip.Exception, match="did not create"):
            _skip_unless_only_test_nodes(driver, database)
    finally:
        driver.execute_query("MATCH (n:PytestForeign) DELETE n", database_=database)
    _skip_unless_only_test_nodes(driver, database)
