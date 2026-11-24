"""Enrich links each limit to the chunks that hold its source text.

This test writes to Neo4j, so it runs only when NEO4J_TEST_URI points at a
local server. Set NEO4J_TEST_PASSWORD, and optionally NEO4J_TEST_USERNAME
and NEO4J_TEST_DATABASE. verify counts limits across the whole database, so
the tests skip unless it holds only their own nodes. They remove the nodes
they create.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
from neo4j import Driver, GraphDatabase

from populate_aircraft_db import loader
from populate_aircraft_db.pipeline import LimitSource, check_limit_nodes, link_limits_to_chunks

TEST_URI = os.environ.get("NEO4J_TEST_URI", "")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
MODEL = "PYTEST-LIMIT"
DOC = f"{MODEL}-DOC"
OTHER_DOC = f"{MODEL}-OTHER"

pytestmark = pytest.mark.skipif(not TEST_URI, reason="NEO4J_TEST_URI is not set")

# Chunk ranges in DOC overlap by 20 characters. c2's text starts with a
# repeated table header, so its range starts after the header at 180.
# OTHER_DOC has one chunk over the same offsets.
_SETUP = """
CREATE (d:Document {documentId: $doc})
CREATE (o:Document {documentId: $other})
CREATE (:Chunk {chunkId: $doc + '-c0', startOffset: 0, endOffset: 100})-[:FROM_DOCUMENT]->(d)
CREATE (:Chunk {chunkId: $doc + '-c1', startOffset: 80, endOffset: 200})-[:FROM_DOCUMENT]->(d)
CREATE (:Chunk {chunkId: $doc + '-c2', startOffset: 180, endOffset: 300})-[:FROM_DOCUMENT]->(d)
CREATE (:Chunk {chunkId: $other + '-c0', startOffset: 0, endOffset: 300})-[:FROM_DOCUMENT]->(o)
WITH 1 AS _
UNWIND $names AS name
CREATE (:OperatingLimit {name: name, aircraftType: $model})
"""

_SOURCES = [
    # Two chunks hold it whole, in their overlap.
    LimitSource("Held Twice", DOC, 85, 95),
    # No chunk holds it whole, so both chunks it overlaps link.
    LimitSource("Split", DOC, 50, 150),
    # Only c1 holds it. c2 repeats the header above it, outside its range.
    LimitSource("Under Header", DOC, 150, 170),
    # Past the last chunk, as in a sampled run.
    LimitSource("Unchunked", DOC, 400, 410),
]


@pytest.fixture
def driver() -> Iterator[Driver]:
    assert urlparse(TEST_URI).hostname in LOCAL_HOSTS, "limit tests only run against localhost"
    auth = (os.environ.get("NEO4J_TEST_USERNAME", "neo4j"), os.environ["NEO4J_TEST_PASSWORD"])
    with GraphDatabase.driver(TEST_URI, auth=auth) as drv:
        yield drv


# Matches every node the tests create.
_TEST_NODE = """
n.aircraftType = $model OR n.documentId STARTS WITH $model OR n.chunkId STARTS WITH $model
"""


@pytest.fixture
def database(driver: Driver) -> Iterator[str]:
    db = os.environ.get("NEO4J_TEST_DATABASE", "neo4j")
    records, _, _ = driver.execute_query(
        # A missing property makes the predicate null, so treat null as false.
        f"MATCH (n) WHERE NOT coalesce(({_TEST_NODE}), false) RETURN count(n) AS count",
        model=MODEL,
        database_=db,
    )
    if records[0]["count"]:
        pytest.skip(f"database {db!r} holds nodes the limit tests did not create")
    cleanup = f"MATCH (n) WHERE {_TEST_NODE} DETACH DELETE n"
    driver.execute_query(cleanup, model=MODEL, database_=db)
    yield db
    driver.execute_query(cleanup, model=MODEL, database_=db)


def _setup(driver: Driver, database: str) -> None:
    driver.execute_query(
        _SETUP,
        doc=DOC,
        other=OTHER_DOC,
        model=MODEL,
        names=[s.name for s in _SOURCES],
        database_=database,
    )


def _links(driver: Driver, database: str) -> dict[str, list[str]]:
    records, _, _ = driver.execute_query(
        """
        MATCH (ol:OperatingLimit {aircraftType: $model})
        OPTIONAL MATCH (ol)-[:FROM_CHUNK]->(c:Chunk)
        WITH ol, c ORDER BY c.chunkId
        RETURN ol.name AS name, collect(c.chunkId) AS chunks
        """,
        model=MODEL,
        database_=database,
    )
    return {r["name"]: r["chunks"] for r in records}


def test_limits_link_to_the_chunks_that_hold_their_source(driver: Driver, database: str) -> None:
    _setup(driver, database)

    link_limits_to_chunks(driver, database, _SOURCES)
    # A second run adds no links.
    link_limits_to_chunks(driver, database, _SOURCES)

    assert _links(driver, database) == {
        "Held Twice": [f"{DOC}-c0", f"{DOC}-c1"],
        "Split": [f"{DOC}-c0", f"{DOC}-c1"],
        "Under Header": [f"{DOC}-c1"],
        "Unchunked": [],
    }
    records, _, _ = driver.execute_query(
        "MATCH (:OperatingLimit)-[r:FROM_CHUNK]->() RETURN count(r) AS count",
        database_=database,
    )
    assert records[0]["count"] == 5

    result = loader._VerifyResult(strict=True)
    loader._check_limit_chunks(driver, database, {"OperatingLimit", "Chunk"}, result)
    assert result.failures == [f"OperatingLimits without Chunk: 1 ({MODEL} 1)"]


def test_a_limit_with_no_node_raises(driver: Driver, database: str) -> None:
    _setup(driver, database)

    check_limit_nodes(driver, database, _SOURCES)
    with pytest.raises(ValueError, match="1 limit\\(s\\) in operating_limits.csv"):
        check_limit_nodes(driver, database, [*_SOURCES, LimitSource("Missing", DOC, 0, 1)])


def test_an_extracted_limit_does_not_count_as_loaded(driver: Driver, database: str) -> None:
    """An older enrich extracted limits with these labels, and the clear deletes them."""
    _setup(driver, database)

    for label in ("__Entity__", "__KGBuilder__"):
        driver.execute_query(
            f"MATCH (ol:OperatingLimit {{name: 'Split'}}) SET ol:{label}", database_=database
        )
        with pytest.raises(ValueError, match="1 limit\\(s\\) in operating_limits.csv"):
            check_limit_nodes(driver, database, _SOURCES)
        driver.execute_query(
            f"MATCH (ol:OperatingLimit {{name: 'Split'}}) REMOVE ol:{label}", database_=database
        )
