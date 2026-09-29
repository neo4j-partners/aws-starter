# Fraud Investigation with Amazon Quick

This demo investigates synthetic fraud rings with AWS analytics and Neo4j. One
dataset feeds two stores. Athena queries it as Iceberg tables, and a Strands
agent investigates it as a Neo4j graph. Amazon Quick presents the results.

| Folder | Purpose |
|--------|---------|
| [`data/`](./data/) | The single copy of the synthetic fraud CSVs and `ground_truth.json` |
| [`graph-loader/`](./graph-loader/) | Loads `data/` into Neo4j with a direct driver and adds GDS fraud signals |
| [`fraud-memory-agent/`](./fraud-memory-agent/) | Strands agent that queries the graph through the MCP Gateway and records memory in NAMS |
| [`fraud-iceberg/`](./fraud-iceberg/) | Writes `data/` to Iceberg tables in S3 or S3 Tables for Athena |

## Prerequisites

- A dedicated Neo4j database. Graph Data Science or Aura Graph Analytics is
  needed for the enrichment step.
- AWS credentials with Bedrock model access.
- A NAMS API key from [NAMS](https://memory.neo4jlabs.com/).
- The [`uv`](https://docs.astral.sh/uv/) package manager and Python 3.11+.

## Step 1: Load the graph

```bash
cd graph-loader
cp .env.sample .env       # set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD
uv sync
uv run fraud-graph-load
```

`uv run fraud-graph-load --reset` deletes every node and relationship in the
database before loading. Use it only on the dedicated demo database.

## Step 2: Add GDS fraud signals

```bash
uv run fraud-graph-enrich
uv run fraud-graph-analyze   # optional read-only check of the investigation queries
```

Enrichment adds risk scores, communities, betweenness, and account similarity.
The agent can query the base graph without it. Investigation prompts about
those signals need it. See [`graph-loader/README.md`](./graph-loader/README.md)
for GDS session sizing.

## Step 3: Deploy the MCP server for the fraud graph

The agent reaches Neo4j only through the Neo4j MCP server. Deploy one against
the same database used in Step 1:

```bash
cd ../../../neo4j-mcp-server
cp .env.sample .env.finance  # set the same NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD
./deploy.py --env finance
./deploy.py --env finance credentials
../scripts/sync-credentials.sh
```

`sync-credentials.sh` copies `.mcp-credentials.finance.json` into
`fraud-memory-agent/.mcp-credentials.json`.

## Step 4: Run the fraud memory agent

```bash
cd ../demos/fraud-amazon-quick/fraud-memory-agent
cp .env.sample .env         # set MEMORY_API_KEY=nams_...
uv sync
uv run fraud-server        # Terminal 1
uv run fraud-cli --user-id analyst-1 "Find circular transfer chains"   # Terminal 2
```

Deploy it to AgentCore Runtime when the local run works:

```bash
./agent.sh configure
./agent.sh deploy
./agent.sh verify
```

See [`fraud-memory-agent/README.md`](./fraud-memory-agent/README.md) for the
request contract, NAMS traffic generation, and diagnostics.

## Step 5: Write the Iceberg tables for Athena

```bash
cd ../fraud-iceberg
uv run scripts/write_finance_s3_tables.py --dry-run
uv run scripts/write_finance_s3_tables.py
```

The folder also writes to a normal S3 bucket with Glue and runs sample Athena
queries. See [`fraud-iceberg/README.md`](./fraud-iceberg/README.md) for bucket
naming, Regions, and required permissions.

## Step 6: Present the results in Amazon Quick

Amazon Quick presents the Athena tables from Step 5 and the agent from Step 4.
The Quick setup is done in the AWS console. This repository does not script it.

The [fraud data architecture deck](../../docs/slides/current/fraud-data-architecture.md)
shows how Athena, Neo4j, and Amazon Quick fit together.
