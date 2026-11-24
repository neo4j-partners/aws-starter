"""The loader records the generator stamp on a Dataset node, and verify reads it.

This test writes to Neo4j, so it runs only when NEO4J_TEST_URI points at a
local server. Set NEO4J_TEST_PASSWORD, and optionally NEO4J_TEST_USERNAME
and NEO4J_TEST_DATABASE. It removes every Dataset node in that database,
before and after each test.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from neo4j import Driver, GraphDatabase
from neo4j.exceptions import ConstraintError

from generator import stamp
from populate_aircraft_db import loader
from populate_aircraft_db.schema import create_constraints

TEST_URI = os.environ.get("NEO4J_TEST_URI", "")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
STAMP = {
    "config": {"aircraft": 30, "airports": 40, "days": 90, "seed": 42, "start_date": "2024-07-01"},
    "generator_hash": "abc123",
}

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
    cleanup = "MATCH (d:Dataset) DETACH DELETE d"
    driver.execute_query(cleanup, database_=db)
    yield db
    driver.execute_query(cleanup, database_=db)


@pytest.fixture
def no_csv_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the CSV loads, so only the Dataset node is written."""
    monkeypatch.setattr(loader, "load_nodes", lambda *args: 0)
    monkeypatch.setattr(loader, "load_relationships", lambda *args: None)
    monkeypatch.setattr(loader, "load_operating_limits", lambda *args: None)


def _datasets(driver: Driver, database: str) -> list[dict]:
    records, _, _ = driver.execute_query(
        "MATCH (d:Dataset) RETURN d.id AS id, d.generator_hash AS hash, d.stamp AS stamp",
        database_=database,
    )
    return [record.data() for record in records]


@pytest.mark.usefixtures("no_csv_load")
def test_load_replaces_the_dataset_node_with_the_current_stamp(
    driver: Driver, database: str, tmp_path: Path
) -> None:
    driver.execute_query("CREATE (:Dataset {generator_hash: 'old'})", database_=database)
    stamp.write_stamp(tmp_path, STAMP)

    loader.load_operational_graph(driver, database, tmp_path)

    (dataset,) = _datasets(driver, database)
    assert dataset["id"] == "current"
    assert dataset["hash"] == "abc123"
    assert json.loads(dataset["stamp"]) == STAMP


def test_the_schema_allows_one_current_dataset_node(driver: Driver, database: str) -> None:
    create_constraints(driver, database)
    driver.execute_query("CREATE (:Dataset {id: 'current'})", database_=database)

    with pytest.raises(ConstraintError):
        driver.execute_query("CREATE (:Dataset {id: 'current'})", database_=database)


@pytest.mark.usefixtures("no_csv_load")
def test_load_without_a_stamp_leaves_no_dataset_node(
    driver: Driver, database: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    driver.execute_query("CREATE (:Dataset {generator_hash: 'old'})", database_=database)

    with caplog.at_level(logging.WARNING):
        loader.load_operational_graph(driver, database, tmp_path)

    assert _datasets(driver, database) == []
    assert "has no .stamp.json, so the graph gets no Dataset node" in caplog.text


def test_a_failed_load_leaves_no_dataset_node(
    driver: Driver, database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The old node goes first, so a partial graph never claims a dataset.
    driver.execute_query("CREATE (:Dataset {generator_hash: 'old'})", database_=database)
    stamp.write_stamp(tmp_path, STAMP)

    def fail(*args: object) -> int:
        raise RuntimeError("load failed")

    monkeypatch.setattr(loader, "load_nodes", fail)

    with pytest.raises(RuntimeError, match="load failed"):
        loader.load_operational_graph(driver, database, tmp_path)

    assert _datasets(driver, database) == []


def test_a_graph_without_a_dataset_node_was_loaded_before_stamps(
    driver: Driver, database: str, tmp_path: Path
) -> None:
    stamp.write_stamp(tmp_path, STAMP)

    reason = loader.dataset_mismatch(driver, database, tmp_path)

    assert reason == (
        "the graph has no Dataset node (loaded before stamps, from unstamped CSVs,"
        " or a load did not finish)"
    )


@pytest.mark.usefixtures("no_csv_load")
def test_a_graph_loaded_from_the_current_stamp_matches(
    driver: Driver, database: str, tmp_path: Path
) -> None:
    stamp.write_stamp(tmp_path, STAMP)
    loader.load_operational_graph(driver, database, tmp_path)

    assert loader.dataset_mismatch(driver, database, tmp_path) is None


@pytest.mark.usefixtures("no_csv_load")
@pytest.mark.parametrize(
    ("changed", "differs"),
    [
        pytest.param({**STAMP, "generator_hash": "def456"}, "generator_hash", id="code"),
        pytest.param(
            {**STAMP, "config": {**STAMP["config"], "days": 365, "seed": 7}},
            "config.days, config.seed",
            id="config",
        ),
    ],
)
def test_a_graph_loaded_from_another_run_names_what_differs(
    driver: Driver, database: str, tmp_path: Path, changed: dict, differs: str
) -> None:
    stamp.write_stamp(tmp_path, STAMP)
    loader.load_operational_graph(driver, database, tmp_path)
    stamp.write_stamp(tmp_path, changed)

    reason = loader.dataset_mismatch(driver, database, tmp_path)

    assert reason == f"the graph was loaded from a run with a different {differs} than {tmp_path}"


def test_a_missing_local_stamp_skips_the_comparison(
    driver: Driver, database: str, tmp_path: Path
) -> None:
    # stale_reason already reports the missing stamp.
    driver.execute_query(
        "CREATE (:Dataset {generator_hash: 'abc123', stamp: $stamp})",
        stamp=json.dumps(STAMP),
        database_=database,
    )

    assert loader.dataset_mismatch(driver, database, tmp_path) is None


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param("CREATE (:Dataset {generator_hash: 'abc123'})", id="no-stamp-property"),
        pytest.param("CREATE (:Dataset {stamp: 'not json'})", id="unreadable"),
        pytest.param("CREATE (:Dataset {stamp: '[]'})", id="not-an-object"),
        pytest.param("CREATE (:Dataset), (:Dataset)", id="two-nodes"),
    ],
)
def test_an_unreadable_dataset_node_does_not_match(
    driver: Driver, database: str, tmp_path: Path, setup: str
) -> None:
    stamp.write_stamp(tmp_path, STAMP)
    driver.execute_query(setup, database_=database)

    reason = loader.dataset_mismatch(driver, database, tmp_path)

    assert reason is not None
    assert "Dataset node" in reason
