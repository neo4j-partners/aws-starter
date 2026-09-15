"""Shared source loading and Iceberg writing helpers for the finance dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import boto3
import pyarrow as pa
import pyarrow.csv as csv
from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import NoSuchTableError


DEFAULT_NAMESPACE = "finance"
DATA_DIR = Path(__file__).parents[1] / "data"
TABLE_PROPERTIES = {
    "format-version": "2",
    "write.parquet.compression-codec": "zstd",
}
JsonRows = Callable[[dict[str, Any]], list[dict[str, Any]]]


@dataclass(frozen=True)
class SourceTable:
    """A bundled tabular source and the schema used to read it."""

    source_file: str
    arrow_schema: pa.Schema
    json_rows: JsonRows | None = None


def ground_truth_summary_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": source["schema_version"],
            "seed": source["seed"],
            **source["summary"],
        }
    ]


def fraud_ring_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"ring_id": ring["ring_id"]} for ring in source["rings"]]


def fraud_ring_account_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"ring_id": ring["ring_id"], "account_id": account_id}
        for ring in source["rings"]
        for account_id in ring["account_ids"]
    ]


def fraud_ring_merchant_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"ring_id": ring["ring_id"], **merchant}
        for ring in source["rings"]
        for merchant in ring["anchor_merchants"]
    ]


def whale_account_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"account_id": account_id} for account_id in source["whale_account_ids"]]


def shared_phone_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    kyc_ring = source["kyc_story_ring"]
    return [
        {"ring_id": kyc_ring["ring_id"], "phone": phone, "account_id": account_id}
        for phone, account_ids in kyc_ring["shared_phones"].items()
        for account_id in account_ids
    ]


def shared_address_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    kyc_ring = source["kyc_story_ring"]
    return [
        {"ring_id": kyc_ring["ring_id"], "address": address, "account_id": account_id}
        for address, account_ids in kyc_ring["shared_address"].items()
        for account_id in account_ids
    ]


TABLES: dict[str, SourceTable] = {
    "accounts": SourceTable(
        "accounts.csv",
        pa.schema(
            [
                pa.field("account_id", pa.int64()),
                pa.field("account_hash", pa.string()),
                pa.field("account_name", pa.string()),
                pa.field("account_type", pa.string()),
                pa.field("region", pa.string()),
                pa.field("balance", pa.float64()),
                pa.field("opened_date", pa.date32()),
                pa.field("holder_age", pa.int32()),
            ]
        ),
    ),
    "customers": SourceTable(
        "customers.csv",
        pa.schema(
            [
                pa.field("customer_id", pa.int64()),
                pa.field("account_id", pa.int64()),
                pa.field("customer_name", pa.string()),
                pa.field("phone", pa.string()),
                pa.field("email", pa.string()),
                pa.field("address", pa.string()),
            ]
        ),
    ),
    "merchants": SourceTable(
        "merchants.csv",
        pa.schema(
            [
                pa.field("merchant_id", pa.int64()),
                pa.field("merchant_name", pa.string()),
                pa.field("category", pa.string()),
                pa.field("region", pa.string()),
            ]
        ),
    ),
    "transactions": SourceTable(
        "transactions.csv",
        pa.schema(
            [
                pa.field("txn_id", pa.int64()),
                pa.field("account_id", pa.int64()),
                pa.field("merchant_id", pa.int64()),
                pa.field("amount", pa.float64()),
                pa.field("txn_timestamp", pa.timestamp("us")),
                pa.field("txn_hour", pa.int32()),
            ]
        ),
    ),
    "account_links": SourceTable(
        "account_links.csv",
        pa.schema(
            [
                pa.field("link_id", pa.int64()),
                pa.field("src_account_id", pa.int64()),
                pa.field("dst_account_id", pa.int64()),
                pa.field("amount", pa.float64()),
                pa.field("transfer_timestamp", pa.timestamp("us")),
            ]
        ),
    ),
    "account_labels": SourceTable(
        "account_labels.csv",
        pa.schema(
            [
                pa.field("account_id", pa.int64()),
                pa.field("is_fraud", pa.bool_()),
            ]
        ),
    ),
    "fraud_ground_truth_summary": SourceTable(
        "ground_truth.json",
        pa.schema(
            [
                pa.field("schema_version", pa.int32()),
                pa.field("seed", pa.int64()),
                pa.field("total_rings", pa.int32()),
                pa.field("total_fraud_accounts", pa.int32()),
                pa.field("total_whale_accounts", pa.int32()),
                pa.field("anchor_merchants_per_ring", pa.int32()),
            ]
        ),
        ground_truth_summary_rows,
    ),
    "fraud_rings": SourceTable(
        "ground_truth.json",
        pa.schema([pa.field("ring_id", pa.int64())]),
        fraud_ring_rows,
    ),
    "fraud_ring_accounts": SourceTable(
        "ground_truth.json",
        pa.schema(
            [pa.field("ring_id", pa.int64()), pa.field("account_id", pa.int64())]
        ),
        fraud_ring_account_rows,
    ),
    "fraud_ring_merchants": SourceTable(
        "ground_truth.json",
        pa.schema(
            [
                pa.field("ring_id", pa.int64()),
                pa.field("merchant_id", pa.int64()),
                pa.field("category", pa.string()),
            ]
        ),
        fraud_ring_merchant_rows,
    ),
    "whale_accounts": SourceTable(
        "ground_truth.json",
        pa.schema([pa.field("account_id", pa.int64())]),
        whale_account_rows,
    ),
    "fraud_ring_shared_phones": SourceTable(
        "ground_truth.json",
        pa.schema(
            [
                pa.field("ring_id", pa.int64()),
                pa.field("phone", pa.string()),
                pa.field("account_id", pa.int64()),
            ]
        ),
        shared_phone_rows,
    ),
    "fraud_ring_shared_addresses": SourceTable(
        "ground_truth.json",
        pa.schema(
            [
                pa.field("ring_id", pa.int64()),
                pa.field("address", pa.string()),
                pa.field("account_id", pa.int64()),
            ]
        ),
        shared_address_rows,
    ),
}


def aws_region(requested_region: str | None) -> str:
    """Return an explicit Region, falling back to the active AWS profile."""
    return requested_region or boto3.Session().region_name or "us-east-1"


def read_source(source: SourceTable) -> pa.Table:
    """Read one bundled source into a strictly typed Arrow table."""
    source_path = DATA_DIR / source.source_file
    if source.json_rows is not None:
        with source_path.open(encoding="utf-8") as source_file:
            return pa.Table.from_pylist(
                source.json_rows(json.load(source_file)), schema=source.arrow_schema
            )
    return csv.read_csv(
        source_path,
        convert_options=csv.ConvertOptions(
            column_types=source.arrow_schema,
            timestamp_parsers=["%Y-%m-%d %H:%M:%S"],
        ),
    )


def selected_tables(
    table_names: list[str] | None = None,
) -> list[tuple[str, SourceTable]]:
    """Return all tables, or an explicitly requested subset, in source order."""
    if table_names is None:
        return list(TABLES.items())
    return [(name, TABLES[name]) for name in table_names]


def validate_sources(table_names: list[str] | None = None) -> None:
    """Ensure every bundled CSV can be parsed before any AWS call is made."""
    if not DATA_DIR.is_dir():
        raise SystemExit(f"Bundled data directory is missing: {DATA_DIR}")
    for name, source in selected_tables(table_names):
        data = read_source(source)
        print(f"{name}: {data.num_rows:,} rows; {data.schema}")


def write_source_table(
    catalog: Catalog,
    namespace: str,
    name: str,
    source: SourceTable,
    replace: bool,
    location: str | None = None,
) -> None:
    """Create or replace one Iceberg table and load its bundled CSV rows."""
    identifier = f"{namespace}.{name}"
    data = read_source(source)
    try:
        table = catalog.load_table(identifier)
    except NoSuchTableError:
        create_args: dict[str, object] = {
            "identifier": identifier,
            "schema": source.arrow_schema,
            "properties": TABLE_PROPERTIES,
        }
        if location is not None:
            create_args["location"] = location
        table = catalog.create_table(**create_args)
        table.append(data)
        print(f"Created and loaded {identifier}: {data.num_rows:,} rows")
        return

    if not replace:
        raise SystemExit(
            f"{identifier} already exists. Re-run with --replace to overwrite "
            "its contents."
        )
    table.overwrite(data)
    print(f"Replaced {identifier}: {data.num_rows:,} rows")
