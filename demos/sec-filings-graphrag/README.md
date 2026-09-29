# SEC Filings GraphRAG Demo

This notebook builds a small graph from NVIDIA and Amazon 10-K filings. It is
the short, beginner introduction to GraphRAG in this repository.

## Overview

- **Notebook:** The notebook is `4_levels_of_graphrag.ipynb`.
- **Data:** The two 10-K filings are PDFs in [`demos/sec-filings-graphrag/data/`](./data/).
- **Graph:** The notebook splits each filing into chunks, embeds them with Amazon Titan Text Embeddings V2, and writes them to Neo4j. The same input always builds the same graph.
- **Retrieval:** The notebook compares four retrieval strategies: vector, vector plus graph, keyword, and vector plus keyword plus graph.
- **Status:** The notebook has graph ingestion and all four strategies. A later phase will add the comparison tables and the final grounded answer.

## Quick start

Run these commands from the repo root:

```bash
cd demos/sec-filings-graphrag
cp .env.sample .env        # add your Neo4j connection details
uv sync
```

Then open `4_levels_of_graphrag.ipynb`, select the project's `.venv` kernel,
and run the notebook from top to bottom.

## Requirements

- **Python:** You need Python 3.10 or later and `uv`.
- **Neo4j:** You need a dedicated, empty Neo4j Aura Free database. A local Neo4j database also works, but these docs cover Aura Free.
- **AWS:** Your AWS credentials need access to Amazon Titan Text Embeddings V2 in the configured region.

## Configure `.env`

- **`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`:** These values connect the notebook to Neo4j.
- **`AWS_REGION`:** This value sets the Bedrock region. It defaults to `us-east-1`.
- **`AWS_PROFILE`:** Set this value only to use a named local AWS profile. Otherwise the notebook uses the standard AWS credential chain.
- **`BEDROCK_TEXT_MODEL_ID`:** The final answer cell will use this model. That cell does not exist yet.

## Protect your data

The notebook stops before it writes if the database already has any nodes. Use
a dedicated database for this demo.

To start over, set `RESET_DATABASE = True` in the configuration cell. The
notebook then deletes every node and relationship in the database. It also
drops the two demo indexes, `chunkEmbeddings` and `search_chunks`.
