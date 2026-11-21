"""Library status lines are log records, and the CLI shows only this package's."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from populate_aircraft_db import loader, main, pipeline
from populate_aircraft_db.schema import CONSTRAINTS, create_constraints

PACKAGE = "populate_aircraft_db"


class CountDriver:
    """Return one row with count 3 for every query."""

    def execute_query(self, cypher: str, /, **params: Any) -> tuple[list[dict], None, None]:
        return [{"count": 3}], None, None


@pytest.fixture
def package_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger=PACKAGE)
    return caplog


@pytest.fixture
def restore_package_logger() -> Iterator[None]:
    package_logger = logging.getLogger(PACKAGE)
    saved = (list(package_logger.handlers), package_logger.level, package_logger.propagate)
    yield
    package_logger.handlers[:] = saved[0]
    package_logger.setLevel(saved[1])
    package_logger.propagate = saved[2]


def _records(caplog: pytest.LogCaptureFixture, name: str) -> list[tuple[int, str]]:
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == name]


def test_schema_setup_logs_each_constraint(package_logs: pytest.LogCaptureFixture) -> None:
    create_constraints(CountDriver(), "db")
    assert _records(package_logs, "populate_aircraft_db.schema") == [
        (logging.INFO, f"  [OK] Constraint: {label}.{prop}") for label, prop in CONSTRAINTS
    ]


def test_load_nodes_logs_progress(
    package_logs: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loader, "_NODE_DEFINITIONS", [("Reading", "r.csv", "q")])
    monkeypatch.setattr(loader, "iter_csv_batches", lambda data_dir, filename: iter([]))
    monkeypatch.setattr(loader, "_run_in_batches", lambda *args: (10, 2))

    assert loader.load_nodes(CountDriver(), "db", None) == 2
    assert _records(package_logs, "populate_aircraft_db.loader") == [
        (logging.INFO, "Loading Reading nodes..."),
        (logging.INFO, "  [OK] Loaded 8 Reading nodes."),
    ]


@pytest.mark.parametrize(
    ("skipped", "expected"),
    [
        (5, (logging.WARNING, "[WARN] Skipped 5 readings whose sensor_id matches no Sensor.")),
        (0, (logging.INFO, "[OK] No readings skipped.")),
    ],
)
def test_skipped_readings_log_a_warning(
    package_logs: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    skipped: int,
    expected: tuple[int, str],
) -> None:
    monkeypatch.setattr(loader, "load_nodes", lambda *args: skipped)
    monkeypatch.setattr(loader, "load_relationships", lambda *args: None)

    loader.load_operational_graph(CountDriver(), "db", None)
    assert _records(package_logs, "populate_aircraft_db.loader") == [expected]


def test_clear_database_logs_counts(
    package_logs: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loader, "delete_all_relationships", lambda driver, database: 7)
    monkeypatch.setattr(loader, "detach_delete_nodes", lambda driver, database: 4)

    loader.clear_database(CountDriver(), "db")
    assert _records(package_logs, "populate_aircraft_db.loader") == [
        (logging.INFO, "Clearing database..."),
        (logging.INFO, "  [OK] Database cleared (7 relationships, 4 nodes deleted)."),
    ]


def test_cross_links_log_each_count(package_logs: pytest.LogCaptureFixture) -> None:
    pipeline.link_to_existing_graph(CountDriver(), "db")
    assert _records(package_logs, "populate_aircraft_db.pipeline") == [
        (logging.INFO, f"  [OK] 3 {link}")
        for link in [
            "Document -[:APPLIES_TO]-> Aircraft",
            "AircraftModel -[:DESCRIBES_MODEL]-> Aircraft",
            "SystemReference -[:DESCRIBES_SYSTEM]-> System",
            "ComponentReference -[:DESCRIBES_COMPONENT]-> Component",
            "Sensor -[:HAS_LIMIT]-> OperatingLimit",
        ]
    ]


def test_clear_enrichment_logs_the_total(
    package_logs: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "detach_delete_nodes", lambda driver, database, label: 1)

    pipeline.clear_enrichment_data(CountDriver(), "db")
    records = _records(package_logs, "populate_aircraft_db.pipeline")
    assert records[0] == (
        logging.INFO,
        "Clearing enrichment data (Documents, Chunks, extracted entities)...",
    )
    assert records[1][0] == logging.INFO
    assert records[1][1].startswith("  [OK] Cleared ")
    assert len(records) == 2


@pytest.mark.usefixtures("restore_package_logger")
def test_cli_logging_shows_package_info_and_hides_other_info() -> None:
    first, second = io.StringIO(), io.StringIO()
    main._configure_logging(first)
    main._configure_logging(second)

    logging.getLogger("populate_aircraft_db.loader").info("  [OK] package line")
    logging.getLogger("httpx").info("HTTP Request: other library")

    assert first.getvalue() == ""
    assert second.getvalue() == "  [OK] package line\n"


@pytest.mark.usefixtures("restore_package_logger")
def test_cli_command_prints_library_log_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(neo4j_uri="bolt://example", neo4j_database="db")
    monkeypatch.setattr(main, "Settings", lambda: settings)
    monkeypatch.setattr(main, "_connect", lambda s: nullcontext(object()))
    monkeypatch.setattr(
        main,
        "clear_database",
        lambda driver, database: logging.getLogger("populate_aircraft_db.loader").info(
            "  [OK] Database cleared"
        ),
    )

    result = CliRunner().invoke(main.app, ["clean"])

    assert result.exit_code == 0, result.output
    assert result.output == ("Connecting to bolt://example...\n  [OK] Database cleared\n\nDone.\n")
