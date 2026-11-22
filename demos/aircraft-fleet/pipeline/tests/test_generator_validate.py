"""generate-data validate checks every ID reference in the generated CSVs."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from generator.main import app, generate
from generator.writers import CSV_COLUMNS

runner = CliRunner()

# Every reference column, with the node file whose IDs it must match.
REFERENCES = [
    ("nodes_readings.csv", "sensor_id"),
    *(
        (filename, column)
        for filename, columns in CSV_COLUMNS.items()
        if filename.startswith("rels_")
        for column in columns
    ),
]


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("validate")
    generate(aircraft=3, airports=40, days=3, seed=42, output=output)
    return output


@pytest.fixture
def copy(dataset: Path, tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(dataset, target)
    return target


def _set_first_row(path: Path, column: str, value: str) -> None:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    rows[0][column] = value
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_a_generated_dataset_passes(dataset: Path) -> None:
    result = runner.invoke(app, ["validate", str(dataset)])

    assert result.exit_code == 0, result.output
    assert "All referential integrity checks passed" in result.output


def test_every_relationship_column_is_covered() -> None:
    # Two columns per relationship file, plus the readings' sensor_id.
    rels = [name for name in CSV_COLUMNS if name.startswith("rels_")]
    assert len(REFERENCES) == 2 * len(rels) + 1


@pytest.mark.parametrize(("filename", "column"), REFERENCES)
def test_a_dangling_reference_fails(copy: Path, filename: str, column: str) -> None:
    _set_first_row(copy / filename, column, "MISSING")

    result = runner.invoke(app, ["validate", str(copy)])

    assert result.exit_code == 1, result.output
    assert f"{filename}:2: {column}='MISSING' not in" in result.output


@pytest.mark.parametrize(
    ("filename", "column"),
    [("nodes_readings.csv", "reading_id"), ("nodes_removals.csv", ":ID(Removal)")],
)
def test_a_duplicate_id_fails(copy: Path, filename: str, column: str) -> None:
    with (copy / filename).open(newline="", encoding="utf-8") as f:
        second = list(csv.DictReader(f))[1][column]
    _set_first_row(copy / filename, column, second)

    result = runner.invoke(app, ["validate", str(copy)])

    assert result.exit_code == 1, result.output
    assert f"{filename}: 1 duplicate {column} value(s)" in result.output


def test_a_missing_relationship_file_fails(copy: Path) -> None:
    (copy / "rels_event_system.csv").unlink()

    result = runner.invoke(app, ["validate", str(copy)])

    assert result.exit_code == 1, result.output
    assert "Missing file: rels_event_system.csv" in result.output


def test_a_renamed_reference_column_fails(copy: Path) -> None:
    path = copy / "rels_flight_delay.csv"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[0] = lines[0].replace(":END_ID(Delay)", ":END_ID(Delays)")
    path.write_text("".join(lines), encoding="utf-8")

    result = runner.invoke(app, ["validate", str(copy)])

    assert result.exit_code == 1, result.output
    assert "rels_flight_delay.csv: missing column :END_ID(Delay)" in result.output
