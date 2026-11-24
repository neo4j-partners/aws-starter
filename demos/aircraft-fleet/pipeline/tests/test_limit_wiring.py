"""Enrich and load-operational call the limit steps in order.

Every graph and LLM step is replaced by a stub that records its call, so
these tests need no Neo4j server.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from populate_aircraft_db import main, pipeline

DRIVER = object()
SOURCES = [pipeline.LimitSource("EGT Takeoff - A320-200", "DOC", 0, 1)]


def _record(
    monkeypatch: pytest.MonkeyPatch, module: object, names: list[str], calls: list[str]
) -> None:
    """Replace each named function on module with a stub that appends its name."""

    def stub(name: str):
        def record(*_args: object, **_kwargs: object) -> None:
            calls.append(name)

        return record

    for name in names:
        monkeypatch.setattr(module, name, stub(name))


def _record_limits(
    monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace, calls: list[str]
) -> None:
    """Stub the limit lookup and linking, and check what they are passed."""

    def limit_sources(data_dir: Path, document_dir: Path) -> list[pipeline.LimitSource]:
        assert (data_dir, document_dir) == (settings.data_dir, settings.document_dir)
        calls.append("limit_sources")
        return SOURCES

    def with_sources(name: str):
        def record(driver: object, database: str, sources: list[pipeline.LimitSource]) -> None:
            assert (driver, database, sources) == (DRIVER, "db", SOURCES)
            calls.append(name)

        return record

    monkeypatch.setattr(pipeline, "limit_sources", limit_sources)
    monkeypatch.setattr(pipeline, "check_limit_nodes", with_sources("check_limit_nodes"))
    monkeypatch.setattr(pipeline, "link_limits_to_chunks", with_sources("link_limits_to_chunks"))


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        neo4j_uri="bolt://example",
        neo4j_database="db",
        data_dir=tmp_path / "data",
        document_dir=tmp_path / "documents",
        enrich_sample_size=0,
        chunk_size=800,
        chunk_overlap=100,
    )


def test_enrich_checks_the_limits_before_the_clear_and_links_them_after_fusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    settings = _settings(tmp_path)
    _record_limits(monkeypatch, settings, calls)
    _record(
        monkeypatch,
        pipeline,
        [
            "clear_enrichment_data",
            "process_all_documents",
            "link_to_existing_graph",
            "validate_enrichment",
        ],
        calls,
    )
    _record(
        monkeypatch,
        main,
        [
            "drop_extraction_constraints",
            "create_constraints",
            "create_extraction_constraints",
            "create_embedding_indexes",
        ],
        calls,
    )
    creds = main._LLMCredentials(
        provider="bedrock",
        openai_key=None,
        llm_model="model",
        llm_max_tokens=1,
        embedding_model="embedder",
        embedding_dims=1,
    )

    main._run_enrich(DRIVER, settings, creds)

    assert calls == [
        "limit_sources",
        "check_limit_nodes",
        "clear_enrichment_data",
        "drop_extraction_constraints",
        "create_constraints",
        "process_all_documents",
        "create_extraction_constraints",
        "create_embedding_indexes",
        "link_to_existing_graph",
        "link_limits_to_chunks",
        "validate_enrichment",
    ]


def test_load_operational_relinks_the_limits_after_the_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    settings = _settings(tmp_path)
    monkeypatch.setattr(main, "Settings", lambda: settings)
    monkeypatch.setattr(main, "_connect", lambda s: nullcontext(DRIVER))
    _record_limits(monkeypatch, settings, calls)
    _record(monkeypatch, pipeline, ["link_to_existing_graph", "validate_enrichment"], calls)
    _record(
        monkeypatch,
        main,
        [
            "create_constraints",
            "create_indexes",
            "create_fulltext_indexes",
            "load_operational_graph",
        ],
        calls,
    )

    result = CliRunner().invoke(main.app, ["load-operational"])

    assert result.exit_code == 0, result.output
    assert calls == [
        "create_constraints",
        "create_indexes",
        "create_fulltext_indexes",
        "load_operational_graph",
        "link_to_existing_graph",
        "limit_sources",
        "link_limits_to_chunks",
        "validate_enrichment",
    ]
