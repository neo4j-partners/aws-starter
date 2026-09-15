# Finance data agent

This directory contains a self-contained copy of the Finance Genie synthetic
dataset and two executable `uv` scripts that store its tabular CSV data as
Apache Iceberg tables. One targets an ordinary S3 bucket with AWS Glue as the
catalog; the other uses the Amazon S3 Tables service and its Iceberg REST
catalog.

## Load the data

You can load the dataset in either of these ways:

- [Normal S3 bucket with Glue](#load-into-a-normal-s3-bucket-with-glue): stores
  the tables in an S3 bucket and uses AWS Glue as the catalog.
- [Amazon S3 Tables](#load-into-amazon-s3-tables): uses Amazon's managed S3
  Tables storage and Iceberg REST catalog.

Both loaders convert the CSV files into Iceberg tables: the records are stored
as Parquet files, while Iceberg tracks their schema and table snapshots for
reliable queries.

## Parquet and Iceberg

Parquet and Iceberg operate at different layers. Parquet is the columnar file
format that stores the actual rows. Iceberg is the table format that turns a
set of data files into a versioned, queryable table: it records the schema,
snapshots, and the exact files included in each snapshot.

The normal S3 loader uses Parquet as its Iceberg tables' data-file format.
Each `finance.<table>` table has this S3 layout:

```text
warehouse/finance/<table>/
├── data/*.parquet       # the actual records
└── metadata/*           # Iceberg schemas, manifests, and snapshots
```

Iceberg can manage Parquet, ORC, or Avro data files. A direct Parquet URL 
downloads one raw data file. Querying an Iceberg table through Athena,
Spark, or PyIceberg reads the Glue catalog and Iceberg metadata to 
assemble the files for the selected table snapshot.

## Overview of Data Set

The dataset was generated with hidden fraud rings. The graph should find the
rings from transfer, merchant, and KYC data. Ground truth tables identify
the generated fraud accounts and rings. Use it after graph analysis to check
whether the graph found them.

Fraud is represented as ten account rings. Each ring contains 100 accounts
labelled as fraudulent only in the ground-truth tables; the graph input does
not include those labels. Ring accounts transfer money between each other and
use shared anchor merchants. One ring also shares customer phone numbers and
an address.

- **Accounts:** 25,000 accounts.
- **Fraud labels:** The ground-truth `account_labels` table marks 1,000
  accounts with `is_fraud = true`; this table is not a graph input.
- **Fraud rings:** Ten rings with 100 fraud accounts each.
- **Anchor merchants:** Four merchants are assigned to each ring.
- **Ground truth:** `ground_truth.json` records ring membership, anchor
  merchants, whale accounts, and the KYC story.

### Source tables

- **`accounts`:** Account details.
- **`customers`:** Customer details and KYC identifiers.
- **`merchants`:** Merchant details.
- **`transactions`:** Payments from accounts to merchants.
- **`account_links`:** Transfers between accounts.

### Ground truth tables

Keep these tables out of graph input. They provide the answer key after graph
analysis.

- **`account_labels`:** Account-level fraud labels. Join this table to graph
  results by `account_id` to evaluate each detected account.
- **`fraud_ground_truth_summary`:** Source schema version, seed, and totals.
- **`fraud_rings`:** One row per fraud ring.
- **`fraud_ring_accounts`:** Ring-to-account membership.
- **`fraud_ring_merchants`:** Ring-to-anchor-merchant membership and category.
- **`whale_accounts`:** High-value account identifiers.
- **`fraud_ring_shared_phones`:** Ring-scoped shared phone-to-account links.
- **`fraud_ring_shared_addresses`:** Ring-scoped shared address-to-account links.

`account_labels` provides a fast account-level check. The `fraud_*` tables
explain the rings and their supporting evidence.

### Graph inputs

Load these five Iceberg tables into the graph:

- **Accounts:** `finance.accounts` becomes `:Account`.
- **Customers:** `finance.customers` becomes `:Customer`, `:Phone`, and
  `:Address` with ownership and KYC relationships.
- **Merchants:** `finance.merchants` becomes `:Merchant`.
- **Payments:** `finance.transactions` becomes `:TRANSACTED_WITH`.
- **Transfers:** `finance.account_links` becomes `:TRANSFERRED_TO`.

Use the ground-truth tables only after graph analysis. They are the answer key.

### Fraud encoding, graph loading, and evaluation

- **Fraud signal:** The graph exposes transfer clusters, transfer cycles,
  shared merchants, and shared KYC identifiers.
- **Graph result:** A signal marks an account for review.
- **Iceberg load:** Both loaders create five graph-input tables and eight
  ground-truth tables. `finance.account_labels` is ground truth only.
- **Account-level truth:** Join graph results to `finance.account_labels` by
  `account_id`.
- **Result table:** Store `account_id`, `detector_name`, `score`, and evidence
  from the graph analysis.
- **Evaluation:** Use the join to calculate true positives, false positives,
  false negatives, precision, and recall.
- **Ring-level truth:** Query the normalized `finance.fraud_*` and
  `finance.whale_accounts` tables for ring membership, anchor merchants, whale
  accounts, and the KYC story.

### Sample Graph algorithms

Once the Iceberg graph inputs have been loaded into Neo4j, an analyst can use
Cypher to investigate fraud patterns rather than query the ground-truth answer
tables. Useful investigations inspect:

- Multi-hop `TRANSFERRED_TO` chains, especially circular flows that return to
  their originating account.
- Communities of accounts transferring heavily among themselves while making
  relatively few merchant payments.
- Shared KYC phone numbers or addresses, which can link otherwise separate
  customer records for review.
- Common transfer counterparties that connect accounts across chains or
  communities.
- Similar merchant behaviour through `SIMILAR_TO`, especially when it
  corroborates a transfer or KYC signal.

Each pattern is an investigative lead, not proof of fraud. Compare results
with the ground-truth tables only after the analysis to evaluate the detector.

After the graph is built, [enrich_gds.py](./enrich_gds.py) shows sample Aura
Graph Data Science algorithms that can enrich those investigations:

- **PageRank** writes `risk_score` to prioritize accounts with transfer-network
  influence.
- **Louvain** writes `community_id` to identify transfer communities.
- **Betweenness centrality** writes `betweenness_centrality` to identify
  potential money-flow intermediaries.
- **Node similarity** writes `SIMILAR_TO` relationships using Jaccard similarity
  over account-to-merchant behaviour.

Run it with Neo4j connection settings in the environment:

```bash
uv run enrich_gds.py
```

These metrics guide analyst review. They are not fraud labels or proof of
criminal activity.

[analyze_graph.py](./analyze_graph.py) runs read-only example Cypher analyses
for these five investigation patterns:

```bash
uv run analyze_graph.py
```

```sql
SELECT d.account_id, d.detector_name, d.score, l.is_fraud
FROM detector_results AS d
LEFT JOIN finance.account_labels AS l ON l.account_id = d.account_id;
```

## Load into a normal S3 bucket with Glue

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
- `fraud_ground_truth_summary`
- `fraud_rings`
- `fraud_ring_accounts`
- `fraud_ring_merchants`
- `whale_accounts`
- `fraud_ring_shared_phones`
- `fraud_ring_shared_addresses`

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

## Load into Amazon S3 Tables

Amazon S3 Tables is a separate AWS storage service, not a conventional S3
bucket. It manages the table data and maintenance operations itself. To create
an S3 Tables table bucket, its `finance` namespace, and load the same CSVs
through the S3 Tables Iceberg REST catalog, run:

```bash
uv run scripts/write_finance_s3_tables.py

# Pick a table-bucket name and Region explicitly when needed.
uv run scripts/write_finance_s3_tables.py my-company-finance-tables --region us-west-2
```

The script creates each table bucket with SSE-S3 (`AES256`) encryption. It
creates the thirteen Iceberg tables listed above, or refuses to replace existing
table data unless you add `--replace`.

```bash
uv run scripts/write_finance_s3_tables.py my-company-finance-tables --replace
uv run scripts/write_finance_s3_tables.py --dry-run
```

The S3 Tables script needs permission to create or get the table bucket and
namespace, plus the S3 Tables Iceberg permissions needed to create, inspect,
read, and update table metadata and data. In IAM these are `s3tables` actions,
including `CreateTableBucket`, `GetTableBucket`, `CreateNamespace`,
`CreateTable`, `GetTable`, `GetTableMetadataLocation`, `GetTableData`,
`PutTableData`, and `UpdateTableMetadataLocation`. Unlike the normal S3
loader, it does not configure an S3 bucket policy or public access controls.

## Explore the Glue/S3 dataset with Athena

The Athena script first summarizes the five source tables, then samples one
customer with their profile and ten most recent transactions. It also runs
fraud-ring membership counts, anchor merchants, shared KYC identifiers, and
whale accounts with ring membership. It prints each result in a formatted
console section.

```bash
# Shows the SQL without starting Athena queries.
uv run scripts/query_finance_athena.py --dry-run

# Supply a result prefix because the primary workgroup has no configured output.
uv run scripts/query_finance_athena.py \
  --output-location s3://data-agent-neo4j-euw1/athena-results/
```

Use `--show-sql` to print SQL before execution and `--max-rows` to change the
per-query output limit. The caller needs Athena query permissions, Glue read
permissions, and read/write access to the chosen Athena results prefix.

## Why this implementation

For a normal S3 bucket, PyIceberg with the AWS Glue catalog is the smallest
fully transactional approach: PyIceberg writes Parquet data and Iceberg
metadata while Glue provides the shared catalog. The script constructs typed
PyArrow tables directly from the committed CSVs. Pandas would only add an
intermediate in-memory DataFrame, and Pydantic is useful for API/domain-model
validation rather than bulk analytical-table writes, so neither is a dependency
here.

Both entry-point scripts use `scripts/finance_iceberg.py` for the typed table
definitions, CSV parsing, dry-run validation, and create-or-replace Iceberg
writes. The S3 Tables entry point uses the service's control-plane API only to
ensure its table bucket and namespace exist; PyIceberg creates and writes the
tables through the SigV4-authenticated S3 Tables Iceberg REST endpoint.

The copied CSV and JSON source data lives in [data](./data/). The loaders
normalize `ground_truth.json` into relational tables so its fraud-ring evidence
is available for SQL joins. The Neo4j-specific source scripts are intentionally
omitted because this data agent only loads Iceberg.

## Current guidance

AWS documents PyIceberg plus the Glue Data Catalog for writing Iceberg tables
in S3, including PyArrow `append` operations. PyIceberg supports its native
Glue catalog and direct PyArrow writes. This loader intentionally uses that
path instead of a Spark cluster for this modest, local CSV seed dataset.

For a new large-scale analytics lake, Amazon S3 Tables has a different bucket
model and governance setup from ordinary S3. Use the dedicated S3 Tables
script when that service is required rather than treating it as a drop-in
replacement for a normal bucket.

- [AWS: PyIceberg with Glue Data Catalog](https://docs.aws.amazon.com/prescriptive-guidance/latest/apache-iceberg-on-aws/iceberg-pyiceberg.html)
- [PyIceberg: configuration and AWS credentials](https://py.iceberg.apache.org/configuration/)
- [PyIceberg: PyArrow write API and type mapping](https://py.iceberg.apache.org/api/)
- [AWS: S3 Tables Iceberg REST endpoint](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-open-source.html)

## How it works

1. The script creates or finds the S3 bucket and uses the bucket's Region.
2. It applies the policy-controlled public-read and SSO-writer bucket access.
3. It creates the `finance` Glue database when needed.
4. It parses each source from [data](./data/) into a typed PyArrow table.
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
