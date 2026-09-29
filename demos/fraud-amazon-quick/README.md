# Fraud Investigation with Amazon Quick

This demo finds synthetic fraud rings with AWS analytics and Neo4j. One
dataset feeds both Athena and a Neo4j graph, and Amazon Quick shows the
results.

## Overview

- **Dataset:** The folder [`demos/fraud-amazon-quick/data/`](./data/) holds the only copy of the synthetic fraud CSVs and `ground_truth.json`.
- **Graph loader:** The folder [`demos/fraud-amazon-quick/graph-loader/`](./graph-loader/) loads the data into Neo4j with a direct driver. It also adds GDS fraud signals.
- **Fraud memory agent:** The folder [`demos/fraud-amazon-quick/fraud-memory-agent/`](./fraud-memory-agent/) holds a Strands agent. The agent queries the graph through the MCP Gateway and records memory in NAMS.
- **Iceberg loaders:** The folder [`demos/fraud-amazon-quick/fraud-iceberg/`](./fraud-iceberg/) writes the data to Iceberg tables in S3 or S3 Tables. Athena queries those tables.
- **Amazon Quick:** Amazon Quick shows the Athena tables and the agent. You set it up in the AWS console.

## Quick start

Each command group starts from the repo root.

```bash
# 1. Load the graph and add GDS signals
cd demos/fraud-amazon-quick/graph-loader
cp .env.sample .env              # set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
uv sync
uv run fraud-graph-load
uv run fraud-graph-enrich

# 2. Deploy the MCP server for the same database
cd neo4j-mcp-server
cp .env.sample .env.finance      # set the same NEO4J_* values
./deploy.py --env finance
./deploy.py --env finance credentials
../scripts/sync-credentials.sh

# 3. Run the fraud memory agent
cd demos/fraud-amazon-quick/fraud-memory-agent
cp .env.sample .env              # set MEMORY_API_KEY=nams_...
uv sync
uv run fraud-server              # Terminal 1
uv run fraud-cli --user-id analyst-1 "Find circular transfer chains"   # Terminal 2

# 4. Write the Iceberg tables
cd demos/fraud-amazon-quick/fraud-iceberg
uv run scripts/write_finance_s3_tables.py
```

## Prerequisites

- **Neo4j database:** You need a Neo4j database set aside for this demo. The enrichment step also needs Graph Data Science or Aura Graph Analytics.
- **AWS credentials:** Your AWS credentials need access to Bedrock models.
- **NAMS API key:** You can create a key at [NAMS](https://memory.neo4jlabs.com/).
- **Tools:** You need the [`uv`](https://docs.astral.sh/uv/) package manager and Python 3.11 or later.

## Step 1: Load the graph

Run from `demos/fraud-amazon-quick/graph-loader/`:

```bash
cp .env.sample .env       # set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
uv sync
uv run fraud-graph-load
```

`uv run fraud-graph-load --reset` deletes every node and relationship in the
database before it loads. Use it only on the demo database.

## Step 2: Add GDS fraud signals

Run from `demos/fraud-amazon-quick/graph-loader/`:

```bash
uv run fraud-graph-enrich
uv run fraud-graph-analyze   # optional read-only check of the investigation queries
```

Enrichment adds risk scores, communities, betweenness, and account
similarity. The agent can query the graph without it. Questions about those
signals need it. See
[`demos/fraud-amazon-quick/graph-loader/README.md`](./graph-loader/README.md)
for GDS session sizing.

## Step 3: Deploy the MCP server for the fraud graph

The agent reaches Neo4j only through the Neo4j MCP server. Deploy the server
against the same database you loaded in Step 1.

Run from [`neo4j-mcp-server/`](../../neo4j-mcp-server/):

```bash
cp .env.sample .env.finance  # set the same NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
./deploy.py --env finance
./deploy.py --env finance credentials
../scripts/sync-credentials.sh
```

`sync-credentials.sh` copies `.mcp-credentials.finance.json` to
`demos/fraud-amazon-quick/fraud-memory-agent/.mcp-credentials.json`.

## Step 4: Run the fraud memory agent

Run from `demos/fraud-amazon-quick/fraud-memory-agent/`:

```bash
cp .env.sample .env         # set MEMORY_API_KEY=nams_...
uv sync
uv run fraud-server        # Terminal 1
uv run fraud-cli --user-id analyst-1 "Find circular transfer chains"   # Terminal 2
```

Deploy the agent to AgentCore Runtime after the local run works:

```bash
./agent.sh configure
./agent.sh deploy
./agent.sh verify
```

See
[`demos/fraud-amazon-quick/fraud-memory-agent/README.md`](./fraud-memory-agent/README.md)
for the request format, NAMS traffic generation, and diagnostics.

## Step 5: Write the Iceberg tables for Athena

Run from `demos/fraud-amazon-quick/fraud-iceberg/`:

```bash
uv run scripts/write_finance_s3_tables.py --dry-run
uv run scripts/write_finance_s3_tables.py
```

The same folder can also write to a normal S3 bucket with Glue. The sample
Athena queries in `query_finance_athena.py` read the Glue catalog, so run the
Glue loader first if you want them. Pass the same `--region` to the loader and
the query script. See
[`demos/fraud-amazon-quick/fraud-iceberg/README.md`](./fraud-iceberg/README.md)
for bucket names, Regions, and required permissions.

## Step 6: Show the results in Amazon Quick

Amazon Quick shows the Athena tables from Step 5 and the agent from Step 4.
You set up Quick in the AWS console. This repository does not script it.

The [fraud data architecture deck](../../docs/slides/current/fraud-data-architecture.md)
shows how Athena, Neo4j, and Amazon Quick fit together.
