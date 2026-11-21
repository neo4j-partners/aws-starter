"""Library status lines are log records, and the CLI shows only this package's."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import nullcontext
from pathlib import Path
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
def test_cli_logging_shows_package_info_and_hides_other_info(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main._configure_logging()
    main._configure_logging()

    logging.getLogger("populate_aircraft_db.loader").info("  [OK] package line")
    logging.getLogger("httpx").info("HTTP Request: other library")

    assert capsys.readouterr().out == "  [OK] package line\n"


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


@pytest.mark.usefixtures("restore_package_logger")
def test_cli_logs_to_each_invocations_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    # CliRunner gives each invoke its own stdout and closes it afterwards,
    # so the second invoke must not touch the first one's stream.
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
    runner = CliRunner()

    results = [runner.invoke(main.app, ["clean"]) for _ in range(2)]

    for result in results:
        assert result.exit_code == 0, result.output
        assert result.output.count("  [OK] Database cleared\n") == 1
    assert logging.getLogger(PACKAGE).propagate is False


@pytest.mark.usefixtures("restore_package_logger")
def test_cli_logging_sends_warnings_to_stderr_and_info_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main._configure_logging()
    main._configure_logging()

    logging.getLogger("populate_aircraft_db.bedrock_structured").info("retry line")
    logging.getLogger("populate_aircraft_db.loader").warning("[WARN] warning line")
    logging.getLogger("populate_aircraft_db.pipeline").error("error line")

    captured = capsys.readouterr()
    assert captured.out == "retry line\n"
    assert captured.err == "[WARN] warning line\nerror line\n"


class _Terminal:
    """Record what reaches a terminal that both stdout and stderr write to."""

    def __init__(self) -> None:
        self.lines: list[str] = []


class _BlockBufferedStream:
    """Hold writes until flush, like stdout piped to tee."""

    def __init__(self, terminal: _Terminal) -> None:
        self.terminal = terminal
        self.pending: list[str] = []

    def write(self, text: str) -> int:
        self.pending.append(text)
        return len(text)

    def flush(self) -> None:
        self.terminal.lines.append("".join(self.pending))
        self.pending.clear()


class _UnbufferedStream:
    """Pass each write straight through, like stderr."""

    def __init__(self, terminal: _Terminal) -> None:
        self.terminal = terminal

    def write(self, text: str) -> int:
        self.terminal.lines.append(text)
        return len(text)

    def flush(self) -> None:
        return None


@pytest.mark.usefixtures("restore_package_logger")
def test_cli_warning_follows_earlier_stdout_output(monkeypatch: pytest.MonkeyPatch) -> None:
    # With setup.sh 2>&1 | tee, stdout is block buffered and stderr is not,
    # so a warning could reach the terminal before earlier print() output.
    terminal = _Terminal()
    monkeypatch.setattr(sys, "stdout", _BlockBufferedStream(terminal))
    monkeypatch.setattr(sys, "stderr", _UnbufferedStream(terminal))
    main._configure_logging()

    print("Stage 3: earlier output")
    logging.getLogger("populate_aircraft_db.loader").warning("[WARN] warning line")

    assert terminal.lines == ["Stage 3: earlier output\n", "[WARN] warning line\n"]


class _BrokenPipeStream:
    """Fail every flush, like stdout piped to a reader that has exited."""

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        raise BrokenPipeError(32, "Broken pipe")


@pytest.mark.usefixtures("restore_package_logger")
@pytest.mark.parametrize("stdout", [None, _BrokenPipeStream()], ids=["none", "broken-pipe"])
def test_cli_warning_reaches_stderr_when_stdout_cannot_flush(
    monkeypatch: pytest.MonkeyPatch, stdout: object
) -> None:
    terminal = _Terminal()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", _UnbufferedStream(terminal))
    main._configure_logging()

    logging.getLogger("populate_aircraft_db.loader").warning("[WARN] warning line")

    assert terminal.lines == ["[WARN] warning line\n"]


def _fake_loader(monkeypatch: pytest.MonkeyPatch, skipped: int) -> None:
    """Load one node type and two relationship types, five rows each."""
    monkeypatch.setattr(loader, "_NODE_DEFINITIONS", [("Aircraft", "a.csv", "nodes")])
    monkeypatch.setattr(
        loader,
        "_REL_DEFINITIONS",
        [("HAS_SYSTEM", "r1.csv", "rels"), ("HAS_SENSOR", "r2.csv", "rels")],
    )
    monkeypatch.setattr(loader, "iter_csv_batches", lambda data_dir, filename: iter([]))
    monkeypatch.setattr(
        loader,
        "_run_in_batches",
        lambda driver, database, batches, query: (
            (5 + skipped, skipped) if query == "nodes" else (5, 0)
        ),
    )


_LOADER_LINES = [
    "Loading Aircraft nodes...",
    "  [OK] Loaded 5 Aircraft nodes.",
    "Loading HAS_SYSTEM relationships...",
    "  [OK] Loaded 5 HAS_SYSTEM relationships.",
    "Loading HAS_SENSOR relationships...",
    "  [OK] Loaded 5 HAS_SENSOR relationships.",
]


@pytest.mark.usefixtures("restore_package_logger")
@pytest.mark.parametrize(
    ("skipped", "summary"),
    [
        (0, "[OK] No readings skipped."),
        (3, "[WARN] Skipped 3 readings whose sensor_id matches no Sensor."),
    ],
)
def test_cli_load_shows_blank_lines_between_load_phases(
    monkeypatch: pytest.MonkeyPatch, skipped: int, summary: str
) -> None:
    settings = SimpleNamespace(neo4j_uri="bolt://example", neo4j_database="db", data_dir=None)
    monkeypatch.setattr(main, "Settings", lambda: settings)
    monkeypatch.setattr(main, "_connect", lambda s: nullcontext(object()))
    for name in ("create_constraints", "create_indexes", "create_fulltext_indexes"):
        monkeypatch.setattr(main, name, lambda driver, database: None)
    monkeypatch.setattr(pipeline, "link_to_existing_graph", lambda driver, database: None)
    monkeypatch.setattr(pipeline, "validate_enrichment", lambda driver, database: None)
    _fake_loader(monkeypatch, skipped)

    result = CliRunner().invoke(main.app, ["load-operational"])

    assert result.exit_code == 0, result.output
    loaded = result.output.split("Creating fulltext indexes...\n\n")[1].split("Linking")[0]
    assert loaded == "\n".join([*_LOADER_LINES[:2], "", *_LOADER_LINES[2:], "", summary, "", ""])


@pytest.mark.parametrize("skipped", [0, 3])
def test_load_phase_records_have_no_empty_messages(
    package_logs: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, skipped: int
) -> None:
    _fake_loader(monkeypatch, skipped)

    loader.load_operational_graph(CountDriver(), "db", None)

    records = [r for r in package_logs.records if r.name == "populate_aircraft_db.loader"]
    assert [r.getMessage() for r in records][:-1] == _LOADER_LINES
    assert all(r.getMessage().strip() for r in records)
    assert [i for i, r in enumerate(records) if getattr(r, "blank_before", False)] == [2, 6]


def _process_two_documents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakePipeline:
        async def run_async(self, **kwargs: Any) -> None:
            return None

    docs = [
        SimpleNamespace(filename=f"{n}.md", aircraft_type="T", title="t", document_id=n)
        for n in ("DOC-1", "DOC-2")
    ]
    for doc in docs:
        (tmp_path / doc.filename).write_text("abc", encoding="utf-8")
    monkeypatch.setattr(pipeline, "DOCUMENTS", docs)
    monkeypatch.setattr(
        pipeline, "_create_pipeline", lambda *a, **k: (FakePipeline(), SimpleNamespace())
    )
    pipeline.process_all_documents(
        CountDriver(),
        "db",
        tmp_path,
        provider="bedrock",
        openai_api_key=None,
        anthropic_api_key=None,
        llm_model="m",
        llm_max_tokens=1,
        embedding_model="e",
        embedding_dimensions=1,
        chunk_size=10,
        chunk_overlap=0,
    )


_DOCUMENT_LINES = [
    "Processing: DOC-1.md",
    "  Read 3 characters.",
    "  [OK] Pipeline complete for DOC-1",
    "Processing: DOC-2.md",
    "  Read 3 characters.",
    "  [OK] Pipeline complete for DOC-2",
]


@pytest.mark.usefixtures("restore_package_logger")
def test_cli_logging_shows_a_blank_line_before_each_document(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    main._configure_logging()

    _process_two_documents(monkeypatch, tmp_path)

    assert capsys.readouterr().out == "\n".join(
        ["", *_DOCUMENT_LINES[:3], "", *_DOCUMENT_LINES[3:], ""]
    )


def test_document_records_have_no_empty_messages(
    package_logs: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _process_two_documents(monkeypatch, tmp_path)

    records = [r for r in package_logs.records if r.name == "populate_aircraft_db.pipeline"]
    assert [r.getMessage() for r in records] == _DOCUMENT_LINES
    assert [i for i, r in enumerate(records) if getattr(r, "blank_before", False)] == [0, 3]
