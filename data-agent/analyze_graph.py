#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "neo4j>=5.28.0",
#   "python-dotenv>=1.0.1",
# ]
# ///
"""Run read-only fraud-investigation queries against the loaded finance graph.

Set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, and optionally NEO4J_DATABASE
before running. Run ``uv run enrich_gds.py`` first when using the
``internal-communities`` or ``similar-behavior`` analyses.

Examples:

    uv run analyze_graph.py
    uv run analyze_graph.py --analysis circular-flows --limit 10
    uv run analyze_graph.py --analysis shared-kyc
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase


Analysis = tuple[str, str]
ANALYSES: dict[str, Analysis] = {
    "circular-flows": (
        "Multi-hop TRANSFERRED_TO chains that return to their origin.",
        """
        MATCH (a:Account)-[first:TRANSFERRED_TO]->(b:Account)
              -[second:TRANSFERRED_TO]->(c:Account)-[third:TRANSFERRED_TO]->(a)
        WHERE a.account_id < b.account_id AND a.account_id < c.account_id
          AND b.account_id <> c.account_id
        RETURN [a.account_id, b.account_id, c.account_id, a.account_id] AS account_path,
               [first.amount, second.amount, third.amount] AS transfer_amounts,
               [first.transfer_timestamp, second.transfer_timestamp,
                third.transfer_timestamp] AS transfer_timestamps
        LIMIT $limit
        """,
    ),
    "internal-communities": (
        "Transfer communities with substantial internal movement.",
        """
        MATCH (a:Account)-[transfer:TRANSFERRED_TO]->(b:Account)
        WHERE a.community_id IS NOT NULL AND a.community_id = b.community_id
        WITH a.community_id AS community_id,
             count(transfer) AS internal_transfer_count,
             sum(transfer.amount) AS internal_transfer_amount,
             collect(DISTINCT a.account_id)[..10] AS sample_account_ids
        RETURN community_id, internal_transfer_count, internal_transfer_amount,
               sample_account_ids
        ORDER BY internal_transfer_amount DESC
        LIMIT $limit
        """,
    ),
    "shared-kyc": (
        "Customers sharing a phone number or address, with their owned accounts.",
        """
        CALL {
            MATCH (first:Customer)-[:HAS_PHONE]->(identifier:Phone)<-[:HAS_PHONE]-(second:Customer)
            WHERE first.customer_id < second.customer_id
            MATCH (first)-[:OWNS]->(first_account:Account)
            MATCH (second)-[:OWNS]->(second_account:Account)
            RETURN 'phone' AS identifier_type, identifier.number AS identifier,
                   first.customer_id AS first_customer_id,
                   second.customer_id AS second_customer_id,
                   first_account.account_id AS first_account_id,
                   second_account.account_id AS second_account_id
            UNION ALL
            MATCH (first:Customer)-[:HAS_ADDRESS]->(identifier:Address)<-[:HAS_ADDRESS]-(second:Customer)
            WHERE first.customer_id < second.customer_id
            MATCH (first)-[:OWNS]->(first_account:Account)
            MATCH (second)-[:OWNS]->(second_account:Account)
            RETURN 'address' AS identifier_type, identifier.address AS identifier,
                   first.customer_id AS first_customer_id,
                   second.customer_id AS second_customer_id,
                   first_account.account_id AS first_account_id,
                   second_account.account_id AS second_account_id
        }
        RETURN identifier_type, identifier, first_customer_id, second_customer_id,
               first_account_id, second_account_id
        LIMIT $limit
        """,
    ),
    "common-counterparties": (
        "Accounts that send transfers to the same counterparty.",
        """
        MATCH (first:Account)-[:TRANSFERRED_TO]->(counterparty:Account)
              <-[:TRANSFERRED_TO]-(second:Account)
        WHERE first.account_id < second.account_id
        WITH counterparty, first, second, count(*) AS shared_transfer_count
        RETURN counterparty.account_id AS counterparty_account_id,
               first.account_id AS first_account_id,
               second.account_id AS second_account_id,
               shared_transfer_count
        ORDER BY shared_transfer_count DESC
        LIMIT $limit
        """,
    ),
    "similar-behavior": (
        "Behaviorally similar accounts, enriched from shared merchant neighbours.",
        """
        MATCH (first:Account)-[similarity:SIMILAR_TO]-(second:Account)
        WHERE first.account_id < second.account_id
        RETURN first.account_id AS first_account_id,
               second.account_id AS second_account_id,
               similarity.similarity_score AS similarity_score,
               first.community_id AS first_community_id,
               second.community_id AS second_community_id
        ORDER BY similarity_score DESC
        LIMIT $limit
        """,
    ),
}


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--analysis",
        choices=["all", *ANALYSES],
        default="all",
        help="Investigation to run (default: all).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum rows per investigation (default: 10).",
    )
    return parser.parse_args()


def connection_settings() -> tuple[str, str, str, str]:
    load_dotenv()
    required = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)}. Set them in .env or the environment.")
    return (
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
        os.environ.get("NEO4J_DATABASE", "neo4j"),
    )


def records_as_dicts(result: Any) -> list[dict[str, Any]]:
    return [record.data() for record in result]


def run_analysis(session: Any, name: str, limit: int) -> None:
    description, query = ANALYSES[name]
    print(f"\n{name}: {description}")
    records = records_as_dicts(session.run(query, limit=limit))
    if records:
        print(json.dumps(records, default=str, indent=2))
    else:
        print("No matching records. Run enrich_gds.py first when this analysis needs GDS data.")


def main() -> None:
    args = arguments()
    if args.limit < 1:
        raise SystemExit("--limit must be greater than zero.")

    uri, username, password, database = connection_settings()
    names = list(ANALYSES) if args.analysis == "all" else [args.analysis]
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            for name in names:
                run_analysis(session, name, args.limit)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
