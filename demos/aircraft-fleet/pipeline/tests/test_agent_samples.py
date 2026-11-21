"""agent_samples: schema description, Cypher extraction, and read-only execution."""

from __future__ import annotations

import logging
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
from neo4j.exceptions import Forbidden, ServiceUnavailable, SessionExpired

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
    SampleQuestion,
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
        property_rows: list[tuple[list[str], str | None]] = (),
        relationship_rows: list[tuple[list[str], str, list[str]]] = (),
        models: list[str] = (),
        tail_rows: list[tuple[str, str]] = (),
        operators: list[str] = (),
        airports: list[str] = (),
        schema_error: Exception | None = None,
        extra_candidates: list[int] = (),
    ) -> None:
        self.schema_error = schema_error
        # Indexes every pattern check returns on top of the real matches.
        self.extra_candidates = list(extra_candidates)
        self.rows = {
            agent_samples._NODE_PROPERTIES_Q: [
                {"nodeLabels": labels, "propertyName": name} for labels, name in property_rows
            ],
            agent_samples._MODELS_Q: [{"model": model} for model in models],
            agent_samples._SAMPLE_TAILS_Q: [
                {"model": model, "tail": tail} for model, tail in tail_rows
            ],
            agent_samples._OPERATORS_Q: [{"operator": name} for name in operators],
            agent_samples._AIRPORTS_Q: [{"iata": code} for code in airports],
        }
        self.relationship_rows = list(relationship_rows)
        self.session_configs: list[dict[str, Any]] = []
        self.session_queries: list[list[str]] = []
        self.sessions: list[_SchemaSession] = []
        self.check_queries: list[str] = []

    def session(self, **config: Any) -> _SchemaSession:
        self.session_configs.append(config)
        self.session_queries.append([])
        self.sessions.append(_SchemaSession(self, self.session_queries[-1]))
        return self.sessions[-1]

    def execute_query(self, cypher: str, /, **params: Any) -> tuple[list[dict], None, None]:
        return [], None, None


class _SchemaSession:
    def __init__(self, driver: SchemaDriver, queries: list[str]) -> None:
        self.driver = driver
        self.queries = queries
        self.bookmarks = object()

    def last_bookmarks(self) -> object:
        return self.bookmarks

    def __enter__(self) -> _SchemaSession:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def run(self, cypher: str) -> SimpleNamespace:
        self.queries.append(cypher)
        if self.driver.schema_error is not None:
            raise self.driver.schema_error
        if cypher == agent_samples._SCHEMA_VISUALIZATION_Q:
            record = _visualization(self.driver.relationship_rows)
            return SimpleNamespace(single=lambda strict=False: record)
        if cypher.startswith("MATCH (:"):
            self.driver.check_queries.append(cypher)
            rows = _check_rows(cypher, self.driver.relationship_rows)
            rows += [{"candidate": index} for index in self.driver.extra_candidates]
            return SimpleNamespace(data=lambda: rows)
        if cypher not in self.driver.rows:
            raise AssertionError(f"unexpected schema query: {cypher}")
        rows = self.driver.rows[cypher]
        return SimpleNamespace(data=lambda: rows)


class _VizNode(dict):
    """A db.schema.visualization node: one label, with an element id."""

    def __init__(self, label: str) -> None:
        super().__init__(name=label)
        self.element_id = f"viz:{label}"


def _visualization(
    relationship_rows: list[tuple[list[str], str, list[str]]],
) -> dict[str, list[Any]]:
    """Answer db.schema.visualization the way the count store does.

    The count store knows, per type, which labels start and which end a
    relationship, but not which pairs go together. So every start label of a
    type is paired with every end label of that type, which can pair labels
    that are never linked.
    """
    starts: dict[str, set[str]] = {}
    ends: dict[str, set[str]] = {}
    for from_labels, rel_type, to_labels in relationship_rows:
        starts.setdefault(rel_type, set()).update(from_labels)
        ends.setdefault(rel_type, set()).update(to_labels)
    nodes = {
        label: _VizNode(label) for labels in [*starts.values(), *ends.values()] for label in labels
    }
    relationships = [
        SimpleNamespace(start_node=nodes[start], type=rel_type, end_node=nodes[end])
        for rel_type in starts
        for start in sorted(starts[rel_type])
        for end in sorted(ends[rel_type])
    ]
    return {"nodes": list(nodes.values()), "relationships": relationships}


_BRANCH = re.compile(
    r"MATCH \(:`((?:[^`]|``)+)`\)-\[:`((?:[^`]|``)+)`\]->\(:`((?:[^`]|``)+)`\) "
    r"RETURN (\d+) AS candidate LIMIT 1"
)


def _check_rows(
    cypher: str, relationship_rows: list[tuple[list[str], str, list[str]]]
) -> list[dict[str, int]]:
    """Answer the pattern check: the candidates some relationship row matches."""
    branches = cypher.split("\nUNION ALL\n")
    rows = []
    for branch in branches:
        match = _BRANCH.fullmatch(branch)
        assert match, f"unexpected check branch: {branch}"
        start, rel_type, end = (name.replace("``", "`") for name in match.groups()[:3])
        if any(
            start in from_labels and rel == rel_type and end in to_labels
            for from_labels, rel, to_labels in relationship_rows
        ):
            rows.append({"candidate": int(match.group(4))})
    return rows


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
        "- Calibrated:Sensor {sensor_id}"
        f"  (type: {', '.join(sensor_type for sensor_type, _, _ in SENSOR_TYPES)})\n"
        '- Chunk {chunkId, index, text}  (chunkId: "{documentId}:{index}")\n'
        "\n"
        "Relationships:\n"
        "- (Aircraft)-[:HAS_SYSTEM]->(System)\n"
        "- (Chunk)-[:NEXT_CHUNK]->(Chunk)\n"
        "- (Fault)-[:FROM_CHUNK]->(Chunk)\n"
    )


def test_schema_joins_the_notes_of_each_label_on_a_node() -> None:
    driver = SchemaDriver(property_rows=[(["Removal", "Chunk"], "chunkId")])

    lines = graph_schema(driver, "db").splitlines()

    assert (
        '- Chunk:Removal {chunkId}  (chunkId: "{documentId}:{index}"; '
        "hours_since_install and flight_hours_at_removal are flight hours)"
    ) in lines


def test_schema_drops_count_store_pairs_that_no_relationship_links() -> None:
    # Fault and Removal both start a HAS_LIMIT, so the count store also
    # offers Fault-HAS_LIMIT->Sensor and Removal-HAS_LIMIT->OperatingLimit.
    driver = SchemaDriver(
        relationship_rows=[
            (["Fault"], "HAS_LIMIT", ["OperatingLimit"]),
            (["Removal"], "HAS_LIMIT", ["Sensor"]),
        ]
    )

    lines = graph_schema(driver, "db").splitlines()

    assert [line for line in lines if "HAS_LIMIT" in line] == [
        "- (Fault)-[:HAS_LIMIT]->(OperatingLimit)",
        "- (Removal)-[:HAS_LIMIT]->(Sensor)",
    ]
    (check,) = driver.check_queries
    assert check.count("UNION ALL") == 3


def test_schema_lists_each_label_of_a_multi_label_node_in_relationships() -> None:
    # Item 8 and the per-label patterns together: the node line joins the
    # labels and gets each label's notes, and the relationship lines name
    # each label on its own.
    driver = SchemaDriver(
        property_rows=[(["Sensor", "Calibrated"], "sensor_id")],
        relationship_rows=[
            (["Sensor", "Calibrated", "__Entity__"], "HAS_LIMIT", ["OperatingLimit"]),
            (["System"], "HAS_SENSOR", ["Sensor"]),
        ],
    )

    lines = graph_schema(driver, "db").splitlines()

    sensor_types = ", ".join(sensor_type for sensor_type, _, _ in SENSOR_TYPES)
    assert f"- Calibrated:Sensor {{sensor_id}}  (type: {sensor_types})" in lines
    assert lines[lines.index("Relationships:") + 1 :] == [
        "- (Calibrated)-[:HAS_LIMIT]->(OperatingLimit)",
        "- (Sensor)-[:HAS_LIMIT]->(OperatingLimit)",
        "- (System)-[:HAS_SENSOR]->(Sensor)",
    ]


def test_schema_quotes_names_in_the_pattern_check() -> None:
    driver = SchemaDriver(relationship_rows=[(["Odd`Label"], "ODD`TYPE", ["Plain"])])

    lines = graph_schema(driver, "db").splitlines()

    (check,) = driver.check_queries
    assert check == "MATCH (:`Odd``Label`)-[:`ODD``TYPE`]->(:`Plain`) RETURN 0 AS candidate LIMIT 1"
    assert "- (Odd`Label)-[:ODD`TYPE]->(Plain)" in lines


def test_schema_keeps_a_backslash_name_out_of_the_pattern_check(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Inside backticks, Cypher decodes ` to a backtick, so doubling
    # backticks cannot keep such a name inside its quotes.
    evil = "Evil\\u0060)-[]->() RETURN 99 AS candidate //"
    driver = SchemaDriver(
        relationship_rows=[
            ([evil], "HAS_SYSTEM", ["System"]),
            (["Aircraft"], "HAS_SYSTEM", ["System"]),
            (["Aircraft"], "ODD\\TYPE", ["System"]),
        ]
    )

    lines = graph_schema(driver, "db").splitlines()

    assert driver.check_queries
    assert not any("\\" in query for query in driver.check_queries)
    assert lines[lines.index("Relationships:") + 1 :] == ["- (Aircraft)-[:HAS_SYSTEM]->(System)"]
    assert (
        "  [WARN] skipped 2 relationship pattern(s) with a backslash: "
        "(Aircraft)-[:ODD\\TYPE]->(System), "
        "(Evil\\u0060)-[]->() RETURN 99 AS candidate //)-[:HAS_SYSTEM]->(System)\n"
    ) in capsys.readouterr().out


def test_schema_keeps_a_control_character_name_out_of_the_pattern_check(
    capsys: pytest.CaptureFixture[str],
) -> None:
    driver = SchemaDriver(
        relationship_rows=[
            (["Nul\x00Label"], "HAS_SYSTEM", ["System"]),
            (["Aircraft"], "HAS_SYSTEM", ["System"]),
            (["Aircraft"], "LINE\nBREAK", ["System"]),
        ]
    )

    lines = graph_schema(driver, "db").splitlines()

    assert driver.check_queries == [
        "MATCH (:`Aircraft`)-[:`HAS_SYSTEM`]->(:`System`) RETURN 0 AS candidate LIMIT 1"
    ]
    assert lines[lines.index("Relationships:") + 1 :] == ["- (Aircraft)-[:HAS_SYSTEM]->(System)"]
    # The names are escaped, so a control character never reaches the terminal.
    assert (
        "  [WARN] skipped 2 relationship pattern(s) with a control character: "
        "(Aircraft)-[:LINE\\nBREAK]->(System), (Nul\\x00Label)-[:HAS_SYSTEM]->(System)\n"
    ) in capsys.readouterr().out


@pytest.mark.parametrize("index", [-1, 1, 99])
def test_schema_ignores_a_candidate_index_out_of_range(index: int) -> None:
    driver = SchemaDriver(
        relationship_rows=[(["Aircraft"], "HAS_SYSTEM", ["System"])],
        extra_candidates=[index],
    )

    lines = graph_schema(driver, "db").splitlines()

    assert lines[lines.index("Relationships:") + 1 :] == ["- (Aircraft)-[:HAS_SYSTEM]->(System)"]


def test_schema_checks_patterns_in_queries_of_bounded_size() -> None:
    # 20 start labels and 20 end labels of one type give 400 candidates.
    starts = [f"S{n:02d}" for n in range(20)]
    ends = [f"E{n:02d}" for n in range(20)]
    driver = SchemaDriver(
        relationship_rows=[([s], "LINKS", [e]) for s, e in zip(starts, ends, strict=True)]
    )

    lines = graph_schema(driver, "db").splitlines()

    branch_counts = [query.count("UNION ALL") + 1 for query in driver.check_queries]
    assert branch_counts == [150, 150, 100]
    assert lines[lines.index("Relationships:") + 1 :] == [
        f"- ({s})-[:LINKS]->({e})" for s, e in zip(starts, ends, strict=True)
    ]


def test_schema_skips_the_pattern_check_without_relationships() -> None:
    driver = SchemaDriver(property_rows=[(["Aircraft"], "tail_number")])

    lines = graph_schema(driver, "db").splitlines()

    assert driver.check_queries == []
    assert lines[lines.index("Relationships:") + 1 :] == []


def test_schema_lists_a_label_without_properties() -> None:
    # nodeTypeProperties returns one row with a null propertyName for a
    # label whose nodes have no properties.
    driver = SchemaDriver(property_rows=[(["Marker"], None), (["Aircraft"], "tail_number")])

    lines = graph_schema(driver, "db").splitlines()

    assert "- Marker {}" in lines
    assert "- Aircraft {tail_number}" in lines


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


def test_schema_sessions_disable_only_the_expected_notifications() -> None:
    # db.schema.nodeTypeProperties raises a GENERIC notice about its
    # propertyTypes field. Other GENERIC notices still reach the log. On a
    # partial database the fact queries name a label or property key that
    # does not exist yet, which raises an UNRECOGNIZED notice. The second
    # session starts from the first one's bookmarks, so on a cluster both
    # read the same state.
    driver = SchemaDriver(relationship_rows=[(["Aircraft"], "HAS_SYSTEM", ["System"])])

    graph_schema(driver, "db")

    read = {"database": "db", "default_access_mode": READ_ACCESS}
    assert driver.session_configs == [
        {
            **read,
            "notifications_disabled_classifications": [NotificationDisabledClassification.GENERIC],
        },
        {
            **read,
            "notifications_disabled_classifications": [
                NotificationDisabledClassification.UNRECOGNIZED
            ],
            "bookmarks": driver.sessions[0].bookmarks,
        },
    ]
    property_queries, other_queries = driver.session_queries
    assert property_queries == [agent_samples._NODE_PROPERTIES_Q]
    (check,) = driver.check_queries
    assert other_queries == [
        agent_samples._SCHEMA_VISUALIZATION_Q,
        check,
        agent_samples._MODELS_Q,
        agent_samples._SAMPLE_TAILS_Q,
        agent_samples._OPERATORS_Q,
        agent_samples._AIRPORTS_Q,
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
    # One schema read, which opens two sessions.
    assert [config["database"] for config in driver.session_configs] == ["db", "db"]


def _run_samples(
    monkeypatch: pytest.MonkeyPatch,
    driver: SchemaDriver,
    questions: list[SampleQuestion] | None = None,
) -> list[tuple[str, str]]:
    """Run the agent samples with a fake LLM and return its (system, user) calls."""
    chats: list[tuple[str, str]] = []

    def chat(system: str, user: str) -> str:
        chats.append((system, user))
        return "MATCH (n) RETURN n"

    monkeypatch.setattr(
        agent_samples, "_create_llm_client", lambda *args, **kwargs: (chat, lambda text: [0.1])
    )
    if questions is not None:
        monkeypatch.setattr(agent_samples, "SAMPLE_QUESTIONS", questions)
    run_agent_samples(
        driver,
        "db",
        provider="test",
        llm_model="model",
        embedding_model="embedder",
        embedding_dimensions=1,
    )
    return chats


def _questions(tool: str) -> list[SampleQuestion]:
    return [sq for sq in SAMPLE_QUESTIONS if sq.tool == tool]


def test_schema_is_not_read_without_a_text2cypher_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = SchemaDriver()

    _run_samples(monkeypatch, driver, _questions("similarity_search"))

    assert driver.session_configs == []


def test_schema_read_error_skips_only_the_text2cypher_questions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    error = Forbidden()

    chats = _run_samples(monkeypatch, SchemaDriver(schema_error=error))

    out = capsys.readouterr().out
    assert f"[ERROR] Schema read failed: {error.code}: {error.message}" in out
    assert out.count("[SKIP] No graph schema") == len(_questions("text2cypher"))
    similarity = [sq.question for sq in _questions("similarity_search")]
    assert [user for _, user in chats] == similarity


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ServiceUnavailable("connection lost"), id="service-unavailable"),
        pytest.param(SessionExpired("session expired"), id="session-expired"),
    ],
)
def test_schema_read_connection_error_skips_only_the_text2cypher_questions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    chats = _run_samples(monkeypatch, SchemaDriver(schema_error=error))

    out = capsys.readouterr().out
    assert f"[ERROR] Schema read failed: {error}" in out
    assert out.count("[SKIP] No graph schema") == len(_questions("text2cypher"))
    similarity = [sq.question for sq in _questions("similarity_search")]
    assert [user for _, user in chats] == similarity


@pytest.mark.parametrize(
    ("property_rows", "warns"),
    [
        ([], True),
        ([(["__KGBuilder__"], "id")], True),
        ([(["Aircraft"], "tail_number")], False),
    ],
)
def test_schema_warns_when_the_database_has_no_labels(
    capsys: pytest.CaptureFixture[str],
    property_rows: list[tuple[list[str], str]],
    warns: bool,
) -> None:
    graph_schema(SchemaDriver(property_rows=property_rows), "db")

    assert ("[WARN] No node labels in database 'db'" in capsys.readouterr().out) == warns


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


def test_graph_schema_reads_the_live_database(
    driver: Driver, caplog: pytest.LogCaptureFixture
) -> None:
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
        # The lowest aircraft_id number of a model gives its sample tail.
        # As text, AC10000 would sort before AC9999.
        driver.execute_query(
            """
            CREATE (:Aircraft {aircraft_id: 'AC10000', tail_number: 'N2PYT',
                               model: 'PYTEST-MODEL', operator: 'PytestAir'})
            CREATE (:Aircraft {aircraft_id: 'AC9999', tail_number: 'N1PYT',
                               model: 'PYTEST-MODEL', operator: 'PytestAir'})
            CREATE (:Airport {iata: 'ZZQ'})
            """,
            database_=database,
        )

        with caplog.at_level(logging.INFO, logger="neo4j.notifications"):
            schema = graph_schema(driver, database)
        lines = schema.splitlines()

        assert [r for r in caplog.records if r.name == "neo4j.notifications"] == []
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


def test_graph_schema_finds_a_rare_pattern_next_to_a_common_one(driver: Driver) -> None:
    database = os.environ.get("NEO4J_TEST_DATABASE", "neo4j")
    cleanup = """
    MATCH (n)
    WHERE n:PytestCommon OR n:PytestCommonEnd OR n:PytestRare OR n:PytestRareEnd
    DETACH DELETE n
    """
    driver.execute_query(cleanup, database_=database)
    try:
        # 2,000 common links and one rare link of the same type. The rare
        # start node has a second label.
        driver.execute_query(
            """
            UNWIND range(1, 2000) AS i
            CREATE (:PytestCommon)-[:PYTEST_SHARED]->(:PytestCommonEnd)
            WITH count(*) AS created
            CREATE (:PytestRare:PytestRareAlso)-[:PYTEST_SHARED]->(:PytestRareEnd)
            """,
            database_=database,
        )

        lines = graph_schema(driver, database).splitlines()

        shared = [line for line in lines if "PYTEST_SHARED" in line]
        assert shared == [
            "- (PytestCommon)-[:PYTEST_SHARED]->(PytestCommonEnd)",
            "- (PytestRare)-[:PYTEST_SHARED]->(PytestRareEnd)",
            "- (PytestRareAlso)-[:PYTEST_SHARED]->(PytestRareEnd)",
        ]
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
