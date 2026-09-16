"""Load the bundled Finance Genie synthetic fraud dataset into Neo4j.

The source dataset was originally ingested through the Neo4j Spark Connector.
This direct-driver version keeps the same labels, relationship names, and
property types so it can seed the Neo4j database used by the MCP server without
requiring Databricks.
"""

from __future__ import annotations

import argparse
import csv
import os
from collections.abc import Callable, Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase


DATA_DIR = Path(__file__).parent / "data"
BATCH_SIZE = 1_000


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete every node and relationship before loading the dataset.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Rows per Neo4j write transaction (default: {BATCH_SIZE}).",
    )
    return parser.parse_args()


def _connection_settings() -> tuple[str, str, str, str]:
    load_dotenv()
    required = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"Missing {joined}. Set them in .env or the environment.")
    return (
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
        os.environ.get("NEO4J_DATABASE", "neo4j"),
    )


def _rows(filename: str, convert: Callable[[dict[str, str]], dict[str, Any]]) -> Iterator[dict[str, Any]]:
    with (DATA_DIR / filename).open(newline="", encoding="utf-8") as handle:
        yield from (convert(row) for row in csv.DictReader(handle))


def _batches(rows: Iterator[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _account(row: dict[str, str]) -> dict[str, Any]:
    return {
        **row,
        "account_id": int(row["account_id"]),
        "balance": float(row["balance"]),
        "holder_age": int(row["holder_age"]),
        "opened_date": date.fromisoformat(row["opened_date"]),
    }


def _merchant(row: dict[str, str]) -> dict[str, Any]:
    return {**row, "merchant_id": int(row["merchant_id"])}


def _customer(row: dict[str, str]) -> dict[str, Any]:
    return {**row, "customer_id": int(row["customer_id"]), "account_id": int(row["account_id"])}


def _transaction(row: dict[str, str]) -> dict[str, Any]:
    return {
        **row,
        "txn_id": int(row["txn_id"]),
        "account_id": int(row["account_id"]),
        "merchant_id": int(row["merchant_id"]),
        "amount": float(row["amount"]),
        "txn_hour": int(row["txn_hour"]),
        "txn_timestamp": datetime.fromisoformat(row["txn_timestamp"]),
    }


def _transfer(row: dict[str, str]) -> dict[str, Any]:
    return {
        **row,
        "link_id": int(row["link_id"]),
        "src_account_id": int(row["src_account_id"]),
        "dst_account_id": int(row["dst_account_id"]),
        "amount": float(row["amount"]),
        "transfer_timestamp": datetime.fromisoformat(row["transfer_timestamp"]),
    }


def _write_batches(driver: Driver, database: str, cypher: str, rows: Iterator[dict[str, Any]], batch_size: int, label: str) -> None:
    total = 0
    with driver.session(database=database) as session:
        for batch in _batches(rows, batch_size):
            session.execute_write(lambda tx: tx.run(cypher, rows=batch).consume())
            total += len(batch)
            if total % 25_000 == 0 or len(batch) < batch_size:
                print(f"{label}: {total:,} rows")


def _reset(driver: Driver, database: str) -> None:
    print("Deleting the existing Neo4j graph in batches...")
    with driver.session(database=database) as session:
        while True:
            result = session.execute_write(
                lambda tx: tx.run(
                    "MATCH (node) WITH node LIMIT 10000 DETACH DELETE node "
                    "RETURN count(node) AS deleted"
                ).single()
            )
            deleted = result["deleted"]
            if not deleted:
                break
            print(f"deleted {deleted:,} nodes")


def _create_constraints(driver: Driver, database: str) -> None:
    statements = (
        "CREATE CONSTRAINT account_id_unique IF NOT EXISTS FOR (a:Account) REQUIRE a.account_id IS UNIQUE",
        "CREATE CONSTRAINT merchant_id_unique IF NOT EXISTS FOR (m:Merchant) REQUIRE m.merchant_id IS UNIQUE",
        "CREATE CONSTRAINT customer_id_unique IF NOT EXISTS FOR (c:Customer) REQUIRE c.customer_id IS UNIQUE",
        "CREATE CONSTRAINT phone_number_unique IF NOT EXISTS FOR (p:Phone) REQUIRE p.number IS UNIQUE",
        "CREATE CONSTRAINT address_value_unique IF NOT EXISTS FOR (a:Address) REQUIRE a.address IS UNIQUE",
    )
    with driver.session(database=database) as session:
        for statement in statements:
            session.run(statement).consume()


def main() -> None:
    args = _arguments()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be greater than zero.")
    uri, username, password, database = _connection_settings()
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        if args.reset:
            _reset(driver, database)
        _create_constraints(driver, database)

        _write_batches(
            driver,
            database,
            "UNWIND $rows AS row MERGE (a:Account {account_id: row.account_id}) SET a += row",
            _rows("accounts.csv", _account),
            args.batch_size,
            "Accounts",
        )
        _write_batches(
            driver,
            database,
            "UNWIND $rows AS row MERGE (m:Merchant {merchant_id: row.merchant_id}) SET m += row",
            _rows("merchants.csv", _merchant),
            args.batch_size,
            "Merchants",
        )
        _write_batches(
            driver,
            database,
            """
            UNWIND $rows AS row
            MERGE (c:Customer {customer_id: row.customer_id})
            SET c.name = row.customer_name, c.email = row.email
            WITH c, row
            MATCH (a:Account {account_id: row.account_id})
            MERGE (c)-[:OWNS]->(a)
            MERGE (p:Phone {number: row.phone})
            MERGE (c)-[:HAS_PHONE]->(p)
            MERGE (address:Address {address: row.address})
            MERGE (c)-[:HAS_ADDRESS]->(address)
            """,
            _rows("customers.csv", _customer),
            args.batch_size,
            "Customers and KYC identity graph",
        )
        _write_batches(
            driver,
            database,
            """
            UNWIND $rows AS row
            MATCH (a:Account {account_id: row.account_id})
            MATCH (m:Merchant {merchant_id: row.merchant_id})
            MERGE (a)-[t:TRANSACTED_WITH {txn_id: row.txn_id}]->(m)
            SET t.amount = row.amount, t.txn_timestamp = row.txn_timestamp,
                t.txn_hour = row.txn_hour
            """,
            _rows("transactions.csv", _transaction),
            args.batch_size,
            "Transactions",
        )
        _write_batches(
            driver,
            database,
            """
            UNWIND $rows AS row
            MATCH (source:Account {account_id: row.src_account_id})
            MATCH (target:Account {account_id: row.dst_account_id})
            MERGE (source)-[transfer:TRANSFERRED_TO {link_id: row.link_id}]->(target)
            SET transfer.amount = row.amount,
                transfer.transfer_timestamp = row.transfer_timestamp
            """,
            _rows("account_links.csv", _transfer),
            args.batch_size,
            "Peer-to-peer transfers",
        )
    finally:
        driver.close()
    print("Finance Genie graph loaded. Run finance-graph-enrich to add GDS metrics.")


if __name__ == "__main__":
    main()
