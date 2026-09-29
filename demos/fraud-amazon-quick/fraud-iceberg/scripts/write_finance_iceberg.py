#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "boto3>=1.43.0",
#   "pyarrow>=18.0.0",
#   "pyiceberg[glue,pyarrow]>=0.12.0",
# ]
# ///
"""Create an S3 bucket and load the bundled finance CSVs as Iceberg tables.

Run with an AWS profile or role that can create the S3 bucket, manage its
objects, and create Glue databases and tables:

    uv run scripts/write_finance_iceberg.py
    uv run scripts/write_finance_iceberg.py my-unique-bucket-name

The bucket argument is optional and defaults to ``data-agent-neo4j-euw1``.
"""

from __future__ import annotations

import argparse
import json
import os

import boto3
from botocore.exceptions import ClientError
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError, NoSuchNamespaceError

from finance_iceberg import (
    DATA_DIR,
    DEFAULT_NAMESPACE,
    TABLES,
    aws_region,
    selected_tables,
    validate_sources,
    write_source_table,
)


DEFAULT_BUCKET = "data-agent-neo4j-euw1"
DEFAULT_WRITER_ROLE_ARN = (
    "arn:aws:iam::159878781974:role/aws-reserved/sso.amazonaws.com/us-west-2/"
    "AWSReservedSSO_AdministratorAccess_3e15a1219bf2da5b"
)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "bucket",
        nargs="?",
        default=DEFAULT_BUCKET,
        help=f"S3 bucket to create or use (default: {DEFAULT_BUCKET}).",
    )
    parser.add_argument(
        "--region",
        help="AWS Region. Defaults to AWS_REGION, AWS_DEFAULT_REGION, or us-east-1.",
    )
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Glue database / Iceberg namespace (default: {DEFAULT_NAMESPACE}).",
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
        "--force-delete",
        action="store_true",
        help=(
            "Destructively delete every current object, object version, and delete "
            "marker from the target bucket before loading the bundled data."
        ),
    )
    parser.add_argument(
        "--writer-role-arn",
        default=os.environ.get("DATA_AGENT_WRITER_ROLE_ARN", DEFAULT_WRITER_ROLE_ARN),
        help=(
            "IAM role allowed to write objects by the bucket policy. Defaults to "
            "the default-profile SSO role; override with DATA_AGENT_WRITER_ROLE_ARN "
            "or this option."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report the source tables without calling AWS.",
    )
    return parser.parse_args()


def ensure_bucket(bucket: str, region: str) -> str:
    """Create a bucket when needed and return the bucket's AWS Region."""
    s3 = boto3.client("s3", region_name=region)
    try:
        response = s3.head_bucket(Bucket=bucket)
        headers = response.get("ResponseMetadata", {}).get("HTTPHeaders", {})
        bucket_region = headers.get("x-amz-bucket-region", region)
        print(f"Using existing bucket: s3://{bucket} ({bucket_region})")
        return bucket_region
    except ClientError as error:
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 403:
            raise SystemExit(
                f"Bucket {bucket!r} already exists but is not accessible. "
                "S3 bucket names are globally unique; choose another name."
            ) from error
        if status != 404:
            raise

    create_args: dict[str, object] = {"Bucket": bucket}
    if region != "us-east-1":
        create_args["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3.create_bucket(**create_args)
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                }
            ]
        },
    )
    print(f"Created private, encrypted bucket: s3://{bucket}")
    return region


def configure_bucket_access(bucket: str, region: str, writer_role_arn: str) -> None:
    """Apply the policy-controlled public-read, SSO-writer bucket configuration."""
    s3 = boto3.client("s3", region_name=region)
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": False,
            "RestrictPublicBuckets": False,
        },
    )
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicReadObjectsOnly",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/*",
            },
            {
                "Sid": "DefaultProfileWriteObjects",
                "Effect": "Allow",
                "Principal": {"AWS": writer_role_arn},
                "Action": ["s3:PutObject", "s3:AbortMultipartUpload"],
                "Resource": f"arn:aws:s3:::{bucket}/*",
            },
            {
                "Sid": "DenyWritesExceptDefaultProfile",
                "Effect": "Deny",
                "Principal": "*",
                "Action": ["s3:PutObject", "s3:AbortMultipartUpload"],
                "Resource": f"arn:aws:s3:::{bucket}/*",
                "Condition": {"ArnNotEquals": {"aws:PrincipalArn": writer_role_arn}},
            },
        ],
    }
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
    print("Applied policy-controlled public-read and SSO-writer bucket access.")


def clear_bucket(s3, bucket: str) -> None:
    """Delete all current and noncurrent objects, including delete markers."""
    deleted = 0
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket):
        objects = [
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for item in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]
        ]
        for start in range(0, len(objects), 1_000):
            batch = objects[start : start + 1_000]
            s3.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
            deleted += len(batch)
    print(f"Deleted {deleted:,} object versions and delete markers from s3://{bucket}")


def drop_bucket_tables(catalog: Catalog, namespace: str, bucket: str) -> None:
    """Remove catalog entries whose metadata would be invalid after a bucket reset."""
    try:
        identifiers = catalog.list_tables(namespace)
    except NoSuchNamespaceError:
        return
    location_prefix = f"s3://{bucket}/"
    for identifier in identifiers:
        table = catalog.load_table(identifier)
        if table.location().startswith(location_prefix):
            catalog.drop_table(identifier)
            print(f"Dropped Glue table: {'.'.join(identifier)}")


def ensure_namespace(catalog: Catalog, namespace: str, bucket: str) -> None:
    try:
        catalog.create_namespace(
            namespace,
            properties={"location": f"s3://{bucket}/warehouse/{namespace}"},
        )
        print(f"Created Glue database: {namespace}")
    except NamespaceAlreadyExistsError:
        pass


def main() -> None:
    args = arguments()

    if args.dry_run:
        validate_sources(args.tables)
        return

    if not DATA_DIR.is_dir():
        raise SystemExit(f"Bundled data directory is missing: {DATA_DIR}")

    requested_region = aws_region(args.region)
    region = ensure_bucket(args.bucket, requested_region)
    configure_bucket_access(args.bucket, region, args.writer_role_arn)
    # Glue is the shared Iceberg catalog. It is not Amazon S3 Tables.
    catalog = load_catalog("glue", type="glue", **{"client.region": region})
    if args.force_delete:
        drop_bucket_tables(catalog, args.namespace, args.bucket)
        clear_bucket(boto3.client("s3", region_name=region), args.bucket)
    ensure_namespace(catalog, args.namespace, args.bucket)
    for name, source in selected_tables(args.tables):
        write_source_table(
            catalog,
            args.namespace,
            name,
            source,
            args.replace,
            location=f"s3://{args.bucket}/warehouse/{args.namespace}/{name}",
        )


if __name__ == "__main__":
    main()
