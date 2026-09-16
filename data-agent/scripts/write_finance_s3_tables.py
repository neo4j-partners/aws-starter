#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "boto3>=1.43.0",
#   "pyarrow>=18.0.0",
#   "pyiceberg[pyarrow]>=0.12.0",
# ]
# ///
"""Create Amazon S3 Tables and load the bundled finance CSVs with Iceberg.

Run with AWS credentials that can manage S3 Tables and write table data:

    uv run scripts/write_finance_s3_tables.py
    uv run scripts/write_finance_s3_tables.py my-finance-table-bucket
"""

from __future__ import annotations

import argparse

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from pyiceberg.catalog import Catalog, load_catalog

from finance_iceberg import (
    DEFAULT_NAMESPACE,
    TABLES,
    aws_region,
    selected_tables,
    validate_sources,
    write_source_table,
)


DEFAULT_TABLE_BUCKET = "data-agent-finance-tables"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "table_bucket",
        nargs="?",
        default=DEFAULT_TABLE_BUCKET,
        help=(
            "S3 Tables table bucket to create or use "
            f"(default: {DEFAULT_TABLE_BUCKET})."
        ),
    )
    parser.add_argument(
        "--region",
        help="AWS Region. Defaults to AWS_REGION, AWS_DEFAULT_REGION, or us-east-1.",
    )
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"S3 Tables namespace (default: {DEFAULT_NAMESPACE}).",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace the current contents of tables that already exist.",
    )
    parser.add_argument(
        "--table",
        dest="tables",
        action="append",
        choices=TABLES,
        help="Load only this table. Specify multiple times to load several tables.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report the source tables without calling AWS.",
    )
    return parser.parse_args()


def table_bucket_arn(session: boto3.Session, region: str, name: str) -> str:
    """Build this caller's table-bucket ARN from its account and Region."""
    identity = session.client("sts", region_name=region).get_caller_identity()
    account_id = identity["Account"]
    partition = session.get_partition_for_region(region)
    return f"arn:{partition}:s3tables:{region}:{account_id}:bucket/{name}"


def ensure_table_bucket(client: BaseClient, arn: str, name: str) -> str:
    """Create an AES256-encrypted S3 Tables bucket unless it already exists."""
    try:
        client.get_table_bucket(tableBucketARN=arn)
        print(f"Using existing S3 Tables bucket: {arn}")
        return arn
    except ClientError as error:
        if error.response["Error"]["Code"] != "NotFoundException":
            raise

    response = client.create_table_bucket(
        name=name,
        encryptionConfiguration={"sseAlgorithm": "AES256"},
    )
    created_arn = response["arn"]
    print(f"Created AES256-encrypted S3 Tables bucket: {created_arn}")
    return created_arn


def ensure_namespace(
    client: BaseClient, table_bucket_arn: str, namespace: str
) -> None:
    """Create a single-level S3 Tables namespace unless it already exists."""
    try:
        client.create_namespace(tableBucketARN=table_bucket_arn, namespace=[namespace])
        print(f"Created S3 Tables namespace: {namespace}")
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConflictException":
            raise


def s3_tables_catalog(table_bucket_arn: str, region: str) -> Catalog:
    """Connect PyIceberg to the S3 Tables Iceberg REST catalog."""
    return load_catalog(
        "s3tables",
        type="rest",
        warehouse=table_bucket_arn,
        uri=f"https://s3tables.{region}.amazonaws.com/iceberg",
        **{
            "rest.sigv4-enabled": "true",
            "rest.signing-name": "s3tables",
            "rest.signing-region": region,
        },
    )


def main() -> None:
    args = arguments()
    validate_sources(args.tables)
    if args.dry_run:
        return

    region = aws_region(args.region)
    session = boto3.Session(region_name=region)
    client = session.client("s3tables", region_name=region)
    bucket_arn = ensure_table_bucket(
        client,
        table_bucket_arn(session, region, args.table_bucket),
        args.table_bucket,
    )
    ensure_namespace(client, bucket_arn, args.namespace)
    catalog = s3_tables_catalog(bucket_arn, region)
    for name, source in selected_tables(args.tables):
        write_source_table(catalog, args.namespace, name, source, args.replace)


if __name__ == "__main__":
    main()
