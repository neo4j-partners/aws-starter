#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "boto3>=1.43.0",
# ]
# ///
"""Run formatted source-data and fraud-ring queries against the Athena catalog.

Examples:

    uv run scripts/query_finance_athena.py
    uv run scripts/query_finance_athena.py --output-location s3://my-results/athena/
    uv run scripts/query_finance_athena.py --dry-run
"""

from __future__ import annotations

import argparse
import textwrap
import time
from dataclasses import dataclass

import boto3
from botocore.client import BaseClient


DEFAULT_REGION = "eu-west-1"
DEFAULT_DATABASE = "finance"
DEFAULT_CATALOG = "AwsDataCatalog"
DEFAULT_WORKGROUP = "primary"


@dataclass(frozen=True)
class SampleQuery:
    title: str
    sql: str


SAMPLE_QUERIES = (
    SampleQuery(
        "Source-table summaries",
        """
        SELECT 'accounts' AS source_table, 'Account details' AS description, COUNT(*) AS row_count
        FROM accounts
        UNION ALL
        SELECT 'customers', 'Customer profile and KYC details', COUNT(*)
        FROM customers
        UNION ALL
        SELECT 'merchants', 'Merchant details', COUNT(*)
        FROM merchants
        UNION ALL
        SELECT 'transactions', 'Account payments to merchants', COUNT(*)
        FROM transactions
        UNION ALL
        SELECT 'account_links', 'Account-to-account transfers', COUNT(*)
        FROM account_links
        ORDER BY source_table
        """,
    ),
    SampleQuery(
        "Random customer profile and recent transactions",
        """
        WITH sampled_customer AS (
            SELECT
                c.customer_id,
                c.account_id,
                c.customer_name,
                c.phone,
                c.email,
                c.address,
                a.account_type,
                a.region,
                a.balance,
                a.opened_date
            FROM customers AS c
            JOIN accounts AS a ON c.account_id = a.account_id
            ORDER BY rand()
            LIMIT 1
        )
        SELECT
            c.customer_id,
            c.account_id,
            c.customer_name,
            c.phone,
            c.email,
            c.address,
            c.account_type,
            c.region,
            c.balance,
            c.opened_date,
            t.txn_id,
            t.txn_timestamp,
            t.amount,
            m.merchant_name,
            m.category AS merchant_category
        FROM sampled_customer AS c
        LEFT JOIN transactions AS t ON c.account_id = t.account_id
        LEFT JOIN merchants AS m ON t.merchant_id = m.merchant_id
        ORDER BY t.txn_timestamp DESC
        LIMIT 10
        """,
    ),
    SampleQuery(
        "Fraud-ring overview",
        """
        WITH account_counts AS (
            SELECT ring_id, COUNT(*) AS account_count
            FROM fraud_ring_accounts
            GROUP BY ring_id
        ), merchant_counts AS (
            SELECT ring_id, COUNT(*) AS merchant_count
            FROM fraud_ring_merchants
            GROUP BY ring_id
        )
        SELECT r.ring_id, a.account_count, m.merchant_count
        FROM fraud_rings AS r
        JOIN account_counts AS a ON r.ring_id = a.ring_id
        JOIN merchant_counts AS m ON r.ring_id = m.ring_id
        ORDER BY r.ring_id
        """,
    ),
    SampleQuery(
        "Anchor merchants by fraud ring",
        """
        SELECT frm.ring_id, frm.merchant_id, m.merchant_name, frm.category
        FROM fraud_ring_merchants AS frm
        JOIN merchants AS m ON frm.merchant_id = m.merchant_id
        ORDER BY frm.ring_id, frm.merchant_id
        """,
    ),
    SampleQuery(
        "Shared KYC identifiers",
        """
        SELECT 'phone' AS identifier_type, ring_id, phone AS shared_value, account_id
        FROM fraud_ring_shared_phones
        UNION ALL
        SELECT
            'address' AS identifier_type,
            ring_id,
            address AS shared_value,
            account_id
        FROM fraud_ring_shared_addresses
        ORDER BY identifier_type, shared_value, account_id
        """,
    ),
    SampleQuery(
        "Whale accounts with fraud-ring membership",
        """
        SELECT
            w.account_id,
            a.account_name,
            a.balance,
            l.is_fraud,
            r.ring_id
        FROM whale_accounts AS w
        JOIN accounts AS a ON w.account_id = a.account_id
        JOIN account_labels AS l ON w.account_id = l.account_id
        LEFT JOIN fraud_ring_accounts AS r ON w.account_id = r.account_id
        ORDER BY a.balance DESC
        LIMIT 20
        """,
    ),
)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"Athena Region (default: {DEFAULT_REGION}).",
    )
    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help=f"Glue database to query (default: {DEFAULT_DATABASE}).",
    )
    parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG,
        help=f"Athena catalog name (default: {DEFAULT_CATALOG}).",
    )
    parser.add_argument(
        "--workgroup",
        default=DEFAULT_WORKGROUP,
        help=f"Athena workgroup (default: {DEFAULT_WORKGROUP}).",
    )
    parser.add_argument(
        "--output-location",
        help=(
            "S3 prefix for Athena results. Omit only when the selected workgroup "
            "already configures a result location."
        ),
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=20,
        help="Maximum result rows to print for each query (default: 20).",
    )
    parser.add_argument(
        "--show-sql",
        action="store_true",
        help="Print each query before executing it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the sample SQL without calling Athena.",
    )
    return parser.parse_args()


def print_section(title: str) -> None:
    print(f"\n{'=' * 88}\n{title}\n{'=' * 88}")


def format_cell(value: str | None, maximum_width: int = 48) -> str:
    text = "" if value is None else value.replace("\n", " ")
    return text if len(text) <= maximum_width else f"{text[: maximum_width - 1]}…"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("(no rows)")
        return
    formatted_rows = [[format_cell(value) for value in row] for row in rows]
    widths = [
        max(len(header), *(len(row[index]) for row in formatted_rows))
        for index, header in enumerate(headers)
    ]
    separator = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    print(separator)
    header_line = "|".join(
        f" {header:<{width}} " for header, width in zip(headers, widths)
    )
    print(f"|{header_line}|")
    print(separator)
    for row in formatted_rows:
        row_line = "|".join(
            f" {value:<{width}} " for value, width in zip(row, widths)
        )
        print(f"|{row_line}|")
    print(separator)


def wait_for_query(client: BaseClient, query_execution_id: str) -> dict[str, object]:
    """Wait for an Athena query and return its completed execution metadata."""
    while True:
        execution = client.get_query_execution(QueryExecutionId=query_execution_id)[
            "QueryExecution"
        ]
        status = execution["Status"]
        state = status["State"]
        if state == "SUCCEEDED":
            return execution
        if state in {"FAILED", "CANCELLED"}:
            reason = status.get("StateChangeReason", "No failure reason was provided.")
            raise RuntimeError(f"Athena query {state.lower()}: {reason}")
        time.sleep(1)


def fetch_rows(
    client: BaseClient,
    query_execution_id: str,
    max_rows: int,
) -> tuple[list[str], list[list[str]]]:
    """Fetch a bounded result set, skipping Athena's header row."""
    paginator = client.get_paginator("get_query_results")
    headers: list[str] = []
    rows: list[list[str]] = []
    first_page = True
    for page in paginator.paginate(QueryExecutionId=query_execution_id):
        result_set = page["ResultSet"]
        if first_page:
            headers = [
                column.get("Label", column["Name"])
                for column in result_set["ResultSetMetadata"]["ColumnInfo"]
            ]
        page_rows = result_set.get("Rows", [])
        if first_page:
            page_rows = page_rows[1:]
            first_page = False
        for row in page_rows:
            values = [item.get("VarCharValue", "") for item in row.get("Data", [])]
            rows.append(values + [""] * (len(headers) - len(values)))
            if len(rows) >= max_rows:
                return headers, rows
    return headers, rows


def run_query(client: BaseClient, query: SampleQuery, args: argparse.Namespace) -> None:
    print_section(query.title)
    sql = textwrap.dedent(query.sql).strip()
    if args.show_sql:
        print(f"{sql}\n")
    request: dict[str, object] = {
        "QueryString": sql,
        "QueryExecutionContext": {"Catalog": args.catalog, "Database": args.database},
        "WorkGroup": args.workgroup,
    }
    if args.output_location:
        request["ResultConfiguration"] = {"OutputLocation": args.output_location}
    response = client.start_query_execution(**request)
    query_execution_id = response["QueryExecutionId"]
    execution = wait_for_query(client, query_execution_id)
    print(f"Query ID: {query_execution_id}")
    print(f"Results: {execution['ResultConfiguration']['OutputLocation']}")
    headers, rows = fetch_rows(client, query_execution_id, args.max_rows)
    print_table(headers, rows)


def main() -> None:
    args = arguments()
    if args.max_rows < 1:
        raise SystemExit("--max-rows must be at least 1.")
    if args.dry_run:
        for query in SAMPLE_QUERIES:
            print_section(query.title)
            print(query.sql.strip())
        return

    client = boto3.client("athena", region_name=args.region)
    for query in SAMPLE_QUERIES:
        run_query(client, query, args)


if __name__ == "__main__":
    main()
