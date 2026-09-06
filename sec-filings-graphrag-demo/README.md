# SEC Filings GraphRAG Demo

This notebook builds a deterministic graph from NVIDIA and Amazon 10-K
filings. It is the small, learning-focused introduction to GraphRAG in this
repository. The retrieval comparison is completed in later implementation
phases.

## Requirements

- Python 3.10 or later and `uv`
- A dedicated, empty Neo4j Aura Free database
- AWS credentials with access to Amazon Titan Text Embeddings V2 in the
  configured region

Local Neo4j can also be used, but Aura Free is the primary documented path.

## Setup

1. Copy `.env.sample` to `.env` and fill in the Neo4j connection details.
2. Install the environment:

   ```bash
   uv sync
   ```

3. Open `4_levels_of_graphrag.ipynb`, select the project's `.venv` kernel,
   and run the notebook from top to bottom.

The notebook refuses to ingest into a non-empty database by default. Use a
dedicated database. Setting `RESET_DATABASE = True` explicitly deletes every
node and relationship and drops the two demo indexes named in the notebook.
