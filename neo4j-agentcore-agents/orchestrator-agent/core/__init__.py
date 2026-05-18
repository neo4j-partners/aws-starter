"""Shared building blocks for the Orchestrator Agent.

Importing the ``core`` package itself pulls only stdlib + httpx — it
re-exports :mod:`core.config` (model id, region) and :mod:`core.credentials`
(credential loading + OAuth2 token refresh).

The remaining submodules carry heavier dependencies and are imported only
where needed, never from this ``__init__``:

- :mod:`core.prompts`  — router and specialist system prompts
- :mod:`core.factory`  — Bedrock LLM + MCP tool factories (LangChain)
- :mod:`core.graph`    — the LangGraph multi-agent orchestrator graph
"""

from core.config import AWS_REGION, MODEL_ID
from core.credentials import (
    check_token_expiry,
    get_active_credentials,
    load_credentials,
    refresh_token,
)

__all__ = [
    "AWS_REGION",
    "MODEL_ID",
    "check_token_expiry",
    "get_active_credentials",
    "load_credentials",
    "refresh_token",
]
