"""Structured-output BedrockLLM via Converse tool use.

``neo4j-graphrag`` 1.16.0 ships ``BedrockLLM`` with a working
``invoke_with_tools`` (Converse ``toolConfig``) implementation, but
``LLMEntityRelationExtractor`` never calls it: with ``use_structured_output``
it calls ``ainvoke(messages, response_format=Neo4jGraph)`` (which stock
``BedrockLLM`` rejects with "does not currently support structured output"),
otherwise it falls back to prompt-based JSON + ``fix_invalid_json()`` repair.

This module closes that gap. :class:`StructuredBedrockLLM` advertises
``supports_structured_output = True`` and, when the extractor asks for a
``response_format`` Pydantic model, turns that model's JSON schema into a
single forced Bedrock tool. Claude must answer by "calling" the tool, so
Bedrock returns arguments already shaped to the schema — no text parsing or
JSON repair. The reused helpers (``get_messages_v2``, ``_get_tool_config``,
``_build_converse_kwargs``, ``_parse_tool_response``) all come from the stock
``BedrockLLM``; the only addition is forcing ``toolChoice``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Union

from pydantic import BaseModel

from neo4j_graphrag.exceptions import LLMGenerationError
from neo4j_graphrag.llm.bedrock_llm import BedrockLLM
from neo4j_graphrag.llm.types import LLMResponse
from neo4j_graphrag.message_history import MessageHistory
from neo4j_graphrag.tool import Tool
from neo4j_graphrag.types import LLMMessage

logger = logging.getLogger(__name__)

# An empty graph is valid against Neo4jGraph; used as the fallback content so
# the extractor's on_error=IGNORE policy yields an empty chunk graph rather
# than raising when the model declines to call the tool.
_EMPTY_GRAPH_JSON = '{"nodes": [], "relationships": []}'

_TOOL_NAME = "emit_graph"
_TOOL_DESCRIPTION = (
    "Emit the entities (nodes) and relationships extracted from the input text. "
    "You must call this tool exactly once with the full result."
)

# Types accepted by the inherited invoke/ainvoke, mirroring BedrockLLM.
_Input = Union[str, list[LLMMessage]]
_History = Union[list[LLMMessage], MessageHistory, None]
_ResponseFormat = Union[type[BaseModel], dict[str, Any], None]


class _RawSchemaTool(Tool):
    """A ``Tool`` whose parameters are a verbatim JSON schema.

    The stock ``ToolParameter`` model can't represent a Pydantic
    ``model_json_schema()`` (``$defs``/``$ref`` and nested objects), so we
    bypass it and hand Bedrock the schema directly via ``get_parameters``,
    which is all ``BedrockLLM._get_tool_config`` consumes.
    """

    def __init__(
        self, name: str, description: str, json_schema: dict[str, Any]
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            execute_func=lambda **_: None,
            parameters=None,
        )
        self._json_schema = json_schema

    def get_parameters(self, exclude: list[str] | None = None) -> dict[str, Any]:
        return self._json_schema


class StructuredBedrockLLM(BedrockLLM):
    """``BedrockLLM`` that satisfies ``response_format`` via Converse tool use.

    Only the structured path (list-of-messages input with a Pydantic
    ``response_format``) is intercepted; every other call falls through to the
    stock ``BedrockLLM`` behaviour unchanged.
    """

    supports_structured_output: bool = True

    def invoke(  # type: ignore[override]
        self,
        input: _Input,
        message_history: _History = None,
        system_instruction: str | None = None,
        response_format: _ResponseFormat = None,
        **kwargs: Any,
    ) -> LLMResponse:
        if response_format is not None and not isinstance(input, str):
            return self._invoke_structured(input, response_format)
        return super().invoke(
            input,
            message_history,
            system_instruction,
            response_format=None if isinstance(input, str) else response_format,
            **kwargs,
        )

    async def ainvoke(  # type: ignore[override]
        self,
        input: _Input,
        message_history: _History = None,
        system_instruction: str | None = None,
        response_format: _ResponseFormat = None,
        **kwargs: Any,
    ) -> LLMResponse:
        if response_format is not None and not isinstance(input, str):
            return await asyncio.to_thread(
                self._invoke_structured, input, response_format
            )
        return await super().ainvoke(
            input,
            message_history,
            system_instruction,
            response_format=None if isinstance(input, str) else response_format,
            **kwargs,
        )

    def _invoke_structured(
        self, input: list[LLMMessage], response_format: _ResponseFormat
    ) -> LLMResponse:
        """Force a single tool call shaped to ``response_format``'s JSON schema.

        Not rate-limit decorated on purpose: this mirrors the stock
        ``BedrockLLM.invoke_with_tools``, which is likewise undecorated (only
        the plain ``__invoke_v1``/``__invoke_v2`` paths carry the handler).
        """
        if not isinstance(response_format, type) or not issubclass(
            response_format, BaseModel
        ):
            raise LLMGenerationError(
                "StructuredBedrockLLM requires a Pydantic model as "
                f"response_format, got {type(response_format).__name__}"
            )
        schema = response_format.model_json_schema()

        tool = _RawSchemaTool(_TOOL_NAME, _TOOL_DESCRIPTION, schema)
        system_instruction, messages = self.get_messages_v2(input)

        tool_config = self._get_tool_config([tool]) or {}
        # The stock _get_tool_config omits toolChoice, so the model is free to
        # answer with prose. Forcing the tool is what makes this reliable.
        tool_config["toolChoice"] = {"tool": {"name": _TOOL_NAME}}

        converse_kwargs = self._build_converse_kwargs(
            messages,
            system_instruction=system_instruction,
            toolConfig=tool_config,
        )

        try:
            response = self.client.converse(**converse_kwargs)
        except Exception as e:
            # Mirrors BedrockLLM: boto3/botocore raise a wide range of
            # exceptions; re-raise as the library's typed error, chained.
            raise LLMGenerationError(
                f"Error calling StructuredBedrockLLM: {e}"
            ) from e

        tool_response = self._parse_tool_response(response)
        if not tool_response.tool_calls:
            # Forced toolChoice should make this unreachable; if it happens
            # (model/region quirk) fall back to an empty graph so a single
            # chunk doesn't abort the run, but make it visible.
            logger.warning(
                "StructuredBedrockLLM: model returned no tool call despite "
                "forced toolChoice; yielding an empty graph for this chunk."
            )
            return LLMResponse(content=_EMPTY_GRAPH_JSON)

        arguments = tool_response.tool_calls[0].arguments
        return LLMResponse(content=json.dumps(arguments))
