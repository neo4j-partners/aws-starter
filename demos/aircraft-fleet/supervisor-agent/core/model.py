"""Bedrock model settings shared by the supervisor and its specialists."""

from strands.models import BedrockModel, CacheConfig

from core.config import AWS_REGION, MAX_TOKENS, MODEL_EFFORT, MODEL_ID


def build_model() -> BedrockModel:
    """Build the Bedrock model once at startup.

    No temperature: Sonnet 5.5 rejects non-default sampling parameters.
    Thinking and effort go in ``additional_request_fields``, which Strands
    sends as Converse ``additionalModelRequestFields``.
    """
    return BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        max_tokens=MAX_TOKENS,
        streaming=True,
        cache_config=CacheConfig(strategy="auto"),
        additional_request_fields={
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": MODEL_EFFORT},
        },
    )
