"""Shared, framework-agnostic building blocks for the Finance Agent.

The agent entrypoint imports from here:

- :mod:`common.config`      — model id, region, system prompt
- :mod:`common.credentials` — credential loading + OAuth2 token refresh

Nothing in this package depends on Strands. Framework-specific wiring (model
construction, MCP client) lives in ``runtime_app.py``.
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
