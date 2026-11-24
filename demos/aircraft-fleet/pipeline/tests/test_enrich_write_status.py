"""Enrich reports a manual whose Neo4j write failed, and fails after the last manual.

``Neo4jWriter`` catches a Neo4j ``ClientError`` and returns a ``FAILURE``
status instead of raising. These tests run the real writer and the real
neo4j-graphrag pipeline orchestrator with a writer -> resolver connection, as
``SimpleKGPipeline`` builds it with entity resolution on. A fake driver
rejects the write, so no Neo4j server is needed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import neo4j
import pytest
from neo4j.exceptions import ConstraintError
from neo4j_graphrag.components.base import Component, DataModel
from neo4j_graphrag.components.kg_writer import Neo4jWriter
from neo4j_graphrag.components.types import Neo4jGraph, Neo4jNode
from neo4j_graphrag.experimental.pipeline import Pipeline

from populate_aircraft_db import pipeline

CONSTRAINT_MESSAGE = "Node(799562) already exists with label `AircraftModel`"
VERSION_RECORDS = [{"versions": ["5.26.0"], "edition": "enterprise"}]


class FakeDriver:
    """A mock driver that answers the writer's version check.

    It rejects writes while ``reject`` is set.
    """

    def __init__(self) -> None:
        self.reject = False
        self.driver = mock.MagicMock(spec=neo4j.Driver)
        self.driver.execute_query.side_effect = self._execute_query

    def _execute_query(self, query: str, *_args: Any, **_kwargs: Any) -> tuple[Any, None, None]:
        if "dbms.components" in query:
            return VERSION_RECORDS, None, None
        if self.reject:
            raise ConstraintError(CONSTRAINT_MESSAGE)
        return [], None, None


class ResolverResult(DataModel):
    resolved: int = 0


class FakeResolver(Component):
    async def run(self) -> ResolverResult:
        return ResolverResult()


class WriterThenResolver:
    """A stand-in for ``SimpleKGPipeline``: a real writer -> resolver pipeline."""

    def __init__(self, driver: FakeDriver, rejected: set[str]) -> None:
        self._driver = driver
        self._rejected = rejected
        graph = Pipeline()
        graph.add_component(Neo4jWriter(driver.driver, neo4j_database="db"), "writer")
        graph.add_component(FakeResolver(), "resolver")
        graph.connect("writer", "resolver", input_config={})
        self.runner = SimpleNamespace(pipeline=graph)

    async def run_async(self, *, text: str, document_metadata: dict[str, Any]) -> Any:
        self._driver.reject = document_metadata["documentId"] in self._rejected
        node = Neo4jNode(id="1", label="AircraftModel", properties={"name": "A321neo"})
        return await self.runner.pipeline.run({"writer": {"graph": Neo4jGraph(nodes=[node])}})


def _process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kg_pipeline: Any, ids: list[str]
) -> None:
    docs = [
        pipeline.DocumentMeta(filename=f"{n}.md", document_id=n, aircraft_type="T", title="t")
        for n in ids
    ]
    for doc in docs:
        (tmp_path / doc.filename).write_text("abc", encoding="utf-8")
    monkeypatch.setattr(pipeline, "DOCUMENTS", docs)
    monkeypatch.setattr(
        pipeline, "_create_pipeline", lambda *a, **k: (kg_pipeline, SimpleNamespace())
    )
    pipeline.process_all_documents(
        FakeDriver().driver,
        "db",
        tmp_path,
        provider="bedrock",
        openai_api_key=None,
        llm_model="m",
        llm_max_tokens=1,
        embedding_model="e",
        embedding_dimensions=1,
        chunk_size=10,
        chunk_overlap=0,
    )


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == pipeline.logger.name]


def test_a_failed_write_names_the_manual_and_fails_after_the_others(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    kg_pipeline = WriterThenResolver(FakeDriver(), rejected={"DOC-1", "DOC-3"})

    with (
        caplog.at_level(logging.INFO, logger=pipeline.logger.name),
        pytest.raises(pipeline.ManualWriteError, match=r"failed for 2 of 3 manuals: DOC-1, DOC-3$"),
    ):
        _process(monkeypatch, tmp_path, kg_pipeline, ["DOC-1", "DOC-2", "DOC-3"])

    messages = _messages(caplog)
    assert [m for m in messages if "[OK]" in m or "[FAIL]" in m] == [
        f"  [FAIL] Neo4j write failed for DOC-1 (DOC-1.md): {CONSTRAINT_MESSAGE}",
        "  [OK] Pipeline complete for DOC-2",
        f"  [FAIL] Neo4j write failed for DOC-3 (DOC-3.md): {CONSTRAINT_MESSAGE}",
    ]
    failures = [r for r in caplog.records if "[FAIL]" in r.getMessage()]
    assert all(r.levelno == logging.ERROR for r in failures)


def test_successful_writes_log_ok_and_raise_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    kg_pipeline = WriterThenResolver(FakeDriver(), rejected=set())

    with caplog.at_level(logging.INFO, logger=pipeline.logger.name):
        _process(monkeypatch, tmp_path, kg_pipeline, ["DOC-1", "DOC-2"])

    assert [m for m in _messages(caplog) if "[OK]" in m or "[FAIL]" in m] == [
        "  [OK] Pipeline complete for DOC-1",
        "  [OK] Pipeline complete for DOC-2",
    ]


def test_a_run_with_no_writer_result_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class NoWriter(WriterThenResolver):
        async def run_async(self, *, text: str, document_metadata: dict[str, Any]) -> Any:
            return SimpleNamespace(run_id="missing")

    with pytest.raises(pipeline.ManualWriteError, match="DOC-1"):
        _process(monkeypatch, tmp_path, NoWriter(FakeDriver(), rejected=set()), ["DOC-1"])


def test_the_enrichment_pipeline_keeps_the_writer_out_of_the_final_result() -> None:
    """The real ``SimpleKGPipeline`` makes the resolver the only leaf.

    So the writer's status is read from the result store under the task name
    ``writer``, not from ``PipelineResult.result``.
    """
    kg_pipeline, _ = pipeline._create_pipeline(
        FakeDriver().driver,
        "db",
        provider="openai",
        openai_api_key="sk-test",
        llm_model="m",
        llm_max_tokens=1,
        embedding_model="e",
        embedding_dimensions=1,
        chunk_size=100,
        chunk_overlap=0,
    )

    graph = kg_pipeline.runner.pipeline
    assert not graph.get_node_by_name("writer").is_leaf()
    assert graph.get_node_by_name("resolver").is_leaf()
