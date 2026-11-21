"""Console output helpers: column widths, cut values, None, and row limits."""

from __future__ import annotations

import pytest

from populate_aircraft_db.display import records_table, show_cypher, table, val


def test_val_cuts_long_values_and_dashes_none() -> None:
    assert val(None) == "—"
    assert val("abcdef", max_len=4) == "abc…"
    assert val("abcdef") == "abcdef"


def test_table_fits_columns_and_caps_width(capsys: pytest.CaptureFixture[str]) -> None:
    table(["id", "text"], [["a1", "x" * 80], ["a22", None]])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "  " + "id".ljust(4) + "  " + "text".ljust(50)
    assert lines[2] == "  " + "a1".ljust(4) + "  " + "x" * 49 + "…"
    assert lines[3].rstrip() == "  a22   —"


def test_table_without_rows(capsys: pytest.CaptureFixture[str]) -> None:
    records_table([])
    assert capsys.readouterr().out == "  (no results)\n\n"


def test_records_table_shows_at_most_max_rows(capsys: pytest.CaptureFixture[str]) -> None:
    records_table([{"n": i} for i in range(15)], max_rows=3)
    body = capsys.readouterr().out.splitlines()[2:]
    assert [line.strip() for line in body if line.strip()] == ["0", "1", "2"]


def test_show_cypher_indents_under_its_label(capsys: pytest.CaptureFixture[str]) -> None:
    show_cypher("MATCH (a)\n  WHERE a.x\nRETURN a\n", label="Generated Cypher")
    assert capsys.readouterr().out == (
        "  Generated Cypher:\n    MATCH (a)\n      WHERE a.x\n    RETURN a\n\n"
    )


def test_show_cypher_removes_the_indent_of_an_indented_multiline_query(
    capsys: pytest.CaptureFixture[str],
) -> None:
    query = """
        MATCH (a:Aircraft)
          WHERE a.model = $model
        RETURN a.tail_number
    """
    show_cypher(query)
    assert capsys.readouterr().out == (
        "  Cypher:\n"
        "    MATCH (a:Aircraft)\n"
        "      WHERE a.model = $model\n"
        "    RETURN a.tail_number\n"
        "\n"
    )
