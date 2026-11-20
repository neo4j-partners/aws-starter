"""Each relationship CSV lists its columns in the direction the loader creates."""

from __future__ import annotations

import re

import pytest

from generator.writers import CSV_COLUMNS
from populate_aircraft_db.loader import _REL_DEFINITIONS

# (var:Label {property: row[':START_ID(Space)']})
_BINDING = re.compile(r"\((\w+):\w+ \{\w+: row\['(:(?:START|END)_ID\(\w+\))'\]\}\)")
_MERGE = re.compile(r"MERGE \((\w+)\)-\[:\w+\]->\((\w+)\)")


@pytest.mark.parametrize(("rel_type", "csv_name", "query"), _REL_DEFINITIONS)
def test_csv_start_is_relationship_start(rel_type: str, csv_name: str, query: str) -> None:
    columns = dict(_BINDING.findall(query))
    merge = _MERGE.search(query)
    assert merge, f"{rel_type}: no MERGE (a)-[:TYPE]->(b) found"
    start, end = merge.groups()
    assert columns[start].startswith(":START_ID"), f"{rel_type} starts from {columns[start]}"
    assert columns[end].startswith(":END_ID"), f"{rel_type} ends at {columns[end]}"
    assert CSV_COLUMNS[csv_name] == [columns[start], columns[end]]
