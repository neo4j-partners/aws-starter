"""Enrich and load-operational call the limit steps in order.

Every graph and LLM step is replaced by a stub that records its call, so
these tests need no Neo4j server.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner, Result

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
    monkeypatch: pytest.MonkeyPatch,
    settings: SimpleNamespace,
    calls: list[str],
    unlinked: list[str] | None = None,
) -> None:
    """Stub the limit lookup and linking, and check what they are passed.

    The linking stub reports ``unlinked`` as the limits left with no chunk.
    """

    def limit_sources(data_dir: Path, document_dir: Path) -> list[pipeline.LimitSource]:
        assert (data_dir, document_dir) == (settings.data_dir, settings.document_dir)
        calls.append("limit_sources")
        return SOURCES

    def with_sources(name: str, returns: list[str] | None = None):
        def record(
            driver: object, database: str, sources: list[pipeline.LimitSource]
        ) -> list[str] | None:
            assert (driver, database, sources) == (DRIVER, "db", SOURCES)
            calls.append(name)
            return returns

        return record

    monkeypatch.setattr(pipeline, "limit_sources", limit_sources)
    monkeypatch.setattr(pipeline, "check_limit_nodes", with_sources("check_limit_nodes"))
    monkeypatch.setattr(
        pipeline,
        "link_limits_to_chunks",
        with_sources("link_limits_to_chunks", unlinked or []),
    )


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


UNLINKED = ["EGT Cruise Max - B737-800", "N1 Takeoff - A320-200"]


def _record_enrich(
    monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace, calls: list[str]
) -> None:
    """Stub every enrich step except the limit linking, which ``_record_limits`` stubs."""
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


def _invoke_enrich_with_unlinked_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_size: int
) -> tuple[Result, list[str]]:
    """Run the enrich CLI with every step stubbed and two limits left unlinked."""
    calls: list[str] = []
    settings = _settings(tmp_path)
    settings.enrich_sample_size = sample_size
    _record_limits(monkeypatch, settings, calls, unlinked=UNLINKED)
    _record_enrich(monkeypatch, settings, calls)
    monkeypatch.setattr(main, "Settings", lambda: settings)
    creds = main._LLMCredentials(
        provider="bedrock",
        openai_key=None,
        llm_model="model",
        llm_max_tokens=1,
        embedding_model="embedder",
        embedding_dims=1,
    )
    monkeypatch.setattr(main, "_resolve_llm_credentials", lambda s: creds)
    monkeypatch.setattr(main, "_connect", lambda s: nullcontext(DRIVER))
    return CliRunner().invoke(main.app, ["enrich"]), calls


def test_a_full_enrich_fails_and_names_the_limits_left_with_no_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, calls = _invoke_enrich_with_unlinked_limits(tmp_path, monkeypatch, sample_size=0)

    assert result.exit_code != 0
    assert isinstance(result.exception, pipeline.UnlinkedLimitsError)
    assert str(result.exception) == (
        "2 operating limits have no chunk: EGT Cruise Max - B737-800, N1 Takeoff - A320-200"
    )
    assert calls[-2:] == ["link_to_existing_graph", "link_limits_to_chunks"]


def test_a_sampled_enrich_warns_about_the_limits_left_with_no_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, calls = _invoke_enrich_with_unlinked_limits(tmp_path, monkeypatch, sample_size=3)

    assert result.exit_code == 0, result.output
    assert (
        "  [WARN] 2 operating limits have no chunk: "
        "EGT Cruise Max - B737-800, N1 Takeoff - A320-200. "
        "Sampling truncated the manuals before their source text, with ENRICH_SAMPLE_SIZE=3.\n"
    ) in result.output
    assert calls[-1] == "validate_enrichment"


def test_load_operational_warns_about_limits_left_with_no_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    settings = _settings(tmp_path)
    monkeypatch.setattr(main, "Settings", lambda: settings)
    monkeypatch.setattr(main, "_connect", lambda s: nullcontext(DRIVER))
    _record_limits(monkeypatch, settings, calls, unlinked=UNLINKED)
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
    assert (
        "  [WARN] 2 operating limits have no chunk: "
        "EGT Cruise Max - B737-800, N1 Takeoff - A320-200. "
        "The next enrich relinks them.\n"
    ) in result.output
    assert calls[-1] == "validate_enrichment"


class LinkDriver:
    """Return one summary row from the limit-linking query."""

    def __init__(self, unlinked: list[str]) -> None:
        self.row = {"limits": 3, "links": 4, "unlinked": unlinked}

    def execute_query(self, *_args: object, **_kwargs: object) -> tuple[list, None, None]:
        return [self.row], None, None


@pytest.mark.parametrize(
    ("unlinked", "line"),
    [
        ([], "  [OK] 4 OperatingLimit -[:FROM_CHUNK]-> Chunk (3 limits, 0 with no chunk)"),
        (
            ["N1 Takeoff - A320-200", "EGT Cruise Max - B737-800"],
            "  4 OperatingLimit -[:FROM_CHUNK]-> Chunk (3 limits, 2 with no chunk)",
        ),
    ],
)
def test_link_limits_to_chunks_returns_the_unlinked_names_sorted(
    caplog: pytest.LogCaptureFixture, unlinked: list[str], line: str
) -> None:
    with caplog.at_level(logging.INFO, logger=pipeline.logger.name):
        names = pipeline.link_limits_to_chunks(LinkDriver(unlinked), "db", SOURCES)

    assert names == sorted(unlinked)
    assert [r.getMessage() for r in caplog.records] == [line]
