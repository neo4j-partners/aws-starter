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
first text block instead.

Only the structured path, list input with a ``response_format``, carries the
effort setting. That is the only path the entity extractor uses, because
``AnthropicLLM.supports_structured_output`` is true.
"""

from __future__ import annotations

from typing import Any, Literal

from neo4j_graphrag.exceptions import LLMGenerationError
from neo4j_graphrag.llm.anthropic_llm import AnthropicLLM
from pydantic import BaseModel

Effort = Literal["low", "medium", "high", "xhigh", "max"]


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

        Raises:
            LLMGenerationError: If the response has no text block.
        """
        text = next(
            (block.text for block in response.content if block.type == "text"),
            None,
        )
        if text is None:
            raise LLMGenerationError("Expected a text block in the response, found none.")
        return text
