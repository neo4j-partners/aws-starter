# AWS In-Depth Slide Decks

Each section is its own Marp deck. Content was adapted and condensed from
`databricks-neo4j-lab/slides`; the MCP and AgentCore decks were authored from
this repo's `neo4j-agentcore-mcp-server/` and `CLAUDE.md`.

All images are flattened into `./images/` (57 files, including the Neo4j MCP
AgentCore architecture diagram). Marp needs local files, so every deck
references images as `images/<name>`.

## Decks

| # | File | Topic | Source |
|---|------|-------|--------|
| 01 | `01-neo4j-for-agentic-ai-slides.md` | Neo4j for agentic AI: managed graph database, GraphRAG retrieval, retrievers to agents | `overview-knowledge-graph` |
| 02 | `02-aircraft-data-model-slides.md` | Digital twin and flat tables to property graph, then the dual analytics-plus-graph architecture, SQL vs Cypher, when to use which | `overview-knowledge-graph/01,05`, `SUMMARY.md`, `overview-databricks-neo4j/01`, `databricks-in-depth/01` |
| 03 | `03-graphrag-and-genai-slides.md` | GenAI limits, traditional RAG, Context ROT, vectors, the GraphRAG solution | `overview-knowledge-graph/02,03,04,09` |
| 04 | `04-graph-enriched-search-slides.md` | Retrievers: Vector, Vector Cypher, Text2Cypher, graph-enriched retrieval | `overview-retrievers/01-04`, `databricks-in-depth/02` |
| 05 | `05-neo4j-aura-and-agents-slides.md` | Neo4j Aura, why graphs for AI, retrievers to agents, the GraphRAG agent | `overview-knowledge-graph/01-aura`, `overview-retrievers/08` |
| 06 | `06-neo4j-on-aws-slides.md` | Neo4j on AWS Bedrock AgentCore: the MCP server, its tools, the Gateway/Runtime that host it, and the agents that connect | repo `neo4j-agentcore-mcp-server/`, `ARCHITECTURE.md`, `CLAUDE.md` |

## Suggested Presentation Order

01 (Neo4j for agentic AI) -> 02 (data model and dual architecture) ->
03 (GraphRAG) -> 04 (retrievers) -> 05 (Aura and agents) ->
06 (Neo4j on AWS AgentCore).

## Build and Preview

Marp markdown (`marp: true`, `theme: default`, `paginate: true`). Node 22 LTS
required (Marp CLI breaks on Node 25+).

```bash
# Preview one deck
marp "03-graphrag-and-genai-slides.md" --server --allow-local-files

# Export all to PDF
for f in *-slides.md; do marp "$f" --pdf --allow-local-files; done
```

## Notes / Decisions

- Deck 02 combines the aircraft data model with the dual-store concept, and
  makes the analytics side generic
  ("columnar analytics store / lakehouse / data warehouse") and frames routing
  as a multi-agent supervisor on AWS Bedrock AgentCore. Adjust if you want a
  specific AWS analytics service named.
- Decks 03, 04, 05 are platform-neutral Neo4j/GraphRAG content (no AWS or
  Databricks specifics) so they are reusable.
- Em-dashes were removed from all prose per the project writing style.
- Decks live in `docs/slides/aws-in-depth/`. Image paths are relative
  (`images/<name>`), so the deck folder stays portable if moved.
