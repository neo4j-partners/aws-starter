#!/usr/bin/env python3
"""Finance Agent deployed on Amazon Bedrock AgentCore Runtime.

The finance graph is reached through the Neo4j MCP Gateway. Each real agent
invocation is captured in the hosted Neo4j Agent Memory Service (NAMS): the
user prompt and assistant response become conversation messages, and every
MCP tool call becomes a reasoning step and tool call. NAMS needs only
``MEMORY_API_KEY`` and manages its own storage, embeddings, extraction, and
schema.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from dotenv import load_dotenv
from neo4j_agent_memory import MemoryClient
from strands import Agent

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

from core import MODEL_ID, SYSTEM_PROMPT  # noqa: E402
from core.factory import build_mcp_client, build_model  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = BedrockAgentCoreApp()
model = build_model()
_SCOPE_ID_RE = re.compile(r"[^A-Za-z0-9._:@-]")


def _safe_scope_id(value: object) -> str | None:
    """Return a conservative identifier safe to place in logs and metadata."""
    if value is None:
        return None
    cleaned = _SCOPE_ID_RE.sub("", str(value).strip())[:128]
    return cleaned or None


def _require_nams_api_key() -> None:
    if not os.environ.get("MEMORY_API_KEY", "").strip():
        raise ValueError(
            "NAMS memory is required. Set MEMORY_API_KEY in finance-agent/.env "
            "for local runs or inject it during AgentCore deployment."
        )


def _resolve_user_id(payload: dict) -> str:
    for key in ("user_id", "actor_id", "session_id"):
        if scope := _safe_scope_id(payload.get(key)):
            return scope
    return "anonymous"


def _resolve_session_id(payload: dict, user_id: str) -> str:
    """Return a client-visible correlation ID for this captured turn."""
    return _safe_scope_id(payload.get("session_id")) or f"finance-{user_id}"


def _memory_system_prompt(user_id: str, session_id: str) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "This invocation is recorded in Neo4j Agent Memory Service (NAMS) "
        "for audit and analysis. Current user_id="
        f"{user_id}; client session_id={session_id}."
    )


@app.entrypoint
async def invoke(payload: dict | None = None) -> AsyncIterator[dict]:
    """Process a finance query and capture its messages and tool use in NAMS."""
    payload = payload or {}
    prompt = (
        payload.get("prompt")
        or payload.get("message")
        or payload.get("query")
        or payload.get("input")
    )
    if not prompt:
        yield {
            "type": "error",
            "error": "No prompt provided. Include 'prompt' in your request.",
        }
        return

    user_id = _resolve_user_id(payload)
    session_id = _resolve_session_id(payload, user_id)
    prompt_text = str(prompt)
    logger.info("Query: %s...", prompt_text[:100])
    logger.info("Model: %s | NAMS user=%s session=%s", MODEL_ID, user_id, session_id)

    try:
        _require_nams_api_key()
        async with MemoryClient() as memory:
            # NAMS returns its own conversation UUID. Keep the caller's session
            # ID as metadata for grouping and filtering in the NAMS workspace.
            conversation = await memory.short_term.create_conversation(
                session_id,
                user_identifier=user_id,
                metadata={"client_session_id": session_id, "source": "finance-agent"},
            )
            conversation_id = str(conversation.id)
            await memory.short_term.add_message(conversation_id, "user", prompt_text)
            trace = await memory.reasoning.start_trace(
                conversation_id, "Finance Agent investigation"
            )

            answer_parts: list[str] = []
            mcp_client = build_mcp_client()
            with mcp_client:
                agent = Agent(
                    model=model,
                    tools=mcp_client.list_tools_sync(),
                    system_prompt=_memory_system_prompt(user_id, session_id),
                )
                last_tool_id: str | None = None
                async for event in agent.stream_async(prompt_text):
                    if "data" in event:
                        chunk = event["data"]
                        answer_parts.append(chunk)
                        yield {"type": "chunk", "data": chunk}
                    elif tool_use := event.get("current_tool_use"):
                        tool_id = tool_use.get("toolUseId")
                        name = tool_use.get("name")
                        if name and tool_id != last_tool_id:
                            last_tool_id = tool_id
                            step = await memory.reasoning.add_step(
                                trace.id,
                                thought=f"The agent invoked MCP tool {name}.",
                                action=name,
                            )
                            await memory.reasoning.record_tool_call(
                                step.id,
                                tool_name=name,
                                arguments=tool_use.get("input") or {},
                            )
                            yield {"type": "tool", "name": name}

            answer = "".join(answer_parts)
            await memory.short_term.add_message(conversation_id, "assistant", answer)
            await memory.reasoning.complete_trace(
                trace.id, outcome=answer[:1000], success=True
            )

        yield {"type": "complete"}
    except FileNotFoundError as error:
        logger.error("Credentials error: %s", error)
        yield {"type": "error", "error": str(error)}
    except Exception as error:  # noqa: BLE001 - sends a useful runtime error
        logger.error("Invocation failed", exc_info=True)
        yield {"type": "error", "error": f"Error processing request: {error}"}


def main() -> None:
    """Run the local server on port 7020 unless PORT is supplied."""
    app.run(port=int(os.environ.get("PORT", "7020")))


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", "8080")))
