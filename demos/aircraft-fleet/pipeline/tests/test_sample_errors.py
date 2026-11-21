"""Sample queries report the server's error and show the setup hint only for a missing index."""

from __future__ import annotations

from typing import Any

import pytest
from neo4j.exceptions import ClientError

from populate_aircraft_db.agent_samples import _run_similarity_search, _run_text2cypher
from populate_aircraft_db.samples import (
    _adjacent_chunks,
    _fulltext_search,
    _hybrid_comparison,
    _vector_document_context,
    _vector_similarity,
    _vector_topology,
)

SETUP_HINT = "run 'setup' first"
SEED = "DOC-1:0"


class FailingDriver:
    """Fail every query after the first `ok_queries`, which return no rows.

    SHOW INDEXES never fails. It finds `index_count` matches.
    """

    def __init__(self, error: Exception, index_count: int = 0, ok_queries: int = 0) -> None:
        self.error = error
        self.index_count = index_count
        self.ok_queries = ok_queries
        self.index_lookups: list[str] = []

    def execute_query(self, cypher: str, /, **params: Any) -> tuple[list[dict], None, None]:
        if cypher.startswith("SHOW INDEXES"):
            self.index_lookups.append(params["index"])
            return [{"count": self.index_count}], None, None
        if self.ok_queries:
            self.ok_queries -= 1
            return [], None, None
        raise self.error


def _chat(system: str, user: str) -> str:
    return "MATCH (n) RETURN n"


# Each search query in the samples, the index it needs, and how many
# queries before it succeed.
SEARCHES = [
    pytest.param(
        lambda d: _vector_similarity(d, "db", 3, SEED), "maintenanceChunkEmbeddings", 0, id="9"
    ),
    pytest.param(lambda d: _fulltext_search(d, "db", 3), "maintenanceChunkText", 0, id="10"),
    pytest.param(
        lambda d: _vector_document_context(d, "db", 3, SEED),
        "maintenanceChunkEmbeddings",
        0,
        id="11",
    ),
    pytest.param(
        lambda d: _adjacent_chunks(d, "db", 3, SEED), "maintenanceChunkEmbeddings", 0, id="12"
    ),
    pytest.param(
        lambda d: _vector_topology(d, "db", 3, SEED), "maintenanceChunkEmbeddings", 0, id="13"
    ),
    pytest.param(
        lambda d: _hybrid_comparison(d, "db", 3, SEED),
        "maintenanceChunkEmbeddings",
        0,
        id="14-vector",
    ),
    pytest.param(
        lambda d: _hybrid_comparison(d, "db", 3, SEED), "maintenanceChunkText", 1, id="14-fulltext"
    ),
    pytest.param(
        lambda d: _run_similarity_search(d, "db", _chat, lambda t: [0.1], "q"),
        "maintenanceChunkEmbeddings",
        0,
        id="agent-similarity",
    ),
]


@pytest.mark.parametrize(("run", "index", "ok_queries"), SEARCHES)
def test_missing_index_shows_the_error_and_the_setup_hint(
    capsys, run, index: str, ok_queries: int
) -> None:
    error = ClientError()
    driver = FailingDriver(error, index_count=0, ok_queries=ok_queries)

    run(driver)

    out = capsys.readouterr().out
    assert f"[ERROR] {error.code}: {error.message}" in out
    assert f"index '{index}' not found; {SETUP_HINT}" in out
    assert driver.index_lookups == [index]


def test_existing_index_shows_the_error_without_the_setup_hint(capsys) -> None:
    error = ClientError()
    driver = FailingDriver(error, index_count=1)

    _fulltext_search(driver, "db", 3)

    out = capsys.readouterr().out
    assert f"[ERROR] {error.code}: {error.message}" in out
    assert SETUP_HINT not in out
    assert driver.index_lookups == ["maintenanceChunkText"]


@pytest.mark.parametrize(
    ("run", "index", "ok_queries"),
    [
        *SEARCHES,
        pytest.param(
            lambda d: _run_text2cypher(d, "db", _chat, "prompt", "q"),
            None,
            0,
            id="agent-text2cypher",
        ),
    ],
)
def test_non_database_errors_are_not_caught(run, index: str | None, ok_queries: int) -> None:
    with pytest.raises(RuntimeError, match="driver bug"):
        run(FailingDriver(RuntimeError("driver bug"), ok_queries=ok_queries))


def test_generated_cypher_error_is_reported_without_an_index_lookup(capsys) -> None:
    error = ClientError()
    driver = FailingDriver(error)

    _run_text2cypher(driver, "db", lambda system, user: "MATCH (n) RETURN n", "prompt", "question")

    out = capsys.readouterr().out
    assert f"[ERROR] Cypher execution failed: {error.code}: {error.message}" in out
    assert driver.index_lookups == []


def test_embedding_errors_are_not_caught() -> None:
    def embed(text: str) -> list[float]:
        raise RuntimeError("Bedrock throttled")

    with pytest.raises(RuntimeError, match="Bedrock"):
        _run_similarity_search(
            FailingDriver(ClientError()), "db", lambda system, user: "phrase", embed, "question"
        )
