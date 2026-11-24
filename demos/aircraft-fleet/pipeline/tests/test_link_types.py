"""Reference nodes link on exact type, ignoring case, and limits are left alone.

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

# One aircraft with an Engine (HP Turbine, Main Fuel Pump), Avionics (Air
# Data Unit), and Hydraulics (Hydraulic Pump).
_SETUP = """
CREATE (a:Aircraft {aircraft_id: $model + '-A', model: $model})
CREATE (a)-[:HAS_SYSTEM]->(e:System {system_id: $model + '-E', type: 'Engine'})
CREATE (a)-[:HAS_SYSTEM]->(v:System {system_id: $model + '-V', type: 'Avionics'})
CREATE (a)-[:HAS_SYSTEM]->(h:System {system_id: $model + '-H', type: 'Hydraulics'})
CREATE (e)-[:HAS_COMPONENT]->(:Component {component_id: $model + '-E1', type: 'HP Turbine', name: 'High-Pressure Turbine'})
CREATE (e)-[:HAS_COMPONENT]->(:Component {component_id: $model + '-E2', type: 'Main Fuel Pump', name: 'Main Fuel Pump'})
CREATE (v)-[:HAS_COMPONENT]->(:Component {component_id: $model + '-V1', type: 'Air Data Unit', name: 'ADIRU'})
CREATE (h)-[:HAS_COMPONENT]->(:Component {component_id: $model + '-H1', type: 'Hydraulic Pump', name: 'Engine-Driven Pump'})
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
    # Spaces around the system type are ignored too.
    {"name": "Hydraulic Power", "type": " Hydraulics "},
]
_COMPONENTS = [
    {"name": "High-Pressure Turbine", "type": "hp turbine"},
    {"name": "Engine Fuel Pump", "type": "Main Fuel Pump"},
    {"name": "Engine-Driven Pump", "type": "HYDRAULIC PUMP"},
    # A manual name is an alias of its type.
    {"name": "Air Data Inertial Reference Unit", "type": "ADIRU"},
    {"name": "Turbine Stage", "type": "High-Pressure Turbine"},
    # Spaces around the type are ignored.
    {"name": "Padded Turbine", "type": " HP Turbine "},
    # No type, and types outside the vocabulary, link to nothing.
    {"name": "Fuel Filter", "type": "Fuel Filter"},
    {"name": "Fuel Nozzle", "type": "Nozzle"},
    {"name": "HP Turbine", "type": None},
    # The type decides the link, not the name.
    {"name": "Main Fuel Pump", "type": "HP Turbine"},
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
        (f"Air Data Inertial Reference Unit - {MODEL}", f"{MODEL}-V1"),
        (f"Engine - {MODEL}", f"{MODEL}-E"),
        (f"Engine Fuel Pump - {MODEL}", f"{MODEL}-E2"),
        (f"Engine-Driven Pump - {MODEL}", f"{MODEL}-H1"),
        (f"High-Pressure Turbine - {MODEL}", f"{MODEL}-E1"),
        (f"Hydraulic Power - {MODEL}", f"{MODEL}-H"),
        (f"Main Fuel Pump - {MODEL}", f"{MODEL}-E1"),
        (f"Padded Turbine - {MODEL}", f"{MODEL}-E1"),
        (f"Turbine Stage - {MODEL}", f"{MODEL}-E1"),
    ]


# The same aircraft, with component references under system references.
_PARENT_SETUP = """
CREATE (a:Aircraft {aircraft_id: $model + '-A', model: $model})
CREATE (a)-[:HAS_SYSTEM]->(e:System {system_id: $model + '-E', type: 'Engine'})
CREATE (a)-[:HAS_SYSTEM]->(h:System {system_id: $model + '-H', type: 'Hydraulics'})
CREATE (e)-[:HAS_COMPONENT]->(:Component {component_id: $model + '-E2', type: 'Main Fuel Pump', name: 'Main Fuel Pump'})
CREATE (h)-[:HAS_COMPONENT]->(:Component {component_id: $model + '-H1', type: 'Hydraulic Pump', name: 'Main Hydraulic Pump'})
WITH 1 AS _
UNWIND $parents AS parent
CREATE (sr:SystemReference {name: parent.name + ' - ' + $model, aircraftType: $model})
SET sr.systemType = parent.type
WITH sr, parent
UNWIND parent.components AS cr
CREATE (sr)-[:HAS_COMPONENT]->(n:ComponentReference {
    name: cr.name + ' - ' + $model, aircraftType: $model, componentType: cr.type
})
"""

_PARENTS = [
    {
        "name": "Engine",
        "type": "Engine",
        "components": [
            {"name": "Fuel Pump", "type": "Main Fuel Pump"},
            # A pump typed for another system than its parent links nowhere.
            {"name": "Engine-Driven Pump", "type": "Hydraulic Pump"},
        ],
    },
    {
        "name": "Hydraulic System",
        "type": "Hydraulics",
        "components": [{"name": "Main Hydraulic Pump", "type": "Hydraulic Pump"}],
    },
    {
        # A parent without a fleet system type does not block the link.
        "name": "Fuel System",
        "type": None,
        "components": [{"name": "Boost Pump", "type": "Hydraulic Pump"}],
    },
    {
        # Nor does a parent whose type is outside the fleet system types.
        "name": "Fuel Feed",
        "type": "Fuel",
        "components": [{"name": "Main Fuel Pump", "type": "Main Fuel Pump"}],
    },
    {
        # A padded fleet type still counts, so it blocks the fuel pump and
        # passes the hydraulic pump.
        "name": "Padded Hydraulics",
        "type": "Hydraulics ",
        "components": [
            {"name": "Misfiled Fuel Pump", "type": "Main Fuel Pump"},
            {"name": "Padded Parent Pump", "type": "Hydraulic Pump"},
        ],
    },
]

# A pump that the manuals list under both the engine and the hydraulic
# system, as the E190 Engine-Driven Pump is. One matching parent is enough.
_SHARED_PARENTS = """
MATCH (e:SystemReference {name: 'Engine - ' + $model})
MATCH (h:SystemReference {name: 'Hydraulic System - ' + $model})
CREATE (e)-[:HAS_COMPONENT]->(n:ComponentReference {
    name: 'Shared Engine-Driven Pump - ' + $model, aircraftType: $model,
    componentType: 'Hydraulic Pump'
})<-[:HAS_COMPONENT]-(h)
"""


def test_component_links_only_within_its_parent_system_type(driver: Driver, database: str) -> None:
    driver.execute_query(_PARENT_SETUP, model=MODEL, parents=_PARENTS, database_=database)
    driver.execute_query(_SHARED_PARENTS, model=MODEL, database_=database)

    link_to_existing_graph(driver, database)

    records, _, _ = driver.execute_query(
        """
        MATCH (r:ComponentReference)-[:DESCRIBES_COMPONENT]->(c)
        WHERE r.aircraftType = $model
        RETURN r.name AS ref, c.component_id AS target
        ORDER BY ref
        """,
        model=MODEL,
        database_=database,
    )
    assert [(r["ref"], r["target"]) for r in records] == [
        (f"Boost Pump - {MODEL}", f"{MODEL}-H1"),
        (f"Fuel Pump - {MODEL}", f"{MODEL}-E2"),
        (f"Main Fuel Pump - {MODEL}", f"{MODEL}-E2"),
        (f"Main Hydraulic Pump - {MODEL}", f"{MODEL}-H1"),
        (f"Padded Parent Pump - {MODEL}", f"{MODEL}-H1"),
        (f"Shared Engine-Driven Pump - {MODEL}", f"{MODEL}-H1"),
    ]


# One aircraft with an engine EGT sensor, linked to one of two loaded limits.
_SENSOR_SETUP = """
CREATE (a:Aircraft {aircraft_id: $model + '-A', model: $model})
CREATE (a)-[:HAS_SYSTEM]->(e:System {system_id: $model + '-E', type: 'Engine'})
CREATE (e)-[:HAS_SENSOR]->(s:Sensor {sensor_id: $model + '-SN1', type: 'EGT'})
CREATE (s)-[:HAS_LIMIT]->(:OperatingLimit {
    name: 'EGT Takeoff - ' + $model, parameterName: 'EGT', aircraftType: $model,
    maxValue: 890.0
})
CREATE (:OperatingLimit {
    name: 'EGT All - ' + $model, parameterName: 'EGT', aircraftType: $model
})
"""


def test_cross_links_leave_the_loaded_limits_alone(driver: Driver, database: str) -> None:
    """The load writes the limits and their sensor links, so enrich adds and drops none."""
    driver.execute_query(_SENSOR_SETUP, model=MODEL, database_=database)

    link_to_existing_graph(driver, database)

    records, _, _ = driver.execute_query(
        """
        MATCH (ol:OperatingLimit) WHERE ol.aircraftType = $model
        OPTIONAL MATCH (s:Sensor)-[:HAS_LIMIT]->(ol)
        RETURN ol.name AS limit, count(s) AS sensors
        ORDER BY limit
        """,
        model=MODEL,
        database_=database,
    )
    assert [(r["limit"], r["sensors"]) for r in records] == [
        (f"EGT All - {MODEL}", 0),
        (f"EGT Takeoff - {MODEL}", 1),
    ]


def test_a_database_with_other_nodes_is_skipped(driver: Driver, database: str) -> None:
    driver.execute_query("CREATE (:PytestForeign)", database_=database)
    try:
        with pytest.raises(pytest.skip.Exception, match="did not create"):
            _skip_unless_only_test_nodes(driver, database)
    finally:
        driver.execute_query("MATCH (n:PytestForeign) DELETE n", database_=database)
    # A skip here would hide a regression, so it fails the test instead.
    try:
        _skip_unless_only_test_nodes(driver, database)
    except pytest.skip.Exception:
        pytest.fail("clean database was skipped")
