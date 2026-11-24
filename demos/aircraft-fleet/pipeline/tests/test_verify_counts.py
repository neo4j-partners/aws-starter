"""verify compares each loaded label's node count with its CSV row count."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from populate_aircraft_db import loader
from populate_aircraft_db import main as loader_main

# Two rows per CSV, one with a quoted newline, so the count is of records.
ROWS = 2


def _write_csvs(data_dir: Path) -> dict[str, int]:
    """Write every counted CSV with ROWS records and return matching graph counts."""
    for _, filename in loader._COUNTED_CSVS:
        (data_dir / filename).write_text('id,note\n1,"two\nlines"\n2,plain\n', encoding="utf-8")
    return {label: ROWS for label, _ in loader._COUNTED_CSVS}


def _check(label_counts: dict[str, int], data_dir: Path, *, strict: bool = False):
    result = loader._VerifyResult(strict=strict)
    loader._check_csv_counts(label_counts, data_dir, result)
    return result


def test_counts_that_match_the_csvs_pass(tmp_path: Path) -> None:
    counts = _write_csvs(tmp_path)

    result = _check(counts, tmp_path)

    assert result.warnings == [] and result.failures == []


def test_a_label_with_more_nodes_than_csv_rows_is_reported(tmp_path: Path) -> None:
    # A direct load over an earlier, larger dataset leaves its extra nodes.
    counts = _write_csvs(tmp_path)
    counts["Aircraft"] = 3

    result = _check(counts, tmp_path)

    assert result.warnings == [
        f"Aircraft has 3 nodes, but nodes_aircraft.csv in {tmp_path} has 2 rows"
    ]


def test_operating_limits_are_compared_with_their_csv(tmp_path: Path) -> None:
    # The load writes the limits from operating_limits.csv, so extra limits
    # left by an older graph show up here.
    counts = _write_csvs(tmp_path)
    counts["OperatingLimit"] = 5

    result = _check(counts, tmp_path)

    assert result.warnings == [
        f"OperatingLimit has 5 nodes, but operating_limits.csv in {tmp_path} has 2 rows"
    ]


def test_a_count_mismatch_fails_in_strict_mode(tmp_path: Path) -> None:
    counts = _write_csvs(tmp_path)
    counts["Reading"] = 1

    result = _check(counts, tmp_path, strict=True)

    assert result.failures == [
        f"Reading has 1 nodes, but nodes_readings.csv in {tmp_path} has 2 rows"
    ]


def test_a_missing_csv_is_reported_once_per_file(tmp_path: Path) -> None:
    counts = _write_csvs(tmp_path)
    (tmp_path / "nodes_removals.csv").unlink()

    result = _check(counts, tmp_path)

    assert result.warnings == [
        f"nodes_removals.csv is missing from {tmp_path}, so the Removal count was not compared"
    ]


def test_a_directory_with_no_csvs_gives_one_warning(tmp_path: Path) -> None:
    result = _check({"Aircraft": 30}, tmp_path)

    assert result.warnings == [
        f"{tmp_path} has no node CSVs, so node counts were not compared with them"
    ]


def test_the_verify_command_compares_against_the_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = SimpleNamespace(neo4j_uri="bolt://example", neo4j_database="db", data_dir=tmp_path)
    calls: list[dict[str, object]] = []

    def fake_verify(*args: object, **kwargs: object) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr(loader_main, "Settings", lambda: settings)
    monkeypatch.setattr(loader_main, "_connect", lambda s: nullcontext(object()))
    monkeypatch.setattr(loader_main, "_expected_embedding_dims", lambda s: 1024)
    monkeypatch.setattr(loader_main, "stale_reason", lambda data_dir: None)
    monkeypatch.setattr(loader_main, "dataset_mismatch", lambda *args: None)
    monkeypatch.setattr(loader_main, "verify", fake_verify)

    loader_main.verify_cmd(strict=False)

    assert [call["data_dir"] for call in calls] == [tmp_path]
