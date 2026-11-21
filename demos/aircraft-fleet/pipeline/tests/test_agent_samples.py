"""agent_samples: schema description, Cypher extraction, and read-only execution."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import pytest
from neo4j import (
    READ_ACCESS,
    Driver,
    GraphDatabase,
    NotificationDisabledClassification,
    Query,
    RoutingControl,
)

from generator.config import GeneratorConfig
from generator.fleet import generate_fleet
from generator.specs import (
    COMPONENT_TYPES_BY_SYSTEM,
    DELAY_CAUSES,
    EVENT_SEVERITIES,
    SENSOR_TYPES,
)
from populate_aircraft_db import agent_samples
from populate_aircraft_db.agent_samples import (
    SAMPLE_QUESTIONS,
    _extract_cypher,
    _run_text2cypher,
    graph_schema,
    run_agent_samples,
    system_prompt,
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


class SchemaDriver:
    """Answer the schema and fact queries with fixed rows and any other query with none."""

    def __init__(
        self,
        property_rows: list[tuple[list[str], str]] = (),
        relationship_rows: list[tuple[list[str], str, list[str]]] = (),
        models: list[str] = (),
        tail_rows: list[tuple[str, str]] = (),
        operators: list[str] = (),
        airports: list[str] = (),
    ) -> None:
        self.rows = {
            agent_samples._NODE_PROPERTIES_Q: [
                {"nodeLabels": labels, "propertyName": name} for labels, name in property_rows
            ],
            agent_samples._RELATIONSHIPS_Q: [
                {"from_labels": a, "type": rel, "to_labels": b} for a, rel, b in relationship_rows
            ],
            agent_samples._MODELS_Q: [{"model": model} for model in models],
            agent_samples._SAMPLE_TAILS_Q: [
                {"model": model, "tail": tail} for model, tail in tail_rows
            ],
            agent_samples._OPERATORS_Q: [{"operator": name} for name in operators],
            agent_samples._AIRPORTS_Q: [{"iata": code} for code in airports],
        }
        self.session_configs: list[dict[str, Any]] = []

    def session(self, **config: Any) -> _SchemaSession:
        self.session_configs.append(config)
        return _SchemaSession(self)

    def execute_query(self, cypher: str, /, **params: Any) -> tuple[list[dict], None, None]:
        return [], None, None


class _SchemaSession:
    def __init__(self, driver: SchemaDriver) -> None:
        self.driver = driver

    def __enter__(self) -> _SchemaSession:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def run(self, cypher: str) -> SimpleNamespace:
        if cypher not in self.driver.rows:
            raise AssertionError(f"unexpected schema query: {cypher}")
        rows = self.driver.rows[cypher]
        return SimpleNamespace(data=lambda: rows)


def _prompt_line(schema: str, label: str) -> list[str]:
    """Return the comma-separated items on the prompt line that starts with label."""
    return schema.split(f"\n{label}: ")[1].split(".\n")[0].split(", ")


def test_prompt_takes_models_tails_operators_and_airports_from_the_database() -> None:
    driver = SchemaDriver(
        models=["B737-800", "E190"],
        tail_rows=[("B737-800", "N1TEST"), ("E190", "N2TEST")],
        operators=["TestAir"],
        airports=["ZZA", "ZZB"],
    )

    schema = graph_schema(driver, "db")

    assert _prompt_line(schema, "Aircraft models") == ["B737-800", "E190"]
    assert _prompt_line(schema, "Sample tail numbers") == ["N1TEST (B737-800)", "N2TEST (E190)"]
    assert _prompt_line(schema, "Operators") == ["TestAir"]
    assert _prompt_line(schema, "Airport IATA codes") == ["ZZA", "ZZB"]


def test_prompt_leaves_out_facts_the_database_does_not_have() -> None:
    schema = graph_schema(SchemaDriver(), "db")

    assert "Aircraft models" not in schema
    assert "Sample tail numbers" not in schema
    assert "Operators" not in schema
    assert "Airport IATA codes" not in schema


def _fleet_tails(n_aircraft: int) -> dict[str, str]:
    """Return tail number -> model for a generated fleet of n_aircraft."""
    return {
        ac.tail_number: ac.model for ac in generate_fleet(GeneratorConfig(n_aircraft=n_aircraft))
    }


def _question_tails(question: str) -> list[str]:
    return re.findall(r"\bN\d{4,5}[A-Z]?\b", question)


def test_sample_question_tails_are_in_the_smallest_fleet_that_holds_them() -> None:
    tails = {tail for sample in SAMPLE_QUESTIONS for tail in _question_tails(sample.question)}
    assert tails
    assert tails <= _fleet_tails(6).keys()
    assert not tails <= _fleet_tails(5).keys()


def test_shared_faults_question_pairs_two_tails_of_one_model() -> None:
    # Manual Fault nodes are per aircraft model, so tails of two models
    # never share one.
    (question,) = [sq.question for sq in SAMPLE_QUESTIONS if sq.category == "Shared Faults"]
    first, second = _question_tails(question)
    models = _fleet_tails(6)
    assert first != second
    assert models[first] == models[second]


def test_schema_lists_labels_and_relationships_without_internal_labels() -> None:
    driver = SchemaDriver(
        property_rows=[
            (["Chunk", "__KGBuilder__"], "text"),
            (["Chunk", "__KGBuilder__"], "chunkId"),
            (["__KGBuilder__", "Chunk"], "index"),
            (["__Entity__"], "hidden"),
            (["Sensor", "Calibrated"], "sensor_id"),
            (["Aircraft"], "tail_number"),
            (["Aircraft"], "aircraft_id"),
        ],
        relationship_rows=[
            (["Chunk", "__KGBuilder__"], "NEXT_CHUNK", ["__KGBuilder__", "Chunk"]),
            (["__KGBuilder__", "Chunk"], "NEXT_CHUNK", ["Chunk", "__KGBuilder__"]),
            (["Fault", "__Entity__", "__KGBuilder__"], "FROM_CHUNK", ["Chunk", "__KGBuilder__"]),
            (["__Entity__"], "HIDDEN", ["Chunk"]),
            (["Chunk"], "HIDDEN", ["__Entity__"]),
            (["Aircraft"], "HAS_SYSTEM", ["System"]),
        ],
    )

    schema = graph_schema(driver, "db")

    assert schema == (
        "Node labels and properties:\n"
        "- Aircraft {aircraft_id, tail_number}\n"
        "- Calibrated:Sensor {sensor_id}\n"
        '- Chunk {chunkId, index, text}  (chunkId: "{documentId}:{index}")\n'
        "\n"
        "Relationships:\n"
        "- (Aircraft)-[:HAS_SYSTEM]->(System)\n"
        "- (Chunk)-[:NEXT_CHUNK]->(Chunk)\n"
        "- (Fault)-[:FROM_CHUNK]->(Chunk)\n"
    )


@pytest.mark.parametrize(
    ("label", "prop", "values"),
    [
        ("System", "type", list(COMPONENT_TYPES_BY_SYSTEM)),
        ("Sensor", "type", [sensor_type for sensor_type, _, _ in SENSOR_TYPES]),
        ("Delay", "cause", DELAY_CAUSES),
        ("MaintenanceEvent", "severity", EVENT_SEVERITIES),
    ],
)
def test_schema_value_hints_come_from_the_generator_specs(
    label: str, prop: str, values: list[str]
) -> None:
    schema = graph_schema(SchemaDriver(property_rows=[([label], prop)]), "db")

    assert f"- {label} {{{prop}}}  ({prop}: {', '.join(values)})\n" in schema


def test_schema_is_read_in_a_read_session_without_generic_notifications() -> None:
    driver = SchemaDriver()

    graph_schema(driver, "db")

    assert driver.session_configs == [
        {
            "database": "db",
            "default_access_mode": READ_ACCESS,
            "notifications_disabled_classifications": [NotificationDisabledClassification.GENERIC],
        }
    ]


def test_run_agent_samples_sends_the_schema_prompt_with_every_cypher_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = {
        "property_rows": [(["Aircraft"], "tail_number")],
        "relationship_rows": [(["Aircraft"], "HAS_SYSTEM", ["System"])],
    }
    chats: list[tuple[str, str]] = []

    def chat(system: str, user: str) -> str:
        chats.append((system, user))
        return "MATCH (n) RETURN n"

    monkeypatch.setattr(
        agent_samples, "_create_llm_client", lambda *args, **kwargs: (chat, lambda text: [0.1])
    )
    driver = SchemaDriver(**rows)

    run_agent_samples(
        driver,
        "db",
        provider="test",
        llm_model="model",
        embedding_model="embedder",
        embedding_dimensions=1,
    )

    prompt = system_prompt(graph_schema(SchemaDriver(**rows), "db"))
    cypher_questions = [sq.question for sq in SAMPLE_QUESTIONS if sq.tool == "text2cypher"]
    assert [user for system, user in chats if system == prompt] == cypher_questions
    assert [config["database"] for config in driver.session_configs] == ["db"]


def test_system_prompt_puts_the_schema_after_the_rules() -> None:
    prompt = system_prompt("SCHEMA")

    assert prompt.startswith("You are an expert Neo4j Cypher query generator")
    assert "\nRules:\n- Return ONLY the Cypher query text." in prompt
    assert prompt.endswith("\nGraph schema:\nSCHEMA")


class RecordingDriver:
    """Record each execute_query call and return no rows."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def execute_query(self, query: Any, /, **params: Any) -> tuple[list[dict], None, None]:
        self.calls.append((query, params))
        return [], None, None


def test_generated_cypher_runs_in_a_read_transaction() -> None:
    driver = RecordingDriver()

    _run_text2cypher(driver, "db", lambda _system, _user: "MATCH (n) RETURN n", "prompt", "q")

    ((_, params),) = driver.calls
    assert params == {"database_": "db", "routing_": RoutingControl.READ}


def test_generated_cypher_runs_with_a_timeout() -> None:
    driver = RecordingDriver()

    _run_text2cypher(driver, "db", lambda _system, _user: "MATCH (n) RETURN n", "prompt", "q")

    ((query, _),) = driver.calls
    assert isinstance(query, Query)
    assert query.text == "MATCH (n) RETURN n"
    assert query.timeout == 30


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
            driver,
            database,
            lambda _system, _user: f"CREATE (:{LABEL})",
            "prompt",
            "Add a node",
        )
        records, _, _ = driver.execute_query(count, database_=database)
        assert records[0]["n"] == 0
        assert "[ERROR] Cypher execution failed" in capsys.readouterr().out
    finally:
        driver.execute_query(cleanup, database_=database)


def test_graph_schema_reads_the_live_database(driver: Driver) -> None:
    database = os.environ.get("NEO4J_TEST_DATABASE", "neo4j")
    cleanup = """
    MATCH (n)
    WHERE n:PytestSchemaFrom OR n:PytestSchemaTo
       OR (n:Aircraft AND n.model = 'PYTEST-MODEL') OR (n:Airport AND n.iata = 'ZZQ')
    DETACH DELETE n
    """
    driver.execute_query(cleanup, database_=database)
    try:
        driver.execute_query(
            "CREATE (:PytestSchemaFrom:__PytestInternal__ {pytest_from: 1})"
            "-[:PYTEST_SCHEMA_LINK]->(:PytestSchemaTo {pytest_to: 2})",
            database_=database,
        )
        # The lowest aircraft_id of a model gives its sample tail.
        driver.execute_query(
            """
            CREATE (:Aircraft {aircraft_id: 'PYTEST-AC2', tail_number: 'N2PYT',
                               model: 'PYTEST-MODEL', operator: 'PytestAir'})
            CREATE (:Aircraft {aircraft_id: 'PYTEST-AC1', tail_number: 'N1PYT',
                               model: 'PYTEST-MODEL', operator: 'PytestAir'})
            CREATE (:Airport {iata: 'ZZQ'})
            """,
            database_=database,
        )

        schema = graph_schema(driver, database)
        lines = schema.splitlines()

        assert "- PytestSchemaFrom {pytest_from}" in lines
        assert "- PytestSchemaTo {pytest_to}" in lines
        assert "- (PytestSchemaFrom)-[:PYTEST_SCHEMA_LINK]->(PytestSchemaTo)" in lines
        assert not any("__PytestInternal__" in line for line in lines)
        assert "PYTEST-MODEL" in _prompt_line(schema, "Aircraft models")
        tails = _prompt_line(schema, "Sample tail numbers")
        assert "N1PYT (PYTEST-MODEL)" in tails
        assert "N2PYT (PYTEST-MODEL)" not in tails
        assert "PytestAir" in _prompt_line(schema, "Operators")
        assert "ZZQ" in _prompt_line(schema, "Airport IATA codes")
    finally:
        driver.execute_query(cleanup, database_=database)


def test_bedrock_embeds_with_the_configured_model_dimensions_and_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import boto3
    from neo4j_graphrag.embeddings import bedrock

    created: list[dict[str, Any]] = []

    class FakeEmbeddings:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

        def embed_query(self, text: str) -> list[float]:
            return [float(len(text))]

    monkeypatch.setattr(bedrock, "BedrockEmbeddings", FakeEmbeddings)
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: object())

    _, embed = agent_samples._create_llm_client(
        "bedrock",
        region="eu-west-1",
        llm_model="chat-model",
        embedding_model="embed-model",
        embedding_dimensions=256,
    )

    assert created == [{"model_id": "embed-model", "dimensions": 256, "region_name": "eu-west-1"}]
    assert embed("four") == [4.0]
