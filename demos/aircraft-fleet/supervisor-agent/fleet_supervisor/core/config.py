"""Static configuration for the supervisor agent.

Values come from the environment at import time, so a local ``.env`` or a
runtime environment variable set at deploy time can override the defaults
without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Required configuration is missing or unusable.

    The message names the setting, so it belongs in the server log. Clients
    get a generic message instead.
    """


MODEL_ID = os.getenv("MODEL_ID", "global.anthropic.claude-sonnet-5-5")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Explicit output cap for every model call. Streaming is on, so a large cap
# does not risk an HTTP timeout.
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "16000"))

# Sonnet 5.5 runs adaptive thinking by default and cannot turn it off fully.
# ``high`` is the Sonnet 5.5 default, set here explicitly.
MODEL_EFFORT = os.getenv("MODEL_EFFORT", "high")

# Local development port. AgentCore Runtime always uses 8080.
LOCAL_PORT = int(os.getenv("AGENT_PORT", "7071"))


def _env_int(name: str, default: int) -> int:
    """Read an int env var. An unset or empty value gives ``default``."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None


def _env_float(name: str, default: float) -> float:
    """Read a float env var. An unset or empty value gives ``default``."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None


# Suggested follow-up questions come from one small structured call after each
# UI answer. Haiku 4.5 is fast and cheap enough for a three-question list.
FOLLOWUP_MODEL_ID = os.getenv(
    "FOLLOWUP_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0"
)
# The answer has already streamed when the call starts, so a slow call only
# delays the links and the end of the turn. Past this bound, no links are sent.
FOLLOWUP_TIMEOUT_S = _env_float("FOLLOWUP_TIMEOUT_S", 5.0)


@dataclass(frozen=True, slots=True)
class GraphSettings:
    """Settings for the graph tools in :mod:`core.graph`, resolved by :meth:`from_env`.

    The vector index and embedder MUST match what ``aircraft-fleet-pipeline``
    used to populate the graph, or vector search returns noise. They default
    to Amazon Bedrock Titan v2 with 1024 dimensions on the
    ``maintenanceChunkEmbeddings`` index over ``:Chunk(text)``. Hybrid search
    also uses the ``maintenanceChunkText`` fulltext index. The Cypher-writing
    model and its region are ``MODEL_ID`` and ``AWS_REGION`` above. Every
    field is env-overridable.
    """

    vector_index_name: str = "maintenanceChunkEmbeddings"
    fulltext_index_name: str = "maintenanceChunkText"
    schema_ttl_s: int = 600
    text2cypher_timeout_s: float = 30.0
    text2cypher_max_rows: int = 200
    # Output cap for the Cypher-writing call. A query needs far less than the
    # agent's MAX_TOKENS, and the cap stops a runaway generation early.
    text2cypher_max_tokens: int = 2048
    embed_model_id: str = "amazon.titan-embed-text-v2:0"
    embed_dimensions: int = 1024

    @classmethod
    def from_env(cls) -> GraphSettings:
        """Build settings from the environment, falling back to the defaults."""
        defaults = cls()
        return cls(
            vector_index_name=os.getenv("VECTOR_INDEX_NAME") or defaults.vector_index_name,
            fulltext_index_name=os.getenv("FULLTEXT_INDEX_NAME") or defaults.fulltext_index_name,
            schema_ttl_s=_env_int("SCHEMA_TTL_S", defaults.schema_ttl_s),
            text2cypher_timeout_s=_env_float(
                "TEXT2CYPHER_TIMEOUT_S", defaults.text2cypher_timeout_s
            ),
            text2cypher_max_rows=_env_int("TEXT2CYPHER_MAX_ROWS", defaults.text2cypher_max_rows),
            text2cypher_max_tokens=_env_int(
                "TEXT2CYPHER_MAX_TOKENS", defaults.text2cypher_max_tokens
            ),
            embed_model_id=os.getenv("EMBED_MODEL_ID") or defaults.embed_model_id,
            embed_dimensions=_env_int("EMBED_DIMENSIONS", defaults.embed_dimensions),
        )


# Resolved once at import, like the constants above.
graph_settings = GraphSettings.from_env()
