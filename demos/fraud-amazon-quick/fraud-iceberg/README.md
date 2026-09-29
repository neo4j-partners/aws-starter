# Fraud Iceberg Loaders

These scripts load the synthetic fraud dataset into Apache Iceberg tables.
Athena and Amazon Quick can then query the tables with SQL.

## Overview

- **Normal S3 loader:** The script `write_finance_iceberg.py` writes the tables to an S3 bucket and registers them in AWS Glue. See [Load into a normal S3 bucket with Glue](#load-into-a-normal-s3-bucket-with-glue).
- **S3 Tables loader:** The script `write_finance_s3_tables.py` writes the tables to Amazon S3 Tables through its Iceberg REST catalog. See [Load into Amazon S3 Tables](#load-into-amazon-s3-tables).
- **Athena queries:** The script [`query_finance_athena.py`](./scripts/query_finance_athena.py) runs sample SQL against the Glue tables and prints the results.
- **Dataset:** The data lives in [`demos/fraud-amazon-quick/data/`](../data/). It has ten hidden fraud rings.
- **Ground truth:** Separate answer-key tables mark the fraud accounts and rings. Keep them out of the graph and use them only to check graph results.
- **Graph analysis:** The [`demos/fraud-amazon-quick/graph-loader/`](../graph-loader/) project loads Neo4j and runs the fraud queries. This folder only loads Iceberg.

## Quick start

Run from `demos/fraud-amazon-quick/fraud-iceberg/`. Each script declares its
own dependencies, so `uv run` needs no `uv sync`.

```bash
# Check the CSVs without calling AWS
uv run scripts/write_finance_iceberg.py --dry-run

# Load into a normal S3 bucket with Glue
uv run scripts/write_finance_iceberg.py my-company-data-agent-neo4j

# Or load into Amazon S3 Tables
uv run scripts/write_finance_s3_tables.py

# Query the Glue tables with Athena
uv run scripts/query_finance_athena.py \
  --output-location s3://my-company-data-agent-neo4j/athena-results/
```

## The dataset

The generator planted fraud rings in the data. The graph should find the rings
from transfer, merchant, and KYC data. The ground-truth tables then show
whether it found them.

- **Accounts:** The dataset has 25,000 accounts.
- **Fraud rings:** The dataset has ten rings. Each ring has 100 accounts.
- **Fraud labels:** The ground-truth `account_labels` table marks 1,000 accounts with `is_fraud = true`. The graph input does not include these labels.
- **Ring behavior:** Ring accounts transfer money to each other and use shared anchor merchants.
- **Anchor merchants:** Each ring has four anchor merchants.
- **KYC story:** One ring also shares customer phone numbers and an address.
- **Ground truth file:** The file `ground_truth.json` records ring membership, anchor merchants, whale accounts, and the KYC story.

## Data tables

### Source tables

- **`accounts`:** This table holds account details.
- **`customers`:** This table holds customer details and KYC identifiers.
- **`merchants`:** This table holds merchant details.
- **`transactions`:** This table holds payments from accounts to merchants.
- **`account_links`:** This table holds transfers between accounts.

### Ground-truth tables

These tables are the answer key. Keep them out of the graph input.

- **`account_labels`:** This table holds account-level fraud labels. Join it to graph results by `account_id` to check each detected account.
- **`fraud_ground_truth_summary`:** This table holds the source schema version, seed, and totals.
- **`fraud_rings`:** This table has one row per fraud ring.
- **`fraud_ring_accounts`:** This table maps rings to accounts.
- **`fraud_ring_merchants`:** This table maps rings to anchor merchants and their categories.
- **`whale_accounts`:** This table lists high-value account IDs.
- **`fraud_ring_shared_phones`:** This table links shared phones to accounts within a ring.
- **`fraud_ring_shared_addresses`:** This table links shared addresses to accounts within a ring.

Use `account_labels` for a fast account-level check. Use the `fraud_*` tables
to explain each ring and its evidence.

## Graph inputs

The graph uses these five tables:

- **Accounts:** The `finance.accounts` table becomes `:Account` nodes.
- **Customers:** The `finance.customers` table becomes `:Customer`, `:Phone`, and `:Address` nodes with ownership and KYC relationships.
- **Merchants:** The `finance.merchants` table becomes `:Merchant` nodes.
- **Payments:** The `finance.transactions` table becomes `:TRANSACTED_WITH` relationships.
- **Transfers:** The `finance.account_links` table becomes `:TRANSFERRED_TO` relationships.

## Evaluate graph results

- **Fraud signals:** The graph shows transfer clusters, transfer cycles, shared merchants, and shared KYC identifiers.
- **Graph result:** A signal marks an account for review. It does not prove fraud.
- **Table count:** Both loaders create five graph-input tables and eight ground-truth tables.
- **Result table:** Store `account_id`, `detector_name`, `score`, and evidence from the graph analysis.
- **Account-level check:** Join the result table to `finance.account_labels` by `account_id`.
- **Scoring:** The join gives you true positives, false positives, false negatives, precision, and recall.
- **Ring-level check:** Query the `finance.fraud_*` and `finance.whale_accounts` tables for ring membership, anchor merchants, whale accounts, and the KYC story.

This query joins detector results to the labels:

```sql
SELECT d.account_id, d.detector_name, d.score, l.is_fraud
FROM detector_results AS d
LEFT JOIN finance.account_labels AS l ON l.account_id = d.account_id;
```

## Graph investigations

After the graph inputs are in Neo4j, an analyst uses Cypher to look for fraud
patterns. Useful patterns are:

- **Circular flows:** Money moves along `TRANSFERRED_TO` chains and returns to the starting account.
- **Closed communities:** Accounts transfer heavily among themselves and make few merchant payments.
- **Shared KYC:** Separate customers share a phone number or address.
- **Common counterparties:** Several accounts send transfers to the same account.
- **Similar behavior:** Accounts linked by `SIMILAR_TO` buy from the same merchants. This is most useful when it backs up a transfer or KYC signal.

Each pattern is a lead to review. Compare results with the ground-truth
tables only after the analysis.

The script
[`enrich_gds.py`](../graph-loader/graph_loader/enrich_gds.py) adds Graph Data
Science metrics to the graph:

- **PageRank:** PageRank writes `risk_score` to rank accounts by their influence in the transfer network.
- **Louvain:** Louvain writes `community_id` to group accounts into transfer communities.
- **Betweenness centrality:** This algorithm writes `betweenness_centrality` to find accounts that sit between others in money flows.
- **Node similarity:** This algorithm writes `SIMILAR_TO` relationships. It uses Jaccard similarity over account-to-merchant payments.

These metrics guide review. They are not fraud labels.

The script [`analyze_graph.py`](../graph-loader/graph_loader/analyze_graph.py)
runs read-only Cypher for the five patterns above.

Run both from `demos/fraud-amazon-quick/graph-loader/`, with the Neo4j settings
in its `.env`:

```bash
uv run fraud-graph-enrich
uv run fraud-graph-analyze
```

## Parquet and Iceberg

- **Parquet:** Parquet stores table rows in compressed column files.
- **Iceberg:** Iceberg tracks a table's schema, data files, and versions.
- **Together:** Parquet stores the data, and Iceberg turns the files into a table you can query.

## Load into a normal S3 bucket with Glue

Sign in with your usual AWS profile, environment credentials, or IAM role.
Then run from `demos/fraud-amazon-quick/fraud-iceberg/`:

```bash
# Creates and loads s3://data-agent-neo4j-euw1 by default.
uv run scripts/write_finance_iceberg.py

# Bucket names are global. Pass a unique name if the default is taken.
uv run scripts/write_finance_iceberg.py my-company-data-agent-neo4j
```

The script writes Parquet data files and Iceberg metadata to the bucket. AWS
Glue records each table and the location of its current metadata. Each
`finance.<table>` table uses this layout:

```text
warehouse/finance/<table>/
├── data/*.parquet       # table rows
└── metadata/*           # schemas, manifests, and snapshots
```

The script creates the `finance` Glue database and these thirteen Iceberg v2
tables. The tables use Zstandard-compressed Parquet.

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

### Flags

- **`bucket`:** This optional first argument names the bucket. The default is `data-agent-neo4j-euw1`.
- **`--region`:** This flag sets the Region for a new bucket. Without it, the script uses your AWS profile's Region, or `us-east-1` if none is set. For an existing bucket, the script uses the bucket's own Region.
- **`--namespace`:** This flag sets the Glue database name. The default is `finance`.
- **`--table`:** This flag loads only the named table. Repeat it to load several tables.
- **`--replace`:** This flag replaces the contents of tables that already exist. Without it, the script stops when a table exists. It never appends to or replaces a table silently.
- **`--dry-run`:** This flag checks the CSVs and prints their Arrow schemas. It does not call AWS.
- **`--force-delete`:** This flag is destructive. It deletes every current and old object version and every delete marker in the bucket. It also drops the Glue tables whose data is in that bucket. Then it reloads the bundled data.
- **`--writer-role-arn`:** This flag sets the IAM role that may write objects. You can also set `DATA_AGENT_WRITER_ROLE_ARN`.

```bash
uv run scripts/write_finance_iceberg.py my-company-data-agent-neo4j --replace
uv run scripts/write_finance_iceberg.py --dry-run
uv run scripts/write_finance_iceberg.py --force-delete
```

### Bucket access

A new bucket starts private with SSE-S3 default encryption. The script then
applies this access model on every run:

- **Public read:** A bucket policy lets anyone read objects with `s3:GetObject`. Nobody can list the bucket publicly.
- **ACLs:** Public access through ACLs stays blocked.
- **Writes:** Only the writer role can put objects.
- **Writer role:** The default writer role is a fixed SSO role ARN in the script. Set `--writer-role-arn` or `DATA_AGENT_WRITER_ROLE_ARN` to use your own role.

### Permissions

A new bucket needs these S3 permissions:

- `s3:CreateBucket`
- `s3:ListBucket`
- `s3:GetObject`
- `s3:PutObject`
- `s3:DeleteObject`
- `s3:PutBucketEncryption`
- `s3:PutBucketPublicAccessBlock`

It also needs the Glue Data Catalog create, get, and update actions for the
`finance` database and its tables. A run against an existing bucket needs only
the S3 object and Glue permissions it uses.

## Load into Amazon S3 Tables

Amazon S3 Tables manages Iceberg table data and maintenance. This loader
creates an S3 Tables table bucket and a `finance` namespace. It loads the same
CSVs through the S3 Tables Iceberg REST catalog.

Run from `demos/fraud-amazon-quick/fraud-iceberg/`:

```bash
# Uses the table bucket data-agent-finance-tables by default.
uv run scripts/write_finance_s3_tables.py

# Pick a table bucket name and Region when needed.
uv run scripts/write_finance_s3_tables.py my-company-finance-tables --region us-west-2

uv run scripts/write_finance_s3_tables.py my-company-finance-tables --replace
uv run scripts/write_finance_s3_tables.py --dry-run
```

- **Encryption:** The script creates each table bucket with SSE-S3 (`AES256`) encryption.
- **Tables:** The script creates the same thirteen Iceberg tables as the Glue loader.
- **Existing tables:** The script stops when a table exists. Add `--replace` to overwrite it.
- **Other flags:** The `--region`, `--namespace`, `--table`, and `--dry-run` flags work the same as in the Glue loader.
- **Access controls:** This loader does not set a bucket policy or public access controls.

The script needs `s3tables` IAM actions to create and read the table bucket,
namespace, and tables. These include:

- `CreateTableBucket`
- `GetTableBucket`
- `CreateNamespace`
- `CreateTable`
- `GetTable`
- `GetTableMetadataLocation`
- `GetTableData`
- `PutTableData`
- `UpdateTableMetadataLocation`

## Query the Glue tables with Athena

The Athena script runs these queries and prints each result in its own
section:

- **Source-table summaries:** This query summarizes the five source tables.
- **Customer profile:** This query picks one random customer and shows their profile and ten most recent transactions.
- **Fraud-ring overview:** This query counts the accounts and anchor merchants in each ring.
- **Anchor merchants:** This query lists anchor merchants by ring.
- **Shared KYC identifiers:** This query lists shared phones and addresses.
- **Whale accounts:** This query lists whale accounts with their ring membership.

Run from `demos/fraud-amazon-quick/fraud-iceberg/`:

```bash
# Print the SQL without starting Athena queries.
uv run scripts/query_finance_athena.py --dry-run

# The primary workgroup has no result location, so pass one.
uv run scripts/query_finance_athena.py --region eu-west-1 \
  --output-location s3://data-agent-neo4j-euw1/athena-results/
```

- **`--region`:** This flag sets the Athena Region. Without it, the script uses your AWS profile's Region, then falls back to `us-east-1`. This matches the loaders. Pass `--region eu-west-1` for the default `data-agent-neo4j-euw1` bucket.
- **`--database`:** This flag sets the Glue database. The default is `finance`.
- **`--catalog`:** This flag sets the Athena catalog. The default is `AwsDataCatalog`.
- **`--workgroup`:** This flag sets the Athena workgroup. The default is `primary`.
- **`--output-location`:** This flag sets the S3 prefix for results. You can omit it only when the workgroup already has a result location.
- **`--show-sql`:** This flag prints each query before it runs.
- **`--max-rows`:** This flag sets the number of rows printed per query. The default is 20.

The caller needs Athena query permissions, Glue read permissions, and read and
write access to the results prefix.

## Why this design

- **PyIceberg with Glue:** For a normal S3 bucket, PyIceberg with the Glue catalog is the smallest fully transactional option. PyIceberg writes the Parquet data and Iceberg metadata. Glue provides the shared catalog.
- **PyArrow:** The script builds typed PyArrow tables directly from the CSVs.
- **No Pandas:** Pandas would only add an extra in-memory copy of the data, so the scripts do not use it.
- **No Pydantic:** Pydantic suits API and domain-model checks, not bulk table writes, so the scripts do not use it.
- **Shared module:** Both loaders use `scripts/finance_iceberg.py` for table definitions, CSV parsing, dry-run checks, and create-or-replace writes.
- **S3 Tables flow:** The S3 Tables loader uses the S3 Tables API only to create the table bucket and namespace. PyIceberg then creates and writes the tables through the SigV4-signed S3 Tables Iceberg REST endpoint.
- **Ground truth as tables:** The loaders turn `ground_truth.json` into relational tables, so SQL can join the fraud-ring evidence.
- **No Spark:** The dataset is a small local CSV set, so the loaders use PyIceberg instead of a Spark cluster.

Amazon S3 Tables uses a different bucket model and governance setup from
ordinary S3. Use the S3 Tables script when you need that service. Do not treat
it as a drop-in swap for a normal bucket.

- [AWS: PyIceberg with Glue Data Catalog](https://docs.aws.amazon.com/prescriptive-guidance/latest/apache-iceberg-on-aws/iceberg-pyiceberg.html)
- [PyIceberg: configuration and AWS credentials](https://py.iceberg.apache.org/configuration/)
- [PyIceberg: PyArrow write API and type mapping](https://py.iceberg.apache.org/api/)
- [AWS: S3 Tables Iceberg REST endpoint](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-open-source.html)

## How the Glue loader works

1. The script creates or finds the S3 bucket and uses the bucket's Region.
2. It applies the public-read and writer-role bucket access.
3. It creates the `finance` Glue database if needed.
4. It reads each source file from [`demos/fraud-amazon-quick/data/`](../data/) into a typed PyArrow table.
5. For a new table, PyIceberg writes the first Iceberg metadata file to `s3://<bucket>/warehouse/finance/<table>/metadata/`. It registers that location in AWS Glue. Glue stores the table definition and a pointer to the current metadata. Glue does not store the table data.
6. PyIceberg writes the rows as Zstandard-compressed Parquet files. It then commits Iceberg manifests and a snapshot. The snapshot makes those files the table's current version in one atomic step.
7. A later `--replace` run commits a new snapshot. It does not edit Parquet files in place.
8. A `--force-delete` run first drops the Glue tables and removes all bucket objects and versions. Then it rebuilds the tables from the bundled CSVs.
