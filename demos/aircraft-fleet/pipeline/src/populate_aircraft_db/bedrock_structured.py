"""Structured-output BedrockLLM via Converse tool use.

``neo4j-graphrag`` 1.24 ships ``BedrockLLM`` with a working
``invoke_with_tools`` (Converse ``toolConfig``) implementation, but
``LLMEntityRelationExtractor`` never calls it. With ``use_structured_output``
it calls ``ainvoke(messages, response_format=Neo4jGraph)``, which stock
``BedrockLLM`` rejects with "does not currently support structured output".
Otherwise it falls back to prompt-based JSON and ``fix_invalid_json()`` repair.

This module closes that gap. :class:`StructuredBedrockLLM` advertises
``supports_structured_output = True``. When the extractor asks for a
``response_format`` Pydantic model, it turns that model's JSON schema into a
single Bedrock tool and tells Claude to answer by calling it. Bedrock then
returns arguments already shaped to the schema, with no text parsing or JSON
repair.

Claude Sonnet 5.5 rejects a forced ``toolChoice`` (``tool`` or ``any``), so
the tool is offered with ``auto`` and the system prompt instructs the model to
call it. Under ``auto`` the model can still answer in prose, so a reply with
no tool call is retried once. Tool arguments are validated against the
``response_format`` model the same way the extractor validates them, and
arguments that fail are also retried once. A reply that still has no valid
tool call, or one cut off at ``max_tokens``, is counted as a miss and returned
as content that fails ``Neo4jGraph`` validation. The extractor's ``OnError``
policy then decides: ``RAISE`` raises and ``IGNORE`` logs the chunk and yields an empty graph.
Raising here instead would bypass ``OnError``, because the extractor calls the
LLM outside its validation ``try``.

The reused helpers (``get_messages_v2``, ``_get_tool_config``,
``_build_converse_kwargs``, ``_parse_tool_response``) all come from the stock
``BedrockLLM``. This class also forwards ``additional_request_fields`` as the
Converse ``additionalModelRequestFields``, which carries the thinking and
effort settings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Union

from neo4j_graphrag.exceptions import LLMGenerationError
from neo4j_graphrag.llm.bedrock_llm import BedrockLLM
from neo4j_graphrag.llm.types import LLMResponse
from neo4j_graphrag.message_history import MessageHistory
from neo4j_graphrag.tool import Tool
from neo4j_graphrag.types import LLMMessage
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# One call plus one retry when the reply has no valid emit_graph tool call.
_MAX_ATTEMPTS = 2
# Prefix for miss content. It is never valid JSON, so the extractor's
# Neo4jGraph validation fails and its OnError policy applies.
_MISS_PREFIX = "StructuredBedrockLLM miss"

_TOOL_NAME = "emit_graph"
_TOOL_DESCRIPTION = (
    "Emit the entities (nodes) and relationships extracted from the input text. "
    "You must call this tool exactly once with the full result."
)
# Appended to the system instruction. With toolChoice "auto" the prompt is
# what makes the model call the tool instead of answering in prose.
_TOOL_INSTRUCTION = (
    f"Return your answer by calling the {_TOOL_NAME} tool exactly once with "
    "the full result. Do not answer with text."
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

    def __init__(self, name: str, description: str, json_schema: dict[str, Any]) -> None:
        super().__init__(
            name=name,
            description=description,
            execute_func=lambda **_: None,
            parameters=None,
        )
        self._json_schema = json_schema

    def get_parameters(self, exclude: list[str] | None = None) -> dict[str, Any]:
        return self._json_schema


def _first_error(error: ValidationError) -> str:
    """Return the first validation error as "<location>: <message>"."""
    first = error.errors()[0]
    location = ".".join(str(part) for part in first["loc"]) or "<root>"
    return f"{location}: {first['msg']}"


class StructuredBedrockLLM(BedrockLLM):
    """``BedrockLLM`` that satisfies ``response_format`` via Converse tool use.

    Only the structured path (list-of-messages input with a Pydantic
    ``response_format``) is intercepted; every other call falls through to the
    stock ``BedrockLLM`` behaviour unchanged.
    """

    supports_structured_output: bool = True

    def __init__(
        self,
        *args: Any,
        additional_request_fields: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.additional_request_fields = additional_request_fields or {}
        # Chunks run concurrently through asyncio.to_thread, so guard the count.
        self.miss_count = 0
        self._miss_lock = threading.Lock()

    def _build_converse_kwargs(
        self,
        messages: list[dict[str, Any]],
        system_instruction: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Add ``additionalModelRequestFields`` to every Converse call."""
        kwargs = super()._build_converse_kwargs(
            messages, system_instruction=system_instruction, **extra
        )
        if self.additional_request_fields:
            kwargs["additionalModelRequestFields"] = self.additional_request_fields
        return kwargs

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
            return await asyncio.to_thread(self._invoke_structured, input, response_format)
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
        """Request a single tool call shaped to ``response_format``'s JSON schema.

        Not rate-limit decorated on purpose: this mirrors the stock
        ``BedrockLLM.invoke_with_tools``, which is likewise undecorated (only
        the plain ``__invoke_v1``/``__invoke_v2`` paths carry the handler).
        """
        if not isinstance(response_format, type) or not issubclass(response_format, BaseModel):
            raise LLMGenerationError(
                "StructuredBedrockLLM requires a Pydantic model as "
                f"response_format, got {type(response_format).__name__}"
            )
        schema = response_format.model_json_schema()

        tool = _RawSchemaTool(_TOOL_NAME, _TOOL_DESCRIPTION, schema)
        system_instruction, messages = self.get_messages_v2(input)
        system_instruction = (
            f"{system_instruction}\n\n{_TOOL_INSTRUCTION}"
            if system_instruction
            else _TOOL_INSTRUCTION
        )

        tool_config = self._get_tool_config([tool]) or {}
        # Sonnet 5.5 returns a 400 for a forced toolChoice ("tool" or "any").
        # "auto" plus _TOOL_INSTRUCTION is the supported way to get the call.
        tool_config["toolChoice"] = {"auto": {}}

        converse_kwargs = self._build_converse_kwargs(
            messages,
            system_instruction=system_instruction,
            toolConfig=tool_config,
        )

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            response = self._converse(converse_kwargs)
            if response.get("stopReason") == "max_tokens":
                # A truncated tool input is not a complete graph. Retrying with
                # the same max_tokens would likely truncate again.
                return self._miss("response stopped at max_tokens", response)
            tool_call = next(
                (
                    call
                    for call in self._parse_tool_response(response).tool_calls
                    if call.name == _TOOL_NAME
                ),
                None,
            )
            if tool_call is None:
                reason = f"no {_TOOL_NAME} tool call"
            else:
                content = json.dumps(tool_call.arguments)
                # model_validate_json is the check the extractor runs on this
                # content, so a reply that passes here passes there.
                try:
                    response_format.model_validate_json(content)
                except ValidationError as e:
                    reason = (
                        f"{_TOOL_NAME} arguments failed {response_format.__name__} "
                        f"validation ({e.error_count()} errors, first: {_first_error(e)})"
                    )
                else:
                    return LLMResponse(content=content)
            if attempt < _MAX_ATTEMPTS:
                logger.info("StructuredBedrockLLM: %s; retrying.", reason)
        return self._miss(f"{reason} after {_MAX_ATTEMPTS} attempts", response)

    def _converse(self, converse_kwargs: dict[str, Any]) -> dict[str, Any]:
        """Call Converse and wrap client errors in ``LLMGenerationError``."""
        try:
            return self.client.converse(**converse_kwargs)
        except Exception as e:
            # Mirrors BedrockLLM: boto3/botocore raise a wide range of
            # exceptions; re-raise as the library's typed error, chained.
            raise LLMGenerationError(f"Error calling StructuredBedrockLLM: {e}") from e

    def _miss(self, reason: str, response: dict[str, Any]) -> LLMResponse:
        """Count and log a miss, and return content that fails validation."""
        with self._miss_lock:
            self.miss_count += 1
            count = self.miss_count
        logger.warning("StructuredBedrockLLM: %s (miss %d this run).", reason, count)
        content = response.get("output", {}).get("message", {}).get("content", [])
        text = " ".join(block["text"] for block in content if "text" in block)
        return LLMResponse(content=f"{_MISS_PREFIX} ({reason}): {text}")
