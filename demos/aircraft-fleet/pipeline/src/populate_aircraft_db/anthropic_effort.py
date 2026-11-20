"""AnthropicLLM that sets effort on structured extraction calls.

UNTESTED against the live Anthropic API. This project has no Anthropic API
key in its test setup. Only the request shape and text extraction were
checked, with a stubbed client.

``neo4j-graphrag`` 1.24 ``AnthropicLLM`` builds ``output_config`` itself for
structured output, so ``effort`` cannot go in ``model_params``: a second
``output_config`` there collides with it as a duplicate keyword argument.
:class:`EffortAnthropicLLM` adds ``effort`` to the ``output_config`` the
library builds instead. Pass ``thinking`` through ``model_params`` as usual.

The stock ``_extract_text`` reads ``content[0]``. With thinking on, that is a
thinking block, so it raises "Expected a text block". This class reads the
first text block instead. When the reply has no text block, it returns content
that fails graph validation, so the extractor's ``OnError`` setting applies.
This matches how ``StructuredBedrockLLM`` handles a miss.

Only the structured path, list input with a ``response_format``, carries the
effort setting. That is the only path the entity extractor uses, because
``AnthropicLLM.supports_structured_output`` is true.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from neo4j_graphrag.llm.anthropic_llm import AnthropicLLM
from pydantic import BaseModel

logger = logging.getLogger(__name__)

Effort = Literal["low", "medium", "high", "xhigh", "max"]

_MISS_PREFIX = "EffortAnthropicLLM miss"


class EffortAnthropicLLM(AnthropicLLM):
    """``AnthropicLLM`` that adds ``effort`` to structured-output requests."""

    def __init__(self, *args: Any, effort: Effort, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.effort = effort

    def _build_output_config(  # type: ignore[override]
        self, response_format: type[BaseModel] | dict[str, Any]
    ) -> dict[str, Any]:
        """Return the library's ``output_config`` with ``effort`` added."""
        return {**AnthropicLLM._build_output_config(response_format), "effort": self.effort}

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Return the text of the first text block, skipping thinking blocks.

        When the response has no text block, return a miss message instead.
        It is not valid graph JSON, so the extractor's ``OnError`` applies.
        """
        text = next(
            (block.text for block in response.content if block.type == "text"),
            None,
        )
        if text is None:
            stop_reason = getattr(response, "stop_reason", None)
            logger.warning(
                "EffortAnthropicLLM: no text block in response (stop_reason=%s).",
                stop_reason,
            )
            return f"{_MISS_PREFIX} (no text block, stop_reason={stop_reason})"
        return text
