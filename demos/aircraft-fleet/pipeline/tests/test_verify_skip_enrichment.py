"""verify --strict --skip-enrichment fails on operational problems only.

./setup.sh load-operational builds a graph with no enrichment, so the
enrichment checks warn there while the operational checks still fail.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from populate_aircraft_db import loader
from populate_aircraft_db import main as loader_main
from populate_aircraft_db.schema import CONSTRAINTS

FakeResult = tuple[list[dict[str, Any]], None, None]


class FakeDriver:
    """Answer verify's queries for a graph that holds only operational data."""

    def __init__(self, *, missing_label: str | None = None) -> None:
        self.label_counts = dict.fromkeys(loader.OPERATIONAL_LABELS, 2)
        if missing_label is not None:
            del self.label_counts[missing_label]
        self.rel_counts = dict.fromkeys(loader.OPERATIONAL_RELATIONSHIP_TYPES, 2)

    def execute_query(self, query: str, **kwargs: object) -> FakeResult:
        if "labels(n)" in query:
            rows = [{"label": label, "count": n} for label, n in self.label_counts.items()]
        elif "type(r)" in query:
            rows = [{"rel_type": rel, "count": n} for rel, n in self.rel_counts.items()]
        elif "SHOW INDEXES" in query:
            rows = []
        elif "SHOW CONSTRAINTS" in query:
            rows = [
                {
                    "name": f"{label}_{prop}",
                    "type": "UNIQUENESS",
                    "labelsOrTypes": [label],
                    "properties": [prop],
                }
                for label, prop in CONSTRAINTS
            ]
        else:
            rows = [{"count": 0}]
        return rows, None, None


def _verify(driver: FakeDriver, *, skip_enrichment: bool) -> bool:
    return loader.verify(driver, "db", strict=True, skip_enrichment=skip_enrichment)  # type: ignore[arg-type]


def test_missing_enrichment_alone_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert _verify(FakeDriver(), skip_enrichment=True)

    output = capsys.readouterr().out
    assert "[WARN] Chunk has no enrichment nodes" in output
    assert "[WARN] missing index maintenanceChunkEmbeddings" in output
    assert "[WARN] missing uniqueness constraint AircraftModel.name" in output
    assert "[FAIL]" not in output.split("Warnings:")[1]


def test_missing_enrichment_fails_without_the_flag() -> None:
    assert not _verify(FakeDriver(), skip_enrichment=False)


def test_an_operational_failure_still_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert not _verify(FakeDriver(missing_label="Aircraft"), skip_enrichment=True)

    failures = capsys.readouterr().out.split("Failures:")[1]
    assert "[FAIL] Aircraft has no nodes" in failures
    assert "enrichment" not in failures


def _run_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    driver: FakeDriver,
    *,
    code_reason: str | None = None,
) -> Any:
    # Two rows per node CSV, matching the fake graph's operational counts.
    for _, filename, _ in loader._NODE_DEFINITIONS:
        (tmp_path / filename).write_text("id\n1\n2\n", encoding="utf-8")
    settings = SimpleNamespace(neo4j_uri="bolt://example", neo4j_database="db", data_dir=tmp_path)
    monkeypatch.setattr(loader_main, "Settings", lambda: settings)
    monkeypatch.setattr(loader_main, "_connect", lambda s: nullcontext(driver))
    monkeypatch.setattr(loader_main, "_expected_embedding_dims", lambda s: 1024)
    monkeypatch.setattr(loader_main, "stale_reason", lambda data_dir: code_reason)
    monkeypatch.setattr(loader_main, "dataset_mismatch", lambda *args: None)
    return CliRunner().invoke(loader_main.app, ["verify", "--strict", "--skip-enrichment"])


def test_the_command_exits_0_when_only_enrichment_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _run_cli(monkeypatch, tmp_path, FakeDriver())

    assert result.exit_code == 0, result.output
    assert "[OK] Verification completed with warnings." in result.output


def test_the_command_exits_1_on_an_operational_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _run_cli(monkeypatch, tmp_path, FakeDriver(missing_label="Flight"))

    assert result.exit_code == 1, result.output
    assert "[FAIL] Flight has no nodes" in result.output


def test_the_command_exits_1_on_stale_csvs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = _run_cli(monkeypatch, tmp_path, FakeDriver(), code_reason="generator code changed")

    assert result.exit_code == 1, result.output
    assert "[FAIL] Generated CSVs are stale: generator code changed." in result.output
