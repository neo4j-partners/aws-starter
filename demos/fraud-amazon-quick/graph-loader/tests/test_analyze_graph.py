"""Offline checks for the investigation queries. No test reaches Neo4j."""

from __future__ import annotations

import contextlib
import io
import re
import sys
import unittest
from unittest.mock import Mock, patch

from graph_loader import analyze_graph

# A CALL subquery with no scope clause is deprecated in Neo4j 5 and logs a
# warning. A scoped one reads CALL () { or CALL (a, b) {.
UNSCOPED_CALL = re.compile(r"\bCALL\s*\{", re.IGNORECASE)


class QueryTextTests(unittest.TestCase):
    def test_no_query_uses_an_unscoped_call_subquery(self) -> None:
        for name, (_, query) in analyze_graph.ANALYSES.items():
            with self.subTest(analysis=name):
                self.assertIsNone(UNSCOPED_CALL.search(query))

    def test_shared_kyc_subquery_imports_nothing(self) -> None:
        _, query = analyze_graph.ANALYSES["shared-kyc"]
        self.assertIn("CALL () {", query)

    def test_every_query_is_limited(self) -> None:
        for name, (_, query) in analyze_graph.ANALYSES.items():
            with self.subTest(analysis=name):
                self.assertIn("LIMIT $limit", query)


class RunAnalysisTests(unittest.TestCase):
    def run_analysis(self, rows: list[dict]) -> tuple[Mock, str]:
        records = [Mock(data=Mock(return_value=row)) for row in rows]
        session = Mock()
        session.run.return_value = records
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            analyze_graph.run_analysis(session, "shared-kyc", 5)
        return session, output.getvalue()

    def test_passes_the_limit_and_prints_rows(self) -> None:
        session, output = self.run_analysis([{"identifier_type": "phone"}])
        _, query = analyze_graph.ANALYSES["shared-kyc"]
        session.run.assert_called_once_with(query, limit=5)
        self.assertIn('"identifier_type": "phone"', output)

    def test_empty_result_names_the_enrich_step(self) -> None:
        _, output = self.run_analysis([])
        self.assertIn("fraud-graph-enrich", output)


class MainTests(unittest.TestCase):
    def test_limit_below_one_is_rejected(self) -> None:
        with (
            patch.object(sys, "argv", ["fraud-graph-analyze", "--limit", "0"]),
            self.assertRaises(SystemExit) as caught,
        ):
            analyze_graph.main()
        self.assertIn("--limit", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
