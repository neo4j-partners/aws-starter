# Finance data agent

This directory contains a self-contained copy of the Finance Genie synthetic
dataset and an executable `uv` script that stores its tabular CSV data as
Apache Iceberg tables in Amazon S3. The Iceberg catalog is AWS Glue, which
makes the tables discoverable from Athena, Glue, Spark, and other Iceberg
clients.

This is a standard S3 bucket with an AWS Glue Iceberg catalog. It does **not**
use the separate Amazon S3 Tables service.

## Load the data

Authenticate through your usual AWS profile, environment credentials, or an
IAM role, then run from this directory:

```bash
# Creates and loads s3://data-agent-neo4j-euw1 by default.
uv run scripts/write_finance_iceberg.py

# Bucket names are global. Supply a unique name when the default is taken.
uv run scripts/write_finance_iceberg.py my-company-data-agent-neo4j
```

The script creates a new bucket with public access blocked and SSE-S3 default
encryption. It creates the `finance` Glue database and these Iceberg v2,
Zstandard-compressed Parquet tables:

- `accounts`
- `customers`
- `merchants`
- `transactions`
- `account_links`
- `account_labels`

For an existing bucket, the script detects its Region and uses that Region for
the Glue catalog. For a new bucket, pass `--region` when your usual AWS Region
is not the intended bucket Region.

An existing table is never silently appended to or replaced. Use `--replace`
to replace a previously loaded table with its bundled source, or `--dry-run`
to validate the CSVs and display their Arrow schemas without using AWS.

```bash
uv run scripts/write_finance_iceberg.py my-company-data-agent-neo4j --replace
uv run scripts/write_finance_iceberg.py --dry-run
```

`--force-delete` is deliberately destructive: it deletes every current and
noncurrent object plus every delete marker in the selected bucket, drops the
Glue table entries whose data is in that bucket, then reloads the bundled data.

```bash
uv run scripts/write_finance_iceberg.py --force-delete
```

Required IAM permissions are `s3:CreateBucket`, `s3:ListBucket`,
`s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:PutBucketEncryption`,
and `s3:PutBucketPublicAccessBlock` for a new bucket, plus the Glue Data
Catalog create/get/update actions for the `finance` database and its tables.
Existing-bucket runs need only the applicable S3 object and Glue permissions.

The script enforces the requested bucket-level access model each time it runs:
ACL-based public access remains blocked; a bucket policy permits public
`s3:GetObject` only, with no public listing; and only the configured SSO writer
role can put objects. The role defaults to the current default-profile SSO role
and can be overridden by `--writer-role-arn` or `DATA_AGENT_WRITER_ROLE_ARN`.

## Why this implementation

For a normal S3 bucket, PyIceberg with the AWS Glue catalog is the smallest
fully transactional approach: PyIceberg writes Parquet data and Iceberg
metadata while Glue provides the shared catalog. The script constructs typed
PyArrow tables directly from the committed CSVs. Pandas would only add an
intermediate in-memory DataFrame, and Pydantic is useful for API/domain-model
validation rather than bulk analytical-table writes, so neither is a dependency
here.

The copied CSV source data lives in [data](./data/). `ground_truth.json`
remains a test fixture rather than an analytical table because its nested
structure is designed for fraud-detector evaluation. The Neo4j-specific source
scripts are intentionally omitted because this data agent only loads Iceberg.

## Current guidance

AWS documents PyIceberg plus the Glue Data Catalog for writing Iceberg tables
in S3, including PyArrow `append` operations. PyIceberg supports its native
Glue catalog and direct PyArrow writes. This loader intentionally uses that
path instead of a Spark cluster for this modest, local CSV seed dataset.

For a new large-scale analytics lake, evaluate Amazon S3 Tables plus the Glue
Iceberg REST endpoint. It has a different bucket model and governance setup,
so it is not a drop-in replacement for the requested ordinary S3 bucket.

- [AWS: PyIceberg with Glue Data Catalog](https://docs.aws.amazon.com/prescriptive-guidance/latest/apache-iceberg-on-aws/iceberg-pyiceberg.html)
- [PyIceberg: configuration and AWS credentials](https://py.iceberg.apache.org/configuration/)
- [PyIceberg: PyArrow write API and type mapping](https://py.iceberg.apache.org/api/)

## How it works

1. The script creates or finds the S3 bucket and uses the bucket's Region.
2. It applies the policy-controlled public-read and SSO-writer bucket access.
3. It creates the `finance` Glue database when needed.
4. It parses each CSV from [data](./data/) into a typed PyArrow table.
5. For a table that does not yet exist, PyIceberg creates the initial Iceberg
   metadata file in `s3://<bucket>/warehouse/finance/<table>/metadata/` and
   registers its metadata location in AWS Glue. Glue is the catalog: it stores
   the table definition and current metadata pointer, not the table data.
6. PyIceberg appends the Arrow table by writing Zstandard-compressed Parquet
   data files to S3, then commits Iceberg manifests and a snapshot that
   atomically makes those files the table's current version.
7. A later `--replace` run commits a new snapshot instead of editing Parquet
   files in place. `--force-delete` first drops the Glue tables and removes all
   bucket objects and versions, then rebuilds the tables from the bundled CSVs.
