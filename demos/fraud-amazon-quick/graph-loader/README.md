# Fraud Graph Loader

This project loads a synthetic fraud dataset into Neo4j. The Fraud Memory
Agent queries this graph through the Neo4j MCP server.

## Overview

- **Dataset:** The dataset lives in [data/](../data/). It holds 25,000 accounts, 7,500 merchants, 250,000 merchant transactions, and 300,000 account transfers.
- **Loader:** The loader connects to Neo4j directly with a driver. It does not run inside the agent.
- **Enrichment:** An optional step uses Graph Data Science to add risk scores, communities, and similar-account links.
- **Analysis:** A read-only command runs fraud investigation queries and prints the results.
- **Fraud rings:** The file [ground_truth.json](../data/ground_truth.json) lists the fraud rings planted in the data.

## Quick start

```bash
cd demos/fraud-amazon-quick/graph-loader
cp .env.sample .env        # add your NEO4J_* values
uv sync

uv run fraud-graph-load    # load the graph
uv run fraud-graph-enrich  # add GDS metrics (optional)
uv run fraud-graph-analyze # run the investigation queries
```

## Configure the connection

Put these values in `.env`:

- **`NEO4J_URI`:** This is the address of your Neo4j database.
- **`NEO4J_DATABASE`:** This is the database name, usually `neo4j`.
- **`NEO4J_USERNAME` and `NEO4J_PASSWORD`:** These are your database login.

Use the same values as the MCP server's `.env.finance` file. The agent then
queries the same graph that you load here.

## Load the graph

```bash
uv run fraud-graph-load
uv run fraud-graph-load --reset
```

- **`fraud-graph-load`:** This command merges the dataset into Neo4j. You can run it more than once. It does not create duplicates.
- **`--reset`:** This flag deletes every node and relationship in the database, then loads the dataset. Use it only on a database set aside for this demo.

The graph has these parts:

- **`:Account` nodes:** The graph has 25,000 accounts.
- **`:Merchant` nodes:** The graph has 7,500 merchants.
- **`:TRANSACTED_WITH` relationships:** These 250,000 links connect accounts to merchants.
- **`:TRANSFERRED_TO` relationships:** These 300,000 links connect accounts to other accounts.
- **`:Customer`, `:Phone`, and `:Address` nodes:** Customers own accounts through `:OWNS`. Each customer links to a phone number and an address.

## Add graph metrics

```bash
uv run fraud-graph-enrich
```

This command needs a Neo4j deployment with Graph Data Science. It adds these
fields:

- **`risk_score`:** This PageRank score shows how central an account is in the transfer network.
- **`community_id`:** This ID groups accounts that transfer money mostly among themselves.
- **`betweenness_centrality`:** This score shows how often an account sits on the path between other accounts.
- **`:SIMILAR_TO`:** This relationship links accounts that buy from many of the same merchants.

On Aura Graph Analytics, the command starts a temporary GDS session. The
session uses 2GB of memory by default. Set `GDS_SESSION_MEMORY` in `.env` to a
larger value if Neo4j reports that it needs more memory. The session closes
when enrichment finishes.

The agent can query the graph right after loading. Run enrichment before you
ask about risk scores, communities, betweenness, or similar accounts.

## Analyze the graph

```bash
uv run fraud-graph-analyze
uv run fraud-graph-analyze --analysis circular-flows --limit 10
```

This command only reads data. With no flags, it runs every analysis. Use
`--analysis` to pick one:

- **`circular-flows`:** This analysis finds three-hop transfer loops that return to the starting account.
- **`internal-communities`:** This analysis ranks communities by how much money moves inside each group. It needs enrichment first.
- **`shared-kyc`:** This analysis finds customers who share a phone number or address, with the accounts they own.
- **`common-counterparties`:** This analysis finds pairs of accounts that send transfers to the same account.
- **`similar-behavior`:** This analysis finds accounts linked by `:SIMILAR_TO`. It needs enrichment first.

## Ontology

The file [ontology.md](./ontology.md) defines the business terms and fraud
rules for this graph. The terms are stored as plain Neo4j nodes and
relationships. They are not an RDF or TTL model.
