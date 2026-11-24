"""Tests for the database-free parts of ``core.graph.retrieval``."""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import neo4j
import pytest
from neo4j._sync.io._pool import IOPool
from neo4j.auth_management import AuthManager
from neo4j_graphrag.types import RetrieverResultItem

from fleet_supervisor.core import secrets
from fleet_supervisor.core.config import ConfigError
from fleet_supervisor.core.graph import retrieval
from tests.fake_bolt import FakeNeo4j


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Is A320-200 EGT/N1 OK?", "is a320 200 egt n1 ok"),
        ('(NOT "hot") AND', "not hot and"),
        ("field:value ~fuzzy* [x TO y] {a} ^2 \\", "field value fuzzy x to y a 2"),
        ("?!-/", ""),
    ],
)
def test_fulltext_query_strips_lucene_syntax(text: str, expected: str) -> None:
    assert retrieval.fulltext_query(text) == expected


def test_format_hit_includes_provenance() -> None:
    item = RetrieverResultItem(
        content="Check EGT margin.",
        metadata={
            "score": 0.91234,
            "document_id": "AMM-A320-2024-001",
            "aircraft_type": "A320-200",
            "title": "A320 AMM",
            "chunk_index": 7,
            "entities": ["Fault: EGT Overtemp", "OperatingLimit: EGT Takeoff - A320-200"],
        },
    )
    assert retrieval._format_hit(item) == (
        "[Source: AMM-A320-2024-001 | A320-200 | chunk 7 | score 0.912]\n"
        "Entities: Fault: EGT Overtemp, OperatingLimit: EGT Takeoff - A320-200\n"
        "Check EGT margin."
    )


def test_format_hit_without_document_or_entities() -> None:
    item = RetrieverResultItem(
        content="Orphan chunk.",
        metadata={"score": None, "chunk_index": 0, "entities": []},
    )
    assert retrieval._format_hit(item) == ("[Source: unknown document | chunk 0]\nOrphan chunk.")


def test_vector_search_with_no_tokens_skips_the_database(monkeypatch) -> None:
    def fail() -> None:
        raise AssertionError("retriever must not be built")

    monkeypatch.setattr(retrieval, "_hybrid_retriever", fail)
    assert retrieval.vector_search("?!") == "No relevant document chunks found."


def test_schema_cache_honors_ttl(monkeypatch) -> None:
    clock = [1000.0]
    fetches: list[int] = []

    def fake_get_schema(driver: object, database: str) -> str:
        fetches.append(1)
        return f"schema v{len(fetches)}"

    monkeypatch.setattr(retrieval, "_schema_cache", None)
    monkeypatch.setattr(retrieval, "get_driver", object)
    monkeypatch.setattr(retrieval, "get_schema", fake_get_schema)
    monkeypatch.setattr(retrieval.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        retrieval,
        "graph_settings",
        dataclasses.replace(retrieval.graph_settings, schema_ttl_s=60),
    )

    assert retrieval.get_graph_schema() == "schema v1"
    clock[0] += 59
    assert retrieval.get_graph_schema() == "schema v1"
    clock[0] += 2
    assert retrieval.get_graph_schema() == "schema v2"
    assert len(fetches) == 2


def test_graph_query_passes_current_schema(monkeypatch) -> None:
    seen: dict = {}

    class FakeRetriever:
        def search(self, query_text: str, prompt_params: dict) -> SimpleNamespace:
            seen.update(query_text=query_text, prompt_params=dict(prompt_params))
            return SimpleNamespace(items=[SimpleNamespace(content="<Record n=42>")], metadata={})

    monkeypatch.setattr(retrieval, "_text2cypher_retriever", FakeRetriever)
    monkeypatch.setattr(retrieval, "get_graph_schema", lambda: "fresh schema")
    assert retrieval.graph_query("how many aircraft?") == "<Record n=42>"
    assert seen == {
        "query_text": "how many aircraft?",
        "prompt_params": {"schema": "fresh schema"},
    }


def test_graph_query_notes_truncation(monkeypatch) -> None:
    class FakeRetriever:
        def search(self, **_kwargs: object) -> SimpleNamespace:
            items = [SimpleNamespace(content=f"<Record n={i}>") for i in range(2)]
            return SimpleNamespace(items=items, metadata={"truncated": True})

    monkeypatch.setattr(retrieval, "_text2cypher_retriever", FakeRetriever)
    monkeypatch.setattr(retrieval, "get_graph_schema", lambda: "schema")
    out = retrieval.graph_query("list everything")
    assert out.startswith("<Record n=0>\n<Record n=1>\n")
    assert "first 2 rows" in out


def test_text2cypher_llm_caps_output_tokens(monkeypatch) -> None:
    captured: dict = {}

    def fake_llm(**kwargs):
        captured.update(kwargs)
        return "llm"

    monkeypatch.setattr(retrieval, "BedrockLLM", fake_llm)
    monkeypatch.setattr(retrieval, "BoundedText2CypherRetriever", lambda *a, **kw: kw)
    monkeypatch.setattr(retrieval, "get_driver", lambda: "driver")
    monkeypatch.setattr(retrieval, "get_graph_schema", lambda: "schema")
    retrieval._text2cypher_retriever.cache_clear()
    try:
        retrieval._text2cypher_retriever()
    finally:
        retrieval._text2cypher_retriever.cache_clear()
    assert captured["model_params"] == {
        "maxTokens": retrieval.graph_settings.text2cypher_max_tokens
    }


SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:fleet/neo4j-reader-AbCdEf"
UNAUTHORIZED = SimpleNamespace(code="Neo.ClientError.Security.Unauthorized")


class FakeDriver:
    """Records the auth it was built with and whether it was closed."""

    def __init__(self, uri: str, auth: object) -> None:
        self.uri = uri
        self.auth = auth
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_drivers(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[FakeDriver]]:
    """Patch the driver factory and start with no driver and no cached retrievers."""
    built: list[FakeDriver] = []

    def fake_driver(uri: str, auth: object) -> FakeDriver:
        built.append(FakeDriver(uri, auth))
        return built[-1]

    monkeypatch.setenv("NEO4J_URI", "neo4j+s://fleet.example.test")
    monkeypatch.setattr(retrieval.GraphDatabase, "driver", fake_driver)
    monkeypatch.setattr(retrieval, "_driver", None)
    retrieval._hybrid_retriever.cache_clear()
    retrieval._text2cypher_retriever.cache_clear()
    yield built
    retrieval._hybrid_retriever.cache_clear()
    retrieval._text2cypher_retriever.cache_clear()


@dataclasses.dataclass
class FakeSecret:
    """The fleet secret's password history and how often it was read."""

    passwords: list[str] = dataclasses.field(default_factory=lambda: ["first-pw"])
    reads: int = 0

    def rotate(self, password: str) -> None:
        self.passwords.append(password)


@pytest.fixture
def rotating_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSecret]:
    """Serve the fleet secret from a fake Secrets Manager."""
    secret = FakeSecret()

    def get_secret_value(SecretId: str) -> dict[str, str]:
        assert SecretId == SECRET_ARN
        secret.reads += 1
        return {
            "SecretString": json.dumps({"username": "reader", "password": secret.passwords[-1]})
        }

    monkeypatch.setenv("NEO4J_PASSWORD_SECRET_ARN", SECRET_ARN)
    monkeypatch.setattr(
        secrets.boto3,
        "client",
        lambda service, region_name: SimpleNamespace(get_secret_value=get_secret_value),
    )
    secrets.forget_secrets()
    yield secret
    secrets.forget_secrets()


def unauthorized() -> neo4j.exceptions.Neo4jError:
    """A real driver error for a rejected login, as the server reports it."""
    return neo4j.exceptions.Neo4jError._hydrate_neo4j(
        code="Neo.ClientError.Security.Unauthorized", message="rejected"
    )


def report_to_pool(manager: AuthManager, auth: neo4j.Auth) -> neo4j.exceptions.Neo4jError:
    """Pass a rejected login through the driver's own pool hook.

    neo4j 6.4.1 marks the error retryable only when the auth manager handled
    it. ``execute_query`` retries only retryable errors.

    The driver calls this hook only for an error on a pooled connection. A
    login rejected while a new connection opens never reaches it, so the
    tests that use it do not cover that case. The fake-server tests below
    cover it through ``retry_on_rotated_login``.
    """
    error = unauthorized()
    connection = SimpleNamespace(auth_manager=manager, auth=auth)
    IOPool.on_neo4j_error(None, error, connection)
    return error


def test_get_driver_builds_one_driver_with_an_auth_manager(
    fake_drivers: list[FakeDriver],
) -> None:
    driver = retrieval.get_driver()
    assert retrieval.get_driver() is driver
    assert len(fake_drivers) == 1
    assert fake_drivers[0].uri == "neo4j+s://fleet.example.test"
    assert isinstance(fake_drivers[0].auth, AuthManager)


def test_get_driver_needs_the_uri(
    fake_drivers: list[FakeDriver], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEO4J_URI")
    with pytest.raises(ConfigError, match="NEO4J_URI is not set"):
        retrieval.get_driver()
    assert fake_drivers == []


def test_concurrent_first_calls_build_one_driver(
    fake_drivers: list[FakeDriver], monkeypatch: pytest.MonkeyPatch
) -> None:
    built_once = retrieval.GraphDatabase.driver

    def slow_driver(uri: str, auth: object) -> FakeDriver:
        # Without the lock, every thread would get here before the first one returns.
        time.sleep(0.05)
        return built_once(uri, auth)

    monkeypatch.setattr(retrieval.GraphDatabase, "driver", slow_driver)
    start = threading.Barrier(8)

    def first_call() -> object:
        start.wait()
        return retrieval.get_driver()

    with ThreadPoolExecutor(max_workers=8) as pool:
        drivers = list(pool.map(lambda _: first_call(), range(8)))
    assert len(fake_drivers) == 1
    assert all(driver is fake_drivers[0] for driver in drivers)


def test_a_rejected_login_reads_the_rotated_secret(
    fake_drivers: list[FakeDriver], rotating_secret: FakeSecret
) -> None:
    manager = retrieval.get_driver().auth
    first = manager.get_auth()
    assert first == neo4j.basic_auth("reader", "first-pw")
    assert manager.get_auth() is first
    assert rotating_secret.reads == 1

    rotating_secret.rotate("rotated-pw")
    # True tells the driver that the error is retryable. It then retries the
    # query with the login the manager now holds.
    assert manager.handle_security_exception(first, UNAUTHORIZED) is True
    assert manager.get_auth() == neo4j.basic_auth("reader", "rotated-pw")
    assert rotating_secret.reads == 2


def test_a_rejected_login_that_did_not_change_fails_at_once(
    fake_drivers: list[FakeDriver], rotating_secret: FakeSecret
) -> None:
    manager = retrieval.get_driver().auth
    first = manager.get_auth()
    # False tells the driver not to retry, so the query fails right away.
    assert manager.handle_security_exception(first, UNAUTHORIZED) is False
    assert manager.get_auth() is first
    assert rotating_secret.reads == 2


def test_a_login_another_connection_replaced_retries_without_a_read(
    fake_drivers: list[FakeDriver], rotating_secret: FakeSecret
) -> None:
    manager = retrieval.get_driver().auth
    first = manager.get_auth()
    rotating_secret.rotate("rotated-pw")
    assert manager.handle_security_exception(first, UNAUTHORIZED) is True
    assert rotating_secret.reads == 2

    # A second connection still opened with the first login reports it late.
    assert manager.handle_security_exception(first, UNAUTHORIZED) is True
    assert manager.get_auth() == neo4j.basic_auth("reader", "rotated-pw")
    assert rotating_secret.reads == 2


def test_a_pooled_connection_retries_a_rotated_password_once(
    fake_drivers: list[FakeDriver], rotating_secret: FakeSecret
) -> None:
    manager = retrieval.get_driver().auth
    first = manager.get_auth()
    rotating_secret.rotate("rotated-pw")
    assert report_to_pool(manager, first).is_retryable()

    # The retry opens with the rotated login, and Neo4j accepts it.
    assert manager.get_auth() == neo4j.basic_auth("reader", "rotated-pw")
    assert rotating_secret.reads == 2


def test_a_pooled_connection_does_not_retry_a_wrong_password(
    fake_drivers: list[FakeDriver], rotating_secret: FakeSecret
) -> None:
    manager = retrieval.get_driver().auth
    first = manager.get_auth()
    error = report_to_pool(manager, first)

    # Not retryable, so execute_query raises it instead of backing off.
    assert not error.is_retryable()
    assert isinstance(error, neo4j.exceptions.AuthError)
    assert rotating_secret.reads == 2


def test_other_security_errors_keep_the_login(
    fake_drivers: list[FakeDriver], rotating_secret: FakeSecret
) -> None:
    manager = retrieval.get_driver().auth
    first = manager.get_auth()
    rotating_secret.rotate("rotated-pw")
    forbidden = SimpleNamespace(code="Neo.ClientError.Security.Forbidden")
    assert manager.handle_security_exception(first, forbidden) is False
    assert manager.get_auth() is first
    assert rotating_secret.reads == 1


def run_query(driver: neo4j.Driver) -> list[neo4j.Record]:
    records, _, _ = driver.execute_query("RETURN 1", database_="neo4j")
    return records


def fake_server_driver(uri: str, manager: retrieval.RotatingLoginAuthManager) -> neo4j.Driver:
    """A real driver with no retries of its own, so only the helper retries."""
    return neo4j.GraphDatabase.driver(
        uri, auth=manager, connection_timeout=2, max_transaction_retry_time=0
    )


def test_a_new_connection_with_a_rotated_password_recovers_in_the_same_call(
    fake_neo4j: FakeNeo4j, rotating_secret: FakeSecret
) -> None:
    manager = retrieval.RotatingLoginAuthManager()
    assert manager.get_auth() == neo4j.basic_auth("reader", "first-pw")
    rotating_secret.rotate("rotated-pw")

    with fake_server_driver(fake_neo4j.uri, manager) as driver:
        assert retrieval.retry_on_rotated_login(manager, lambda: run_query(driver)) == []

    assert fake_neo4j.logins == ["first-pw", "rotated-pw"]
    assert rotating_secret.reads == 2


def test_the_driver_alone_does_not_recover_a_new_connection(
    fake_neo4j: FakeNeo4j, rotating_secret: FakeSecret
) -> None:
    """Shows why the helper exists: neo4j 6.4 never asks the manager here."""
    manager = retrieval.RotatingLoginAuthManager()
    manager.get_auth()
    rotating_secret.rotate("rotated-pw")

    with (
        neo4j.GraphDatabase.driver(fake_neo4j.uri, auth=manager, connection_timeout=2) as driver,
        pytest.raises(neo4j.exceptions.AuthError) as raised,
    ):
        run_query(driver)

    assert not raised.value.is_retryable()
    assert fake_neo4j.logins == ["first-pw"]
    assert rotating_secret.reads == 1


def test_a_password_still_wrong_after_reload_raises_after_one_attempt(
    fake_neo4j: FakeNeo4j, rotating_secret: FakeSecret
) -> None:
    manager = retrieval.RotatingLoginAuthManager()

    with (
        fake_server_driver(fake_neo4j.uri, manager) as driver,
        pytest.raises(neo4j.exceptions.AuthError),
    ):
        retrieval.retry_on_rotated_login(manager, lambda: run_query(driver))

    assert fake_neo4j.logins == ["first-pw"]
    assert rotating_secret.reads == 2


def test_a_rotated_password_that_is_also_wrong_raises_after_one_retry(
    fake_neo4j: FakeNeo4j, rotating_secret: FakeSecret
) -> None:
    manager = retrieval.RotatingLoginAuthManager()
    manager.get_auth()
    rotating_secret.rotate("another-wrong-pw")

    with (
        fake_server_driver(fake_neo4j.uri, manager) as driver,
        pytest.raises(neo4j.exceptions.AuthError),
    ):
        retrieval.retry_on_rotated_login(manager, lambda: run_query(driver))

    assert fake_neo4j.logins == ["first-pw", "another-wrong-pw"]


def test_service_unavailable_is_not_retried(rotating_secret: FakeSecret) -> None:
    with FakeNeo4j(password="rotated-pw") as stopped:
        uri = stopped.uri
    manager = retrieval.RotatingLoginAuthManager()
    calls: list[int] = []

    def query() -> list[neo4j.Record]:
        calls.append(1)
        return run_query(driver)

    with (
        fake_server_driver(uri, manager) as driver,
        pytest.raises(neo4j.exceptions.ServiceUnavailable),
    ):
        retrieval.retry_on_rotated_login(manager, query)

    assert len(calls) == 1
    assert rotating_secret.reads == 1


def test_a_login_another_call_already_rotated_retries_without_a_read(
    rotating_secret: FakeSecret,
) -> None:
    manager = retrieval.RotatingLoginAuthManager()
    attempts: list[str] = []

    def query() -> str:
        attempts.append(manager.get_auth().credentials)
        if len(attempts) == 1:
            # Another request reloads the rotated login while this one fails.
            rotating_secret.rotate("rotated-pw")
            assert manager.reload() is True
            raise unauthorized()
        return "ok"

    assert retrieval.retry_on_rotated_login(manager, query) == "ok"
    assert attempts == ["first-pw", "rotated-pw"]
    assert rotating_secret.reads == 2


def test_other_auth_errors_are_not_retried(rotating_secret: FakeSecret) -> None:
    manager = retrieval.RotatingLoginAuthManager()
    calls: list[int] = []

    def query() -> None:
        calls.append(1)
        raise neo4j.exceptions.Neo4jError._hydrate_neo4j(
            code="Neo.ClientError.Security.TokenExpired", message="expired"
        )

    with pytest.raises(neo4j.exceptions.AuthError):
        retrieval.retry_on_rotated_login(manager, query)
    assert len(calls) == 1
    assert rotating_secret.reads == 1


def test_reload_reports_whether_the_login_changed(rotating_secret: FakeSecret) -> None:
    manager = retrieval.RotatingLoginAuthManager()
    first = manager.get_auth()

    assert manager.reload() is False
    assert manager.get_auth() == first
    rotating_secret.rotate("rotated-pw")
    assert manager.reload() is True
    assert manager.get_auth() == neo4j.basic_auth("reader", "rotated-pw")
    assert rotating_secret.reads == 3


def test_close_drops_the_driver_and_the_retrievers_that_hold_it(
    fake_drivers: list[FakeDriver], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retrieval, "HybridCypherRetriever", lambda driver, **_: driver)
    monkeypatch.setattr(retrieval, "BoundedText2CypherRetriever", lambda driver, **_: driver)
    monkeypatch.setattr(retrieval, "BedrockLLM", lambda **_: "llm")
    monkeypatch.setattr(retrieval, "_embedder", lambda: "embedder")
    monkeypatch.setattr(retrieval, "get_graph_schema", lambda: "schema")

    first = retrieval.get_driver()
    assert retrieval._hybrid_retriever() is first
    assert retrieval._text2cypher_retriever() is first

    retrieval.close()
    assert first.closed
    second = retrieval.get_driver()
    assert second is not first
    assert retrieval._hybrid_retriever() is second
    assert retrieval._text2cypher_retriever() is second


def test_close_without_a_driver_is_safe(fake_drivers: list[FakeDriver]) -> None:
    retrieval.close()
    assert fake_drivers == []
