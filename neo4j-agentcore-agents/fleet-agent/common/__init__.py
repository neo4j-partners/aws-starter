"""Shared, framework-agnostic building blocks for the Neo4j MCP fleet agent.

Both framework variants (``langgraph/`` and ``strands/``) import from here:

- :mod:`common.config`      — model id, region, system-prompt template
- :mod:`common.credentials` — credential loading + OAuth2 token refresh
- :mod:`common.schema`      — raw-MCP schema fetch + process-level cache

Nothing in this package depends on LangGraph or Strands. Framework-specific
wiring (LLM construction, MCP tool client) lives in each variant.
"""

from common.config import AWS_REGION, MODEL_ID, SYSTEM_PROMPT_TEMPLATE
from common.credentials import (
    check_token_expiry,
    get_active_credentials,
    load_credentials,
    refresh_token,
)
from common.schema import fetch_schema, get_cached_schema

__all__ = [
    "AWS_REGION",
    "MODEL_ID",
    "SYSTEM_PROMPT_TEMPLATE",
    "check_token_expiry",
    "get_active_credentials",
    "load_credentials",
    "refresh_token",
    "fetch_schema",
    "get_cached_schema",
]
