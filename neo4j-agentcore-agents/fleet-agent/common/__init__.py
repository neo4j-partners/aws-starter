"""Shared, framework-agnostic building blocks for the Neo4j fleet agent.

Both framework variants (``langgraph/`` and ``strands/``) import from here:

- :mod:`common.config`       — model id, region, embedder/index, prompt
- :mod:`common.neo4j_tools`  — direct-to-Neo4j GraphRAG retrieval callables

The agent connects straight to Neo4j (no MCP server, no AgentCore Gateway).
Framework-specific wiring (LLM construction, tool binding) lives in each
variant; the retrieval callables here are plain functions both variants wrap.

Importing this package loads the agent-root ``.env``, the fleet-agent
directory one level up from ``common/``, so local runs pick up the Neo4j
connection vars regardless of the working directory. Existing environment
variables are never overridden, so shell-exported vars and AgentCore Runtime
env vars still take precedence; in the deployed Runtime there is no ``.env``
and the load is a harmless no-op.
"""

from pathlib import Path

from dotenv import load_dotenv

# fleet-agent/ is the parent of common/; its .env is the local config source.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from common.config import (  # noqa: E402  (must follow load_dotenv)
    AWS_REGION,
    EMBED_DIMENSIONS,
    EMBED_MODEL_ID,
    MODEL_ID,
    SYSTEM_PROMPT_TEMPLATE,
    VECTOR_INDEX_NAME,
)
from common.neo4j_tools import (  # noqa: E402  (must follow load_dotenv)
    close,
    get_driver,
    get_graph_schema,
    graph_query,
    vector_search,
)

__all__ = [
    "AWS_REGION",
    "EMBED_DIMENSIONS",
    "EMBED_MODEL_ID",
    "MODEL_ID",
    "SYSTEM_PROMPT_TEMPLATE",
    "VECTOR_INDEX_NAME",
    "close",
    "get_driver",
    "get_graph_schema",
    "graph_query",
    "vector_search",
]
