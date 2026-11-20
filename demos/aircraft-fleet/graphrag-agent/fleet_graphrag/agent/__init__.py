"""Shared building blocks for the Aircraft Fleet GraphRAG Agent.

The runtime entrypoint (``fleet_graphrag.server``) and the Strands tool wrappers
(``agent.tools``) import from here:

- :mod:`agent.config`     — model id, region, embedder/index, prompt
- :mod:`agent.retrieval`  — direct-to-Neo4j GraphRAG retrieval callables

The agent connects straight to Neo4j (no MCP server, no AgentCore Gateway).
Strands-specific wiring (LLM construction, tool binding) lives in
``fleet_graphrag.server``; the retrieval callables here are plain functions it wraps.

Importing this package has no side effects on the environment. Entry points
such as ``fleet_graphrag.server`` load the local ``.env`` before importing it.
"""

from fleet_graphrag.agent.config import (
    SYSTEM_PROMPT_TEMPLATE,
    ConfigError,
    Settings,
    settings,
)
from fleet_graphrag.agent.retrieval import (
    close,
    get_driver,
    get_graph_schema,
    graph_query,
    vector_search,
)

__all__ = [
    "SYSTEM_PROMPT_TEMPLATE",
    "ConfigError",
    "Settings",
    "settings",
    "close",
    "get_driver",
    "get_graph_schema",
    "graph_query",
    "vector_search",
]
