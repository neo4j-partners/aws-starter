"""Shared, framework-agnostic building blocks for the Finance Agent.

Both framework variants (``langgraph/`` and ``strands/``) import from here:

- :mod:`common.config`      — model id, region, system prompt
- :mod:`common.credentials` — credential loading + OAuth2 token refresh

Nothing in this package depends on LangGraph or Strands. Framework-specific
wiring (LLM construction, MCP client) lives in each variant.
"""

from common.config import AWS_REGION, MODEL_ID, SYSTEM_PROMPT
from common.credentials import (
    check_token_expiry,
    get_active_credentials,
    load_credentials,
    refresh_token,
)

__all__ = [
    "AWS_REGION",
    "MODEL_ID",
    "SYSTEM_PROMPT",
    "check_token_expiry",
    "get_active_credentials",
    "load_credentials",
    "refresh_token",
]
