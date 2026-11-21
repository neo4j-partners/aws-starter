"""Render the generated blocks of the maintenance manuals from specs.

A block is the text between two marker lines:

    <!-- BEGIN GENERATED: vibration-bands -->
    ...rendered markdown...
    <!-- END GENERATED: vibration-bands -->

Rendering replaces each block's body with its renderer's output and keeps
every other line. The loader strips the markers before chunking.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .specs import ENGINE_SPECS, EngineSpec

MANUALS_DIR = Path(__file__).resolve().parent.parent.parent / "manuals"

# Aircraft model -> manual file. Matches the loader's document registry.
MANUAL_FILES: dict[str, str] = {
    "A320-200": "MAINTENANCE_A320.md",
    "A321neo": "MAINTENANCE_A321neo.md",
    "B737-800": "MAINTENANCE_B737.md",
    "E190": "MAINTENANCE_E190.md",
    "A220-300": "MAINTENANCE_A220.md",
}

Stats = Mapping[str, Any]
Renderer = Callable[[str, EngineSpec, Stats], str]

# Block id -> renderer. Each takes (model, engine spec, fleet stats).
RENDERERS: dict[str, Renderer] = {}

# Blocks every manual must have, once each.
REQUIRED_BLOCKS: tuple[str, ...] = ()

_MARKER = re.compile(r"^<!-- (BEGIN|END) GENERATED: ([a-z0-9-]+) -->$")
# A line that looks like a marker but does not match _MARKER exactly.
_MARKER_LIKE = re.compile(r"^\s*<!--\s*(BEGIN|END)\s+GENERATED", re.IGNORECASE)


class ManualBlockError(ValueError):
    """A manual's block markers are malformed, unknown, or missing."""


def load_stats() -> Stats:
    """The fleet statistics the stats blocks render from."""
    return {}


def render_text(
    text: str,
    model: str,
    stats: Stats,
    *,
    renderers: Mapping[str, Renderer] | None = None,
    required: tuple[str, ...] | None = None,
) -> str:
    """Return text with every block body rendered for model."""
    renderers = RENDERERS if renderers is None else renderers
    required = REQUIRED_BLOCKS if required is None else required
    engine = ENGINE_SPECS[model]
    out: list[str] = []
    seen: set[str] = set()
    open_id: str | None = None
    open_line = 0
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        stripped = line.rstrip("\n")
        if (match := _MARKER.match(stripped)) is None:
            if _MARKER_LIKE.match(stripped):
                raise ManualBlockError(f"line {number}: malformed marker {stripped!r}")
            if open_id is None:
                out.append(line)
            continue
        kind, block_id = match.groups()
        if kind == "BEGIN":
            if open_id is not None:
                raise ManualBlockError(
                    f"line {number}: BEGIN marker for {block_id!r} inside block {open_id!r}"
                )
            if block_id not in renderers:
                raise ManualBlockError(f"line {number}: unknown block id {block_id!r}")
            if block_id in seen:
                raise ManualBlockError(f"line {number}: block {block_id!r} appears twice")
            seen.add(block_id)
            open_id, open_line = block_id, number
            out.append(line)
            if body := renderers[block_id](model, engine, stats).rstrip("\n"):
                out.append(body + "\n")
        elif open_id is None:
            raise ManualBlockError(f"line {number}: END marker for {block_id!r} without a BEGIN")
        elif block_id != open_id:
            raise ManualBlockError(
                f"line {number}: END marker for {block_id!r} inside block {open_id!r}"
            )
        else:
            open_id = None
            out.append(line if line.endswith("\n") else line + "\n")
    if open_id is not None:
        raise ManualBlockError(f"line {open_line}: block {open_id!r} has no END marker")
    for block_id in required:
        if block_id not in seen:
            raise ManualBlockError(f"missing required block {block_id!r}")
    return "".join(out)
