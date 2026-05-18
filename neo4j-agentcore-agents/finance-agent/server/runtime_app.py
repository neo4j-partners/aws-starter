#!/usr/bin/env python3
"""Finance Agent — AgentCore Runtime deployment.

A Strands-native financial-analysis agent over the Neo4j MCP server via
AgentCore Gateway, written the Strands way:

- The Bedrock model is built once at module load (stateless per call, safe
  to share across concurrent requests).
- Each request builds its *own* MCP client and opens its own
  ``with mcp_client:`` scope, so concurrent requests never contend on a
  shared session. The MCP transport factory resolves a *fresh* OAuth2 token
  on every context entry (via ``core.transport``), so a long-running runtime
  never serves requests with an expired Bearer token.
- Each request lists tools, builds an ``Agent``, and streams the answer with
  ``stream_async``.

Context Graph semantic memory:

- ``user_scoped_context_graph_tools`` (core.memory) adds four Strands
  tools (search_context, get_entity_graph, add_memory, get_user_preferences)
  backed by the *same* Neo4j instance as the finance graph, connected
  directly (driver + Bedrock embeddings), not through the MCP Gateway.
- Memory is genuinely isolated per ``user_id``: writes link a ``:User``
  node and reads filter to it, so recall spans that user's sessions but
  never crosses tenants. (The stock ``neo4j_agent_memory`` 0.2.1 Strands
  tools accept ``user_id`` but ignore it — see core/memory.py.) The
  ``user_id`` is resolved from the invoke payload and injected into the
  per-request system prompt so the model passes the right scope.
- Memory is a core capability, not an enhancement. The direct Neo4j env
  vars (``NEO4J_URI``, ``NEO4J_PASSWORD``) are required: if they are absent
  the agent aborts at startup rather than degrading to MCP-only.

Local testing:
    uv run finance-server
    curl -X POST http://localhost:7020/invocations \
        -H "Content-Type: application/json" \
        -d '{"prompt": "Which accounts have the highest risk scores, and who do they transfer money to?"}'

Cloud deployment:
    ./agent.sh configure
    ./agent.sh deploy
    ./agent.sh invoke-cloud "Which accounts have the highest risk scores, and who do they transfer money to?"
"""

import logging
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from dotenv import load_dotenv
from strands import Agent

# Local dev: load finance-agent/.env BEFORE the first-party imports below.
# ``core.config`` reads MODEL_ID/AWS_REGION from os.environ at import time,
# and ``core.memory`` reads NEO4J_URI/NEO4J_PASSWORD when ``memory_tools`` is
# built at module load. Loading .env here means a local .env can override all
# of them. ``override=False`` keeps any real environment variable winning,
# matching how the cloud path injects these via ``agentcore deploy --env``
# (no .env ships in the container, so this is a no-op there).
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

from core import AWS_REGION, MODEL_ID, SYSTEM_PROMPT  # noqa: E402
from core.factory import build_mcp_client, build_model  # noqa: E402
from core.memory import user_scoped_context_graph_tools  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
# The neo4j-agent-memory Strands tools catch their own exceptions and log
# them at DEBUG ("Message search failed: ...", "Preference search failed:
# ..."), returning only a generic string to the model. Surface those at
# DEBUG so the real failure reaches CloudWatch instead of being silently
# dropped by the INFO root level above.
logging.getLogger("neo4j_agent_memory").setLevel(logging.DEBUG)

app = BedrockAgentCoreApp()

# Built once; reused across requests. The Bedrock model is stateless per
# call, so sharing it across concurrent requests is safe. The MCP client is
# deliberately NOT shared — it holds a single session and is built per
# request in ``invoke`` so concurrent requests do not collide.
model = build_model()


def _build_memory_tools() -> list:
    """Build the user-scoped Context Graph memory tools.

    Memory is a core capability of this agent, not an enhancement: the agent
    must not run without it. ``user_scoped_context_graph_tools`` reads
    ``NEO4J_URI``/``NEO4J_PASSWORD`` from the environment (the same
    direct-connection vars the MCP server uses) and raises ``ValueError``
    when they are missing. That is fatal here — the error is logged and
    re-raised so it propagates out of module import and aborts startup,
    rather than degrading to MCP-only.
    """
    try:
        tools = user_scoped_context_graph_tools(
            embedding_provider="bedrock",
            aws_region=AWS_REGION,
        )
    except ValueError:
        logger.error(
            "Context Graph memory is required but could not be initialized. "
            "Set NEO4J_URI and NEO4J_PASSWORD (locally in finance-agent/.env, "
            "in the cloud via './agent.sh deploy', which injects them).",
        )
        raise
    logger.info("User-scoped Context Graph memory enabled (%d tools)", len(tools))
    return tools


# Built once; reused across requests.
memory_tools = _build_memory_tools()


# Memory scope ids reach a tenant-isolation boundary via the system prompt;
# keep them to a conservative identifier charset.
_SCOPE_ID_RE = re.compile(r"[^A-Za-z0-9._:@-]")


def _safe_scope_id(value: object) -> str | None:
    """Normalize a payload-supplied memory scope id, or ``None`` if empty.

    ``user_id``/``session_id`` come from the client-controlled invoke payload
    and are interpolated into the system prompt, where they steer the memory
    tools' scope. Stripping everything outside a conservative identifier
    charset blocks quote/newline breakout and prompt injection, and keeps
    scoping deterministic.
    """
    if value is None:
        return None
    cleaned = _SCOPE_ID_RE.sub("", str(value).strip())[:128]
    return cleaned or None


def _resolve_user_id(payload: dict) -> str:
    """Resolve the memory scope for this request from the invoke payload."""
    for key in ("user_id", "actor_id", "session_id"):
        if scope := _safe_scope_id(payload.get(key)):
            return scope
    return "anonymous"


def _memory_system_prompt(user_id: str, session_id: str | None) -> str:
    """Extend the shared prompt with memory directives bound to this scope.

    The memory tools take ``user_id``/``session_id`` as arguments the model
    fills in, so the resolved scope is stated here rather than relying on the
    model to invent it. Built per request; the shared ``SYSTEM_PROMPT`` is
    left untouched. ``memory_tools`` is always non-empty (startup aborts
    otherwise), so the prompt always carries the memory directives.
    """
    session_clause = f' and session_id="{session_id}"' if session_id else ""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "You also have a Context Graph semantic memory. Before answering, "
        "call search_context to recall anything relevant from past "
        "conversations. After learning a durable fact about the user or "
        "their portfolio, call add_memory to persist it. Always pass "
        f'user_id="{user_id}"{session_clause} to every memory tool.'
    )


@app.entrypoint
async def invoke(payload: dict | None = None) -> AsyncIterator[dict]:
    """AgentCore Runtime handler — processes financial queries via Neo4j MCP."""
    if payload is None:
        payload = {}

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
    session_id = _safe_scope_id(payload.get("session_id"))

    logger.info("Query: %s...", prompt[:100])
    logger.info("Model: %s", MODEL_ID)
    logger.info("Memory scope: user_id=%s session_id=%s", user_id, session_id)

    try:
        # Per-request MCP client: an MCPClient holds a single session, so a
        # shared one would raise "the client session is currently running"
        # under concurrent invokes. Constructing one is cheap (just wraps the
        # transport factory); the session and a freshly resolved OAuth2 token
        # are established on context entry below.
        mcp_client = build_mcp_client()
        with mcp_client:
            tools = mcp_client.list_tools_sync() + memory_tools
            logger.info("Loaded %d tools", len(tools))

            agent = Agent(
                model=model,
                tools=tools,
                system_prompt=_memory_system_prompt(user_id, session_id),
            )

            # Strands repeats ``current_tool_use`` on every input delta while
            # a tool call is being assembled; dedupe by toolUseId so each tool
            # call surfaces exactly once. Emitting these as ``tool`` events is
            # what keeps the streamed narration from running together: the
            # client prints a labelled boundary where a tool call happened.
            last_tool_id: str | None = None
            async for event in agent.stream_async(prompt):
                if "data" in event:
                    yield {"type": "chunk", "data": event["data"]}
                elif tool_use := event.get("current_tool_use"):
                    tool_id = tool_use.get("toolUseId")
                    name = tool_use.get("name")
                    if name and tool_id != last_tool_id:
                        last_tool_id = tool_id
                        yield {"type": "tool", "name": name}

        yield {"type": "complete"}
        logger.info("Request completed successfully")

    except FileNotFoundError as e:
        logger.error("Credentials error: %s", e)
        yield {"type": "error", "error": str(e)}
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        yield {"type": "error", "error": f"Error processing request: {e}"}


def main() -> None:
    """Local dev entry point: ``uv run finance-server``.

    Runs the server in the foreground; stop with Ctrl+C. Defaults to port
    7020 for local use so it never collides with the cloud contract; an
    explicit ``PORT`` still wins. The cloud container never calls this. it
    uses the ``__main__`` block below.
    """
    app.run(port=int(os.environ.get("PORT", "7020")))


if __name__ == "__main__":
    # AgentCore Runtime always invokes the deployed container on 8080
    # (the platform's fixed /invocations contract), so 8080 is the default
    # for the container path. Local dev uses ``main`` (finance-server, 7020).
    app.run(port=int(os.environ.get("PORT", "8080")))
