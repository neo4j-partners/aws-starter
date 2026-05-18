# AWS In-Depth Slide Decks

Each section is its own Marp deck. Content was adapted and condensed from
`databricks-neo4j-lab/slides`; the AgentCore deck was authored from this
repo's `neo4j-agentcore-mcp-server/` and `CLAUDE.md`.

All images are flattened into `./images/` (57 files, including the Neo4j MCP
AgentCore architecture diagram). Marp needs local files, so every deck
references images as `images/<name>`.

## Decks

| # | File | Topic | Source |
|---|------|-------|--------|
| 01 | `01-neo4j-for-agentic-ai-slides.md` | Neo4j for agentic AI: managed graph database, GraphRAG retrieval, retrievers to agents | `overview-knowledge-graph` |
| 02 | `02-aircraft-data-model-slides.md` | Digital twin and flat tables to property graph, then the dual analytics-plus-graph architecture, SQL vs Cypher, when to use which | `overview-knowledge-graph/01,05`, `SUMMARY.md`, `overview-databricks-neo4j/01`, `databricks-in-depth/01` |
| 03 | `03-graphrag-and-retrievers-slides.md` | GenAI limits and Context ROT, the GraphRAG solution, then the three retrievers (Vector, Vector Cypher, Text2Cypher) in practice and as agent tools; embedding fundamentals in an appendix | `overview-knowledge-graph/02,03,04,09`, `overview-retrievers/01-04`, `databricks-in-depth/02` |
| 04 | `04-neo4j-on-aws-slides.md` | Neo4j on AWS Bedrock AgentCore: the MCP server, its tools, the Gateway/Runtime that host it, and the agents that connect | repo `neo4j-agentcore-mcp-server/`, `ARCHITECTURE.md`, `CLAUDE.md` |

## Suggested Presentation Order

01 (Neo4j for agentic AI) -> 02 (data model and dual architecture) ->
03 (GraphRAG and retrievers) -> 04 (Neo4j on AWS AgentCore).

## Build and Preview

Marp markdown (`marp: true`, `theme: default`, `paginate: true`). Node 22 LTS
required (Marp CLI breaks on Node 25+).

```bash
# Preview one deck
marp "03-graphrag-and-retrievers-slides.md" --server --allow-local-files

# Export all to PDF
for f in *-slides.md; do marp "$f" --pdf --allow-local-files; done
```

## Notes / Decisions

- Deck 02 combines the aircraft data model with the dual-store concept, and
  makes the analytics side generic
  ("columnar analytics store / lakehouse / data warehouse") and frames routing
  as a multi-agent supervisor on AWS Bedrock AgentCore. Adjust if you want a
  specific AWS analytics service named.
- Deck 03 merges the former GraphRAG deck and the retrievers deck into one
  arc: traditional RAG limits, the GraphRAG solution, the three retrievers in
  practice, and retrievers as agent tools. GenAI and embedding fundamentals
  live in the appendix. The earlier standalone Aura/agents deck was removed.
- Decks 01-03 are platform-neutral Neo4j/GraphRAG content (no AWS or
  Databricks specifics) so they are reusable.
- Em-dashes were removed from all prose per the project writing style.
- Decks live in `docs/slides/aws-in-depth/`. Image paths are relative
  (`images/<name>`), so the deck folder stays portable if moved.
