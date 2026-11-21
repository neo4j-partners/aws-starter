"""Error reporting shared by the sample queries and the agent samples."""

from __future__ import annotations

from neo4j import Driver, RoutingControl
from neo4j.exceptions import Neo4jError


def report_query_error(driver: Driver, database: str, exc: Neo4jError, index: str) -> None:
    """Print a failed search query's error, and the setup hint if its index is missing.

    If the index lookup fails too, for example for a user without SHOW INDEXES
    rights, only the original error is printed.
    """
    print(f"  [ERROR] {exc.code}: {exc.message}\n")
    try:
        records, _, _ = driver.execute_query(
            "SHOW INDEXES YIELD name WHERE name = $index RETURN count(*) AS count",
            index=index,
            database_=database,
            routing_=RoutingControl.READ,
        )
    except Neo4jError:
        return
    if records[0]["count"] == 0:
        print(f"  (index '{index}' not found; run 'setup' first)\n")
