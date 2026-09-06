# Proposal: `sec-filings-graphrag-demo/`

## Goal

Create the smallest useful GraphRAG demo: one notebook, one install command,
one Neo4j database, and four retrieval patterns that a reader can understand in
a single sitting.

The demo answers one question:

> What does graph enrichment add to vector and keyword retrieval?

Anything that does not help answer that question is out of scope.

## What the demo contains

The notebook builds a small, deterministic graph from two SEC 10-K filings and
then searches it four ways:

| Level | Retrieval pattern | Implementation | What it demonstrates |
|---|---|---|---|
| 1 | Vector | `VectorRetriever` | Semantic similarity |
| 2 | Vector + graph | `VectorCypherRetriever` | Semantic matches enriched with filer and neighboring chunks |
| 3 | Keyword | Neo4j full-text query | Exact terms such as product names and tickers |
| 4 | Vector + keyword + graph | `HybridCypherRetriever` | Both retrieval signals plus graph context |

Level 3 is a complementary retrieval strategy, not a higher level of graph
usage. “Four retrieval patterns” is the precise description; “four levels” is
only a convenient notebook title.

The final cell uses `GraphRAG` with the Level 4 retriever to generate one
grounded answer.

## Why this is separate from `fleet-agent-demo/`

| | `sec-filings-graphrag-demo/` | `fleet-agent-demo/` |
|---|---|---|
| **Shape** | One notebook | Two projects and deployment scripts |
| **Purpose** | Understand retrieval choices | Build and deploy an agent |
| **Data** | Real SEC filings | Synthetic aircraft data |
| **Start here when** | Learning GraphRAG | Building an application |

Read this demo first. Use `fleet-agent-demo/` when the next question is “how do
I ship it?”

## Keep the graph deterministic

The demo does not need LLM-based entity extraction. Extracting Product and
RiskFactor nodes adds schema configuration, many model calls, entity-resolution
behavior, variable output, and failure modes that do not improve the core
lesson.

Build only this graph:

```text
(:Company)-[:FILED]->(:Document)<-[:FROM_DOCUMENT]-(:Chunk)
                                                    -[:NEXT_CHUNK]->(:Chunk)
```

Level 2 starts with the same vector hits as Level 1 and traverses this graph to
return:

- the matched chunk;
- the company and ticker for its filing;
- the immediately preceding and following chunks.

The neighboring chunks make the benefit visible: vector search finds the right
passage, while graph traversal restores local document context. Company,
Document, Chunk, `FILED`, `FROM_DOCUMENT`, and `NEXT_CHUNK` are deterministic,
so rerunning the notebook produces the same graph.

Use a small notebook helper to load PDF text, split it, embed the chunks, and
write the nodes and relationships with parameterized `UNWIND` queries. This is
more direct than configuring an extraction pipeline for a demo about retrieval.
Assign each chunk a deterministic ID such as `<cik>-<position>`.

## Corpus

Copy two PDFs from
`neo4j-bedrock-graphrag-workshop/financial_data_load/financial-data/form10k-sample/`:

| PDF | Company | Why it is included |
|---|---|---|
| `0001045810-23-000017.pdf` | NVIDIA (`NVDA`) | Contains exact terms such as `H100` and `A100` |
| `0001018724-23-000004.pdf` | Amazon (`AMZN`) | Provides a second filer and similar data-center language |

Two filings are enough to demonstrate both exact-term retrieval and reliable
company attribution. Apple adds ingestion time but no behavior used by the demo
questions.

Keep the two metadata records directly in the notebook:

```python
FILINGS = [
    {
        "path": "data/0001045810-23-000017.pdf",
        "company": "NVIDIA CORPORATION",
        "ticker": "NVDA",
        "cik": "1045810",
    },
    {
        "path": "data/0001018724-23-000004.pdf",
        "company": "AMAZON",
        "ticker": "AMZN",
        "cik": "1018724",
    },
]
```

A separate CSV is unnecessary for two records.

## Indexes

Create the indexes after ingestion:

- `chunkEmbeddings`: vector index on `Chunk.embedding`, using Titan Text
  Embeddings V2 at 1024 dimensions with cosine similarity.
- `search_chunks`: full-text index on `Chunk.text`.

Wait for both indexes with `CALL db.awaitIndexes(300)` before searching.

The same embedding model and dimensions must be used for ingestion and queries.
Keep the model ID and dimensions as named constants in the setup cell rather
than repeating them throughout the notebook.

## Safe reruns

The notebook must not erase a database by default. The setup cell includes:

```python
RESET_DATABASE = False
```

If the database is not empty and `RESET_DATABASE` is false, stop with a clear
message instructing the reader to use a dedicated empty database or explicitly
enable reset. When reset is enabled, state immediately above the cell that it
deletes every node, relationship, and demo index in the selected database.

Ingestion should fail visibly. Do not continue after a filing fails, because a
partial graph makes the retrieval comparison misleading.

## Retrieval query

Use the same graph-enrichment query for Levels 2 and 4. It returns a stable
chunk ID, source metadata, and adjacent text:

```cypher
MATCH (node)-[:FROM_DOCUMENT]->(doc:Document)<-[:FILED]-(company:Company)
OPTIONAL MATCH (previous:Chunk)-[:NEXT_CHUNK]->(node)
OPTIONAL MATCH (node)-[:NEXT_CHUNK]->(following:Chunk)
RETURN node.text AS text,
       score,
       {
         chunk_id: node.uid,
         document: doc.name,
         company: company.name,
         ticker: company.ticker,
         previous_text: previous.text,
         next_text: following.text
       } AS metadata
```

Every strategy must expose the same minimum fields so results are easy to
compare:

- rank;
- score;
- chunk ID;
- a short text preview.

Levels 2 and 4 also show company, ticker, and adjacent context.

## Comparison questions

Run two questions through all four strategies with one shared comparison
helper:

1. `What are the risks to data center revenue?`
   This tests semantic retrieval because the wording is paraphrase-heavy.
2. `risks to H100 and A100 sales`
   This tests keyword retrieval because the model names must be matched
   precisely.

Display one compact result table per question. Do not print eight long blocks
of chunk text. The expected lesson is:

- vector retrieval is strong on paraphrased meaning;
- keyword retrieval is strong on exact identifiers;
- graph enrichment adds source and neighboring context;
- hybrid graph retrieval combines all three benefits.

Avoid claiming that graph enrichment improves ranking. Levels 1 and 2 begin
with the same vector hits; Level 2 improves the context supplied with those
hits.

## Notebook outline

Use seven code cells, each preceded by a short markdown explanation:

| # | Cell | Purpose |
|---|---|---|
| 1 | Configure | Load `.env`, define model/index constants, connect, and verify prerequisites |
| 2 | Ingest | Optionally reset, load both PDFs, chunk, embed, and write the deterministic graph |
| 3 | Index and verify | Create both indexes; show company, document, chunk, and relationship counts |
| 4 | Define retrieval | Create the four retrieval strategies and one result-formatting helper |
| 5 | Compare | Run both questions and display compact comparison tables |
| 6 | Answer | Generate one answer with `GraphRAG` over `HybridCypherRetriever` |
| 7 | Close | Close the Neo4j driver |

The notebook narrative is:

```text
Goal → Build a small graph → Compare four retrieval patterns → Generate an answer → Takeaway
```

## Proposed layout

```text
sec-filings-graphrag-demo/
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.sample
├── 4_levels_of_graphrag.ipynb
└── data/
    ├── 0001045810-23-000017.pdf
    └── 0001018724-23-000004.pdf
```

The environment must include the notebook runtime, not only application
libraries. Keep dependencies minimal and lock them after validating a clean
installation:

```toml
dependencies = [
    "ipykernel",
    "neo4j",
    "neo4j-graphrag[bedrock]>=1.18",
    "pypdf",
    "python-dotenv",
]
```

The notebook imports the Neo4j driver and PDF reader directly, so both are
declared explicitly rather than relying on transitive dependencies.

## Requirements

- A dedicated empty Neo4j Aura Free database.
- AWS credentials with access to Titan Text Embeddings V2 and the selected
  Bedrock text model.
- `uv` and Python 3.10 or later.

Use Aura Free as the documented path. Local Docker can be mentioned in one
sentence as an alternative, but it should not create a second setup guide.

The README should offer one installation command:

```bash
uv sync
```

Then tell the reader to select the project's `.venv` kernel and run the notebook
from top to bottom.

## Implementation plan

### Goal

Deliver a self-contained notebook that builds the two-filing graph, compares
the four retrieval patterns, and produces one grounded answer from a clean
checkout.

### Assumptions

- The two source PDFs may be copied into this repository.
- Development uses a dedicated Neo4j database that may be cleared when reset is
  explicitly enabled.
- AWS credentials and Bedrock model access already exist; the demo documents
  them but does not provision them.
- The existing workshop may be used as a reference, but the finished demo must
  not depend on files outside this repository.

### Risks

- Bedrock model availability varies by AWS region. Validate the documented
  model IDs in the target region.
- PDF extraction or chunking changes can alter retrieval results. Lock
  dependencies after the expected comparison has been verified.
- Vector and full-text scores are not directly comparable. Present rankings
  within each strategy and avoid cross-strategy score claims.
- A reset can destroy unrelated data. Keep it disabled by default and test the
  non-empty-database guard.

### Phase 1: Scaffold the sample

**Status:** Pending

**Outcome:** The sample has a minimal, installable structure with all required
local inputs.

- [ ] Create the `sec-filings-graphrag-demo` directory and proposed files.
- [ ] Copy only the NVIDIA and Amazon filings into its `data` directory.
- [ ] Define the direct runtime dependencies and generate the lockfile.
- [ ] Add a minimal environment-variable sample with Neo4j and AWS settings.
- [ ] Confirm a clean environment can create and select the notebook kernel.

**Validation:** Installation succeeds from a clean checkout and the notebook
can import every required package.

### Phase 2: Build the deterministic graph

**Status:** Pending

**Outcome:** Running the ingestion cells creates the same document graph on
every clean run.

- [ ] Load and validate the two filing metadata records and PDF paths.
- [ ] Extract text, split it into ordered chunks, and assign deterministic
  chunk IDs.
- [ ] Generate embeddings with one named model configuration.
- [ ] Write Company, Document, and Chunk nodes with their three relationship
  types using parameterized queries.
- [ ] Add the disabled-by-default reset and the non-empty-database guard.
- [ ] Stop immediately with a useful error if either filing fails.
- [ ] Report concise node and relationship counts after ingestion.

**Validation:** The graph contains exactly two Company and two Document nodes;
all chunks have text, embeddings, IDs, document links, and the expected reading
order.

### Phase 3: Add the four retrieval patterns

**Status:** Pending

**Outcome:** One shared interface runs the same question through four distinct
retrieval strategies.

- [ ] Create and await the vector and full-text indexes.
- [ ] Implement vector retrieval with `VectorRetriever`.
- [ ] Implement graph-enriched vector retrieval with
  `VectorCypherRetriever`.
- [ ] Implement keyword retrieval with one full-text query.
- [ ] Implement hybrid graph retrieval with `HybridCypherRetriever`.
- [ ] Normalize results into rank, score, chunk ID, and text preview.
- [ ] Include company, ticker, and adjacent context only when graph enrichment
  supplies them.

**Validation:** Both questions return results from all four strategies; every
result has a chunk ID, and graph-enriched results contain the expected source
and neighboring context.

### Phase 4: Finish the teaching flow

**Status:** Pending

**Outcome:** A reader can understand the comparison without reading long raw
outputs or implementation internals.

- [ ] Organize the notebook into the seven planned code cells.
- [ ] Add one short explanation before each cell.
- [ ] Display one compact comparison table for each question.
- [ ] Explain semantic, exact-term, and graph-context differences without
  claiming that graph enrichment changes vector ranking.
- [ ] Generate one final grounded answer with the Level 4 retriever.
- [ ] End with a short takeaway and close the database connection.

**Validation:** A reviewer unfamiliar with the source workshop can explain what
each retrieval pattern adds after one top-to-bottom run.

### Phase 5: Integrate and verify

**Status:** Pending

**Outcome:** The sample is discoverable, reproducible, and safe to rerun.

- [ ] Write the sample README with one primary Aura setup path.
- [ ] Add the sample to the top-level README before the Fleet Agent Demo.
- [ ] Add the documentation-index link and cross-links between both demos.
- [ ] Run the full notebook against a fresh empty database.
- [ ] Run it again with reset disabled and confirm that it stops safely.
- [ ] Enable reset deliberately, rerun, and confirm equivalent graph and
  retrieval behavior.
- [ ] Review the committed files for credentials, generated output, and
  unnecessary dependencies.

**Validation:** Every acceptance criterion below passes from a clean checkout,
and the README contains no dependency on the external workshop directory.

## Acceptance criteria

Before merging, validate the demo from a clean checkout:

- `uv sync` creates a usable notebook kernel.
- Running all cells against an empty database completes without manual code
  edits.
- The graph contains exactly two Company and two Document nodes, plus multiple
  linked Chunk nodes.
- Both indexes report `ONLINE` before retrieval begins.
- Every result includes a chunk ID; Levels 2 and 4 include company and adjacent
  context.
- The exact-term question visibly benefits from keyword retrieval.
- A second run stops safely unless reset is explicitly enabled.

## Deliberate omissions

- No agent, MCP server, AgentCore deployment, or CDK.
- No LLM entity extraction or entity-resolution pipeline.
- No reranker or `alpha` comparison.
- No ingestion framework comparison.
- No more than two filings and two demonstration questions.

These topics are valuable, but none is required to understand the four
retrieval patterns.

## Repository placement

Place `sec-filings-graphrag-demo/` at the repository root immediately before
the Fleet Agent Demo in the top-level README. Add one documentation-index link
and one sentence directing readers to this notebook first when learning
GraphRAG.
