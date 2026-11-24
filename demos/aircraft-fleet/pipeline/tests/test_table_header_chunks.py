"""A chunk that starts inside a markdown table begins with the table's header."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from neo4j_graphrag.components.text_splitters.fixed_size_splitter import FixedSizeSplitter
from neo4j_graphrag.components.types import TextChunks

from populate_aircraft_db.config import Settings
from populate_aircraft_db.pipeline import (
    ContextPrependingSplitter,
    markdown_tables,
    read_manual_text,
    with_table_header,
)

MANUALS_DIR = Path(__file__).resolve().parent.parent / "manuals"
MANUALS = sorted(MANUALS_DIR.glob("MAINTENANCE_*.md"))
CONTEXT = "[DOCUMENT CONTEXT] Aircraft Type: X | Title: Y\n\n"

HEADER = "| Parameter | Idle | Takeoff |\n|-----------|------|---------|\n"
ROWS = "| EGT (°C) | 400 | < 950 |\n| N1 (%) | 20 | 97 |\n"
TEXT = f"Intro line.\n\n{HEADER}{ROWS}\nAfter the table.\n"
_SEPARATOR_PREFIX = re.compile(r"[\s|:-]*")


class _Rewriting(FixedSizeSplitter):
    """Returns chunks that are not substrings of the text."""

    async def run(self, text: str) -> TextChunks:  # type: ignore[override]
        result = await super().run(text)
        for chunk in result.chunks:
            chunk.text = chunk.text.upper()
        return result


def _split(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    splitter = ContextPrependingSplitter(
        FixedSizeSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap, approximate=True),
        context=CONTEXT,
        document_id="doc",
    )
    result = asyncio.run(splitter.run(text))
    return [chunk.text for chunk in result.chunks]


def _rows_without_header(chunk: str) -> list[str]:
    """Table lines in ``chunk`` with no header row and separator above them.

    A last line with no newline is a fragment cut by the chunk end, so it is
    not checked. A pipe line just above that fragment counts as a header when
    the fragment could be the start of a separator line.
    """
    lines = chunk.split("\n")
    fragment = lines.pop()  # "" when the chunk ends with a newline
    under_header = False
    orphans = []
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            under_header = False
        elif markdown_tables("\n".join(lines[i : i + 2])):
            under_header = True
        elif not under_header and not (
            i == len(lines) - 1 and _SEPARATOR_PREFIX.fullmatch(fragment)
        ):
            orphans.append(line)
    return orphans


def test_markdown_tables_finds_header_body_and_end() -> None:
    [table] = markdown_tables(TEXT)
    assert TEXT[table.start : table.body_start] == HEADER
    assert TEXT[table.body_start : table.end] == ROWS


def test_a_pipe_line_without_a_separator_is_not_a_table() -> None:
    assert markdown_tables("| not | a table |\nplain text\n") == []


def test_a_chunk_starting_in_a_body_row_gets_the_header_and_the_whole_row() -> None:
    tables = markdown_tables(TEXT)
    start = TEXT.index("400 |")
    assert with_table_header(TEXT, start, len(TEXT), tables) == (
        HEADER + TEXT[TEXT.index("| EGT") :]
    )


def test_a_chunk_starting_at_a_row_start_gets_the_header() -> None:
    tables = markdown_tables(TEXT)
    start = TEXT.index("| N1")
    assert with_table_header(TEXT, start, len(TEXT), tables) == HEADER + TEXT[start:]


def test_a_chunk_starting_in_the_separator_goes_back_to_the_header_row() -> None:
    tables = markdown_tables(TEXT)
    start = TEXT.index("------|---------|")
    assert with_table_header(TEXT, start, len(TEXT), tables) == TEXT[TEXT.index(HEADER) :]


def test_a_chunk_starting_at_the_header_row_is_unchanged() -> None:
    tables = markdown_tables(TEXT)
    start = TEXT.index(HEADER)
    assert with_table_header(TEXT, start, len(TEXT), tables) == TEXT[start:]


def test_a_chunk_starting_outside_a_table_is_unchanged() -> None:
    tables = markdown_tables(TEXT)
    start = TEXT.index("After")
    assert with_table_header(TEXT, start, len(TEXT), tables) == TEXT[start:]


def test_the_splitter_puts_the_header_after_the_context_line() -> None:
    chunks = _split(TEXT, chunk_size=40, chunk_overlap=5)
    in_table = [c for c in chunks if "| EGT" in c or "| N1" in c]
    assert in_table
    for chunk in in_table:
        assert chunk.startswith(CONTEXT)
        assert HEADER in chunk
        assert _rows_without_header(chunk.removeprefix(CONTEXT)) == []


def test_the_splitter_rejects_chunks_that_are_not_substrings() -> None:
    splitter = ContextPrependingSplitter(
        _Rewriting(chunk_size=40, chunk_overlap=5), document_id="d"
    )
    with pytest.raises(ValueError, match="not a substring"):
        asyncio.run(splitter.run(TEXT))


@pytest.mark.parametrize("manual", MANUALS, ids=lambda path: path.stem)
def test_every_table_row_in_a_real_manual_chunk_sits_under_its_header(manual: Path) -> None:
    chunk_size = Settings.model_fields["chunk_size"].default
    chunk_overlap = Settings.model_fields["chunk_overlap"].default
    chunks = _split(read_manual_text(manual), chunk_size, chunk_overlap)
    orphans = {
        index: rows
        for index, chunk in enumerate(chunks)
        if (rows := _rows_without_header(chunk.removeprefix(CONTEXT)))
    }
    assert orphans == {}


@pytest.mark.parametrize(
    "header",
    [
        "| Parameter | Ground Idle | Flight Idle | Cruise (digital twin) |",
        "| System | Sensor Type | Parameter | Unit | Location |",
    ],
    ids=["parameters", "sensor-inventory"],
)
def test_a_split_parameters_or_sensor_table_gets_its_header(header: str) -> None:
    """At least one manual splits each table, and its later chunks keep the header.

    The parameters header also heads the quick-reference engine table.
    """
    chunk_size = Settings.model_fields["chunk_size"].default
    chunk_overlap = Settings.model_fields["chunk_overlap"].default
    repeated = 0
    for manual in MANUALS:
        text = read_manual_text(manual)
        chunks = _split(text, chunk_size, chunk_overlap)
        with_header = sum(header in chunk for chunk in chunks)
        repeated += with_header - text.count(header)
    assert repeated > 0
