"""Console output helpers shared by the sample queries and the agent samples."""

from __future__ import annotations

import textwrap
from collections.abc import Mapping, Sequence
from typing import Any

WIDTH = 70
_MAX_COLUMN_WIDTH = 50


def header(title: str, description: str) -> None:
    """Print a section title between rules, then its description."""
    print(f"\n{'=' * WIDTH}")
    print(f"  {title}")
    print(f"{'=' * WIDTH}")
    print(f"\n  {description}\n")


def show_cypher(query: str, label: str = "Cypher") -> None:
    """Print a query under a label, with its common indentation removed."""
    print(f"  {label}:")
    for ln in textwrap.dedent(query).strip().splitlines():
        print(f"    {ln}")
    print()


def val(v: Any, max_len: int = 0) -> str:
    """Return v as text, a dash for None, cut to max_len with an ellipsis."""
    s = str(v) if v is not None else "—"
    if max_len and len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def table(
    headers: Sequence[str], rows: Sequence[Sequence[Any]], widths: list[int] | None = None
) -> None:
    """Print rows as a fixed-width table.

    Without widths, each column fits its longest value plus one, up to 50
    characters. Longer values are cut with an ellipsis.
    """
    if not rows:
        print("  (no results)\n")
        return
    if widths is None:
        widths = []
        for i, h in enumerate(headers):
            col_max = len(h)
            for row in rows:
                col_max = max(col_max, len(str(row[i] if i < len(row) else "")))
            widths.append(min(col_max + 1, _MAX_COLUMN_WIDTH))
    print("  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=False)))
    print("  " + "  ".join("─" * w for w in widths))
    for row in rows:
        cells = [val(v, w).ljust(w) for v, w in zip(row, widths, strict=False)]
        print("  " + "  ".join(cells))
    print()


def records_table(records: Sequence[Mapping[str, Any]], max_rows: int = 10) -> None:
    """Print the first max_rows records as a table, one column per key."""
    keys = list(records[0]) if records else []
    table(keys, [[r.get(k) for k in keys] for r in records[:max_rows]])
