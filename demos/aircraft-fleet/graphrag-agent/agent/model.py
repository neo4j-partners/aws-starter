"""Strands ``BedrockModel`` factory for the GraphRAG agent.

Claude Sonnet 5.5 rejects any ``temperature`` value and rejects
``{"type": "disabled"}`` thinking, so neither is sent. Adaptive thinking and
the effort level are set explicitly in ``additionalModelRequestFields``.
"""

from __future__ import annotations

from strands.models import BedrockModel, CacheConfig

from agent.config import DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, DEFAULT_MODEL_ID, Effort


def thinking_request_fields(effort: Effort = DEFAULT_EFFORT) -> dict[str, object]:
    """Return the Converse ``additionalModelRequestFields`` for adaptive thinking."""
    return {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
    }


def build_bedrock_model(
    model_id: str = DEFAULT_MODEL_ID,
    region_name: str | None = None,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    effort: Effort = DEFAULT_EFFORT,
) -> BedrockModel:
    """Build a streaming ``BedrockModel`` with caching and adaptive thinking.

    ``CacheConfig(strategy="auto")`` caches the system prompt and tool specs.
    The graphrag system prompt embeds the full graph schema, so repeat calls
    read it from the cache.
    """
    return BedrockModel(
        model_id=model_id,
        region_name=region_name,
        max_tokens=max_tokens,
        streaming=True,
        cache_config=CacheConfig(strategy="auto"),
        additional_request_fields=thinking_request_fields(effort),
    )
