# Finance Genie fraud graph

This directory contains the committed synthetic fraud dataset copied from
`graph-on-databricks/finance-genie`. It is the graph described by the Finance
Agent prompt:

- 25,000 `:Account` nodes and 7,500 `:Merchant` nodes
- 250,000 `:TRANSACTED_WITH` relationships
- 300,000 `:TRANSFERRED_TO` relationships
- `risk_score`, `community_id`, `betweenness_centrality`, and `:SIMILAR_TO`
  supplied by the optional GDS enrichment step

`data/ground_truth.json` identifies the intentionally generated fraud rings.
The original generator is
`finance-genie/enrichment-pipeline/setup/generate_data.py`; this copy uses the
committed deterministic output instead of generating a different dataset.

The proposed graph-native business vocabulary and financial-crime rules are
documented in [ontology.md](./ontology.md). It is an informal ontology held as
ordinary Neo4j nodes and relationships, not an RDF/TTL model.

## Load the graph

The loader talks directly to Neo4j. It needs the same `NEO4J_URI`,
`NEO4J_DATABASE`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD` used to deploy the
MCP server. It does not run as part of the agent runtime.

```bash
cd neo4j-agentcore-agents/finance-agent
cp .env.example .env
# Add NEO4J_* values for the database exposed by your MCP server.

# Safe to repeat: merges the nodes and relationships in this dataset.
uv run finance-graph-load

# Deletes all graph data first, then loads the bundled dataset.
uv run finance-graph-load --reset
```

`--reset` deliberately deletes every node and relationship in the selected
database. Use it only for the dedicated demo graph.

## Add graph metrics

Run this against a Neo4j deployment with Graph Data Science installed:

```bash
uv run finance-graph-enrich
```

When using Aura Graph Analytics, this command creates a temporary GDS session.
It defaults to the smallest supported tier, `GDS_SESSION_MEMORY=2GB`; increase
that value in `.env` if Neo4j reports that the graph or algorithms need more
memory. The session is released when enrichment drops its projected graphs.

The agent can query the base graph after `finance-graph-load`. Run enrichment
before asking about risk scores, communities, betweenness, or behavioral
similarity.
