"""Each chunk's context line names the manual section the chunk starts in."""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path

import pytest
from neo4j_graphrag.components.text_splitters.base import TextSplitter
from neo4j_graphrag.components.text_splitters.fixed_size_splitter import FixedSizeSplitter
from neo4j_graphrag.components.types import TextChunk, TextChunks

from populate_aircraft_db.config import Settings
from populate_aircraft_db.pipeline import (
    ContextPrependingSplitter,
    Heading,
    markdown_headings,
    read_manual_text,
    section_path,
)

MANUALS_DIR = Path(__file__).resolve().parent.parent / "manuals"
CONTEXT = "[DOCUMENT CONTEXT] Aircraft Type: X | Title: Y"

TEXT = """# Title

Intro.

## 3. Engine

### 3.2 Components

#### 3.2.3 Turbine

Turbine text.

#### 3.2.4 Fuel Pump

Pump text.

## 4. Troubleshooting

```
# not a heading
```

Fault text.
"""


def _offset(marker: str) -> int:
    return TEXT.index(marker)


def _split(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    splitter = ContextPrependingSplitter(
        FixedSizeSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap, approximate=True),
        context=CONTEXT,
        document_id="doc",
    )
    return [chunk.text for chunk in asyncio.run(splitter.run(text)).chunks]


def _manual_chunks(filename: str) -> list[str]:
    chunk_size = Settings.model_fields["chunk_size"].default
    chunk_overlap = Settings.model_fields["chunk_overlap"].default
    return _split(read_manual_text(MANUALS_DIR / filename), chunk_size, chunk_overlap)


def test_headings_have_their_level_and_text_and_skip_code_blocks() -> None:
    headings = markdown_headings(TEXT)

    assert [(h.level, h.text) for h in headings] == [
        (1, "Title"),
        (2, "3. Engine"),
        (3, "3.2 Components"),
        (4, "3.2.3 Turbine"),
        (4, "3.2.4 Fuel Pump"),
        (2, "4. Troubleshooting"),
    ]
    assert all(TEXT[h.start :].startswith("#") for h in headings)


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("Intro.", []),
        ("Turbine text.", ["3. Engine", "3.2 Components", "3.2.3 Turbine"]),
        ("Pump text.", ["3. Engine", "3.2 Components", "3.2.4 Fuel Pump"]),
        ("Fault text.", ["4. Troubleshooting"]),
    ],
    ids=["before-any-section", "nested", "sibling-replaces", "new-chapter-pops"],
)
def test_section_path_is_the_headings_in_effect(marker: str, expected: list[str]) -> None:
    assert section_path(markdown_headings(TEXT), _offset(marker)) == expected


def test_a_chunk_starting_at_a_heading_shows_only_its_parents() -> None:
    offset = _offset("#### 3.2.4")

    assert section_path(markdown_headings(TEXT), offset) == ["3. Engine", "3.2 Components"]


def test_a_chunk_starting_inside_a_heading_line_includes_that_heading() -> None:
    offset = _offset("Fuel Pump")

    assert section_path(markdown_headings(TEXT), offset)[-1] == "3.2.4 Fuel Pump"


def test_a_closing_level_pops_deeper_headings() -> None:
    headings = [Heading(0, 2, "A"), Heading(10, 4, "A.1.1"), Heading(20, 3, "A.2")]

    assert section_path(headings, 30) == ["A", "A.2"]


def test_the_context_line_carries_the_section_path() -> None:
    chunks = _split(TEXT, chunk_size=40, chunk_overlap=5)
    turbine = next(chunk for chunk in chunks if "Turbine text." in chunk.split("\n\n", 1)[1])

    first_line, _ = turbine.split("\n\n", 1)
    assert first_line.startswith(f"{CONTEXT} | Section: 3. Engine > 3.2 Components")


class CutAt(TextSplitter):
    """Split the text at fixed offsets, so a test controls each chunk start."""

    def __init__(self, *cuts: int) -> None:
        self.cuts = cuts

    async def run(self, text: str) -> TextChunks:
        bounds = [0, *self.cuts, len(text)]
        return TextChunks(
            chunks=[
                TextChunk(text=text[a:b], index=i)
                for i, (a, b) in enumerate(itertools.pairwise(bounds))
            ]
        )


def test_a_chunk_opening_on_blank_lines_before_a_heading_shows_only_its_parents() -> None:
    cut = _offset("#### 3.2.4") - 2  # the blank line above the heading
    splitter = ContextPrependingSplitter(CutAt(cut), context=CONTEXT, document_id="doc")

    chunks = asyncio.run(splitter.run(TEXT)).chunks

    assert chunks[1].text.startswith(
        f"{CONTEXT} | Section: 3. Engine > 3.2 Components\n\n\n\n#### 3.2.4 Fuel Pump"
    )


def test_the_first_chunk_has_no_section_part() -> None:
    chunks = _split(TEXT, chunk_size=40, chunk_overlap=5)

    assert chunks[0].startswith(f"{CONTEXT}\n\n# Title")


def test_an_empty_context_adds_no_line() -> None:
    splitter = ContextPrependingSplitter(
        FixedSizeSplitter(chunk_size=40, chunk_overlap=5, approximate=True), document_id="doc"
    )
    inner = FixedSizeSplitter(chunk_size=40, chunk_overlap=5, approximate=True)

    chunks = asyncio.run(splitter.run(TEXT)).chunks
    plain = asyncio.run(inner.run(TEXT)).chunks

    assert [c.text for c in chunks] == [c.text for c in plain]


@pytest.mark.parametrize(
    "manual", sorted(MANUALS_DIR.glob("MAINTENANCE_*.md")), ids=lambda p: p.stem
)
def test_the_section_does_not_change_chunk_boundaries(manual: Path) -> None:
    chunk_size = Settings.model_fields["chunk_size"].default
    chunk_overlap = Settings.model_fields["chunk_overlap"].default
    text = read_manual_text(manual)
    inner = FixedSizeSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap, approximate=True)

    plain = asyncio.run(inner.run(text)).chunks
    chunks = _split(text, chunk_size, chunk_overlap)

    assert len(chunks) == len(plain)
    for chunk, original in zip(chunks, plain, strict=True):
        assert chunk.endswith(original.text)


def test_the_a220_gearbox_oil_table_chunk_names_its_section() -> None:
    # The "3.5.1 Gearbox Oil System" heading sits in the chunk before the
    # oil pressure table, so only the context line ties the table to it.
    chunks = _manual_chunks("MAINTENANCE_A220.md")
    [chunk] = [c for c in chunks if "| Ground Idle | 40 | 50-65 | 85 |" in c.split("\n\n", 1)[1]]

    first_line = chunk.split("\n", 1)[0]
    assert first_line.endswith(
        " | Section: 3. Engine System - PW1500G > 3.5 Reduction Gearbox > 3.5.1 Gearbox Oil System"
    )
