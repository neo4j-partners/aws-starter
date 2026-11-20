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
first text block instead. A reply with no text block is a miss. Like
``StructuredBedrockLLM``, this class counts each miss in ``miss_count``, logs
it with the running count, and returns content that fails graph validation,
so the extractor's ``OnError`` setting applies. Unlike the Bedrock path, it
does not retry: a miss here usually means the reply stopped at
``max_tokens``, and a retry would stop there too.

Only the structured path, list input with a ``response_format``, carries the
effort setting. That is the only path the entity extractor uses, because
``AnthropicLLM.supports_structured_output`` is true.
"""

from __future__ import annotations

import logging
import threading
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
        # Chunks can run concurrently, so guard the count.
        self.miss_count = 0
        self._miss_lock = threading.Lock()

    def _build_output_config(  # type: ignore[override]
        self, response_format: type[BaseModel] | dict[str, Any]
    ) -> dict[str, Any]:
        """Return the library's ``output_config`` with ``effort`` added."""
        return {**AnthropicLLM._build_output_config(response_format), "effort": self.effort}

    def _extract_text(self, response: Any) -> str:
        """Return the text of the first text block, skipping thinking blocks.

        When the response has no text block, count and log a miss and return
        a miss message. It is not valid graph JSON, so the extractor's
        ``OnError`` applies.
        """
        text = next(
            (block.text for block in response.content if block.type == "text"),
            None,
        )
        if text is None:
            stop_reason = getattr(response, "stop_reason", None)
            with self._miss_lock:
                self.miss_count += 1
                count = self.miss_count
            logger.warning(
                "EffortAnthropicLLM: no text block in response (stop_reason=%s) (miss %d this run).",
                stop_reason,
                count,
            )
            return f"{_MISS_PREFIX} (no text block, stop_reason={stop_reason})"
        return text
