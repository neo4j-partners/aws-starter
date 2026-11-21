"""agent_samples: Cypher extraction and read-only execution of generated Cypher."""

from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
from neo4j import Driver, GraphDatabase

from generator.config import GeneratorConfig
from generator.fleet import generate_fleet
from generator.specs import AIRPORTS, MODEL_DISTRIBUTION, OPERATORS
from populate_aircraft_db.agent_samples import (
    GRAPH_SCHEMA,
    _extract_cypher,
    _run_text2cypher,
)

TEST_URI = os.environ.get("NEO4J_TEST_URI", "")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
LABEL = "PytestAgentWrite"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MATCH (n) RETURN n", "MATCH (n) RETURN n"),
        ("Here is the query:\nMATCH (n)\nRETURN n", "MATCH (n)\nRETURN n"),
        ("```cypher\nMATCH (n) RETURN n\n```\nDone.", "MATCH (n) RETURN n"),
    ],
)
def test_extract_cypher(raw: str, expected: str) -> None:
    assert _extract_cypher(raw) == expected


def test_extract_cypher_does_not_start_at_a_write_clause() -> None:
    raw = "Sure.\nCREATE (n:X)"
    assert _extract_cypher(raw) == raw


def _prompt_line(label: str) -> list[str]:
    """Return the comma-separated items on the prompt line that starts with label."""
    return GRAPH_SCHEMA.split(f"\n{label}: ")[1].split(".\n")[0].split(", ")


def test_prompt_names_every_model_operator_and_airport() -> None:
    assert _prompt_line("Aircraft models") == [model for model, _ in MODEL_DISTRIBUTION]
    assert _prompt_line("Operators") == [operator.name for operator in OPERATORS]
    assert _prompt_line("Airport IATA codes") == [airport.iata for airport in AIRPORTS]


def test_prompt_sample_tails_are_in_the_smallest_full_fleet() -> None:
    fleet = {(ac.tail_number, ac.model) for ac in generate_fleet(GeneratorConfig(n_aircraft=5))}
    entries = _prompt_line("Sample tail numbers")
    samples = {tuple(entry.rstrip(")").split(" (")) for entry in entries}
    assert samples == fleet


@pytest.fixture
def driver() -> Iterator[Driver]:
    if not TEST_URI:
        pytest.skip("NEO4J_TEST_URI is not set")
    assert urlparse(TEST_URI).hostname in LOCAL_HOSTS, "write tests only run against localhost"
    auth = (os.environ.get("NEO4J_TEST_USERNAME", "neo4j"), os.environ["NEO4J_TEST_PASSWORD"])
    with GraphDatabase.driver(TEST_URI, auth=auth) as drv:
        yield drv


def test_generated_write_is_rejected(driver: Driver, capsys: pytest.CaptureFixture[str]) -> None:
    database = os.environ.get("NEO4J_TEST_DATABASE", "neo4j")
    count = f"MATCH (n:{LABEL}) RETURN count(n) AS n"
    cleanup = f"MATCH (n:{LABEL}) DETACH DELETE n"
    driver.execute_query(cleanup, database_=database)
    try:
        _run_text2cypher(
            driver, database, lambda _system, _user: f"CREATE (:{LABEL})", "Add a node"
        )
        records, _, _ = driver.execute_query(count, database_=database)
        assert records[0]["n"] == 0
        assert "[ERROR] Cypher execution failed" in capsys.readouterr().out
    finally:
        driver.execute_query(cleanup, database_=database)
