"""Enrich finds each generated limit's source text inside its manual block."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from generator.limits import LIMITS_FILE
from generator.manuals import MANUALS_DIR
from populate_aircraft_db.config import _DATA_DIR
from populate_aircraft_db.pipeline import (
    DOCUMENTS,
    limit_sources,
    read_manual,
    read_manual_text,
    strip_comments,
)

_COLUMNS = [
    "name",
    "parameterName",
    "regime",
    "aircraftType",
    "unit",
    "minValue",
    "maxValue",
    "nominalValue",
    "sourceBlock",
    "sourceText",
]
_MARKER = "<!-- {} GENERATED: {} -->\n"


def _raw_bodies(raw: str) -> dict[str, str]:
    """Each block's raw body: the lines between its BEGIN and END markers."""
    bodies: dict[str, str] = {}
    open_id: str | None = None
    lines: list[str] = []
    for line in raw.splitlines(keepends=True):
        if line.startswith("<!-- BEGIN GENERATED: "):
            open_id, lines = line.split(": ")[1].removesuffix(" -->\n"), []
        elif line.startswith("<!-- END GENERATED: "):
            bodies[open_id] = "".join(lines)  # type: ignore[index]
            open_id = None
        elif open_id is not None:
            lines.append(line)
    return bodies


@pytest.mark.parametrize("doc", DOCUMENTS, ids=lambda d: d.aircraft_type)
def test_block_ranges_hold_the_block_bodies(doc) -> None:
    path = MANUALS_DIR / doc.filename
    manual = read_manual(path)

    assert manual.text == read_manual_text(path)
    bodies = _raw_bodies(path.read_text(encoding="utf-8"))
    assert manual.blocks.keys() == bodies.keys()
    for block_id, (start, end) in manual.blocks.items():
        assert manual.text[start:end].strip() == strip_comments(bodies[block_id]).strip()


def test_block_ranges_shift_with_the_stripped_lead(tmp_path: Path) -> None:
    path = tmp_path / "manual.md"
    path.write_text(
        "<!-- note -->\n\n"
        + _MARKER.format("BEGIN", "a")
        + "Alpha <!-- x -->row\n"
        + _MARKER.format("END", "a")
        + "middle\n"
        + _MARKER.format("BEGIN", "b")
        + "Beta\n"
        + _MARKER.format("END", "b"),
        encoding="utf-8",
    )

    manual = read_manual(path)

    assert manual.text == "Alpha row\nmiddle\nBeta"
    assert {k: manual.text[s:e] for k, (s, e) in manual.blocks.items()} == {
        "a": "Alpha row\n",
        "b": "Beta",
    }


def test_a_comment_across_a_marker_raises(tmp_path: Path) -> None:
    path = tmp_path / "manual.md"
    path.write_text(
        "<!-- open\n"
        + _MARKER.format("BEGIN", "a")
        + "close -->\nx\n"
        + _MARKER.format("END", "a"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="a comment spans a block marker"):
        read_manual(path)


_A320 = next(doc for doc in DOCUMENTS if doc.aircraft_type == "A320-200")
_TAKEOFF_ROW = "| EGT (Takeoff, 5 min) | < 650°C | 650-695°C | 695°C |"


def _write_csv(data_dir: Path, rows: list[dict[str, str]]) -> None:
    with (data_dir / LIMITS_FILE).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict.fromkeys(_COLUMNS, "") | row)


def _row(name: str, block: str, text: str, aircraft_type: str = "A320-200") -> dict[str, str]:
    return {"name": name, "aircraftType": aircraft_type, "sourceBlock": block, "sourceText": text}


def test_sources_are_ranges_inside_their_block(tmp_path: Path) -> None:
    _write_csv(
        tmp_path,
        [
            _row("EGT Takeoff - A320-200", "egt-limits", _TAKEOFF_ROW),
            _row("EGT Takeoff Copy - A320-200", "egt-limits", _TAKEOFF_ROW),
        ],
    )

    sources = limit_sources(tmp_path, MANUALS_DIR)

    manual = read_manual(MANUALS_DIR / _A320.filename)
    block_start, block_end = manual.blocks["egt-limits"]
    assert [s.name for s in sources] == ["EGT Takeoff - A320-200", "EGT Takeoff Copy - A320-200"]
    for source in sources:
        assert source.document_id == _A320.document_id
        assert manual.text[source.start : source.end] == _TAKEOFF_ROW
        assert block_start <= source.start < source.end <= block_end


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (_row("X", "egt-limits", _TAKEOFF_ROW, "B747"), "no manual for 'B747'"),
        (_row("X", "no-such-block", _TAKEOFF_ROW), "has no block 'no-such-block'"),
        # The row is in egt-limits, not in vibration-bands.
        (_row("X", "vibration-bands", _TAKEOFF_ROW), "occurs 0 times in block"),
        (_row("X", "egt-limits", "| EGT ("), "occurs 2 times in block"),
    ],
    ids=["unknown-type", "missing-block", "other-block", "repeated"],
)
def test_a_source_not_once_in_its_block_raises(
    tmp_path: Path, row: dict[str, str], message: str
) -> None:
    _write_csv(tmp_path, [row])

    with pytest.raises(ValueError, match=message):
        limit_sources(tmp_path, MANUALS_DIR)


@pytest.mark.skipif(
    not (_DATA_DIR / LIMITS_FILE).exists(), reason=f"no generated {LIMITS_FILE} to read"
)
def test_every_generated_limit_has_a_source() -> None:
    with (_DATA_DIR / LIMITS_FILE).open(encoding="utf-8", newline="") as f:
        names = [row["name"] for row in csv.DictReader(f)]

    assert [s.name for s in limit_sources(_DATA_DIR, MANUALS_DIR)] == names
