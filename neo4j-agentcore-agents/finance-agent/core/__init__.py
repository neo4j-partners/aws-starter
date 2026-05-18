"""Shared building blocks for the Finance Agent.

Importing the ``core`` package itself pulls only stdlib + httpx — it
re-exports :mod:`core.config` (model id, region, system prompt) and
:mod:`core.credentials` (credential loading + OAuth2 token refresh).

The remaining submodules carry heavier dependencies and are imported only
where needed, never from this ``__init__``:

- :mod:`core.transport` — MCP transport factory (depends on ``mcp``)
- :mod:`core.factory`  — Bedrock model + MCP client factories (Strands)
- :mod:`core.memory`    — user-scoped Context Graph tools (Strands)
"""

from core.config import AWS_REGION, MODEL_ID, SYSTEM_PROMPT
from core.credentials import (
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
