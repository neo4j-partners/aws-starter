"""Bedrock model settings shared by the supervisor and its specialists.

``thinking_request_fields`` and ``build_bedrock_model`` match the signatures
of the shared factory in graphrag-agent's ``agent/model.py``, so this module
can switch to it with an import change.
"""

from strands.models import BedrockModel, CacheConfig

from core.config import AWS_REGION, MAX_TOKENS, MODEL_EFFORT, MODEL_ID


def thinking_request_fields(effort: str = MODEL_EFFORT) -> dict[str, object]:
    """Return the Converse ``additionalModelRequestFields`` for adaptive thinking."""
    return {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
    }


def build_bedrock_model(
    model_id: str = MODEL_ID,
    region_name: str | None = None,
    *,
    max_tokens: int = MAX_TOKENS,
    effort: str = MODEL_EFFORT,
) -> BedrockModel:
    """Build a streaming ``BedrockModel`` with caching and adaptive thinking.

    No temperature: Sonnet 5.5 rejects non-default sampling parameters.
    """
    return BedrockModel(
        model_id=model_id,
        region_name=region_name,
        max_tokens=max_tokens,
        streaming=True,
        cache_config=CacheConfig(strategy="auto"),
        additional_request_fields=thinking_request_fields(effort),
    )


def build_model() -> BedrockModel:
    """Build the supervisor's model from ``core.config``."""
    return build_bedrock_model(MODEL_ID, AWS_REGION)
