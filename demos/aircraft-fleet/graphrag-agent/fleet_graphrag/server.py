"""Aircraft Fleet GraphRAG Agent (Strands): AgentCore Runtime.

A Strands-native agent that connects **directly to Neo4j** (no MCP server, no
AgentCore Gateway). Two ``neo4j-graphrag`` retrievers are exposed as Strands
tools:

- ``graph_query_tool``: Text2Cypher over the live schema (exact/aggregate).
- ``vector_search_tool``: semantic search over maintenance-document chunks.

The model and tools are built once at module load; the schema is fetched once
and injected into the system prompt at ``Agent`` construction. Each request
streams the answer with ``stream_async``.

Local testing:
    uv run fleet-server
    curl -X POST http://localhost:7070/invocations \
        -H "Content-Type: application/json" \
        -d '{"prompt": "How many aircraft are in the database?"}'

Cloud deployment (AgentCore CLI, see agentcore/agentcore.json):
    ./agent.sh deploy
    ./agent.sh invoke-cloud "How many aircraft are in the database?"
"""

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv

# Local runs read the shared aircraft-fleet .env next to graphrag-agent/,
# three levels above this file. The path comes from this file, so the working
# directory does not matter.
# FLEET_ENV_FILE overrides it; the tests point it at an empty file. Existing
# env vars win, so Runtime env vars are untouched. This runs before the agent
# imports because ``agent.config`` resolves settings at import time.
ENV_FILE = Path(os.environ.get("FLEET_ENV_FILE") or Path(__file__).resolve().parents[2] / ".env")
load_dotenv(ENV_FILE)

import neo4j  # noqa: E402
from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext  # noqa: E402
from neo4j_agent_memory.integrations.strands import Neo4jSessionManager  # noqa: E402
from pydantic import (  # noqa: E402
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
from strands import Agent  # noqa: E402

from fleet_graphrag.agent import (  # noqa: E402
    SYSTEM_PROMPT_TEMPLATE,
    ConfigError,
    get_graph_schema,
    graph_query,
    settings,
    vector_search,
)
from fleet_graphrag.agent.memory import memory_settings, session_manager  # noqa: E402
from fleet_graphrag.agent.model import build_bedrock_model  # noqa: E402
from fleet_graphrag.agent.neo4j_errors import (  # noqa: E402
    UNREACHABLE,
    is_transaction_timeout,
)
from fleet_graphrag.agent.secrets import (  # noqa: E402
    NEO4J_PASSWORD_SECRET_ARN,
    neo4j_password,
)
from fleet_graphrag.agent.tools import (  # noqa: E402
    MAX_TOP_K,
    MIN_TOP_K,
    graph_query_tool,
    vector_search_tool,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = BedrockAgentCoreApp()

GENERIC_ERROR = (
    "Error processing your request. Please try rephrasing your question or check the server logs."
)

INVALID_PAYLOAD = "Invalid request payload."

model = build_bedrock_model(
    settings.model_id,
    settings.aws_region,
    max_tokens=settings.max_tokens,
    effort=settings.effort,
)


class Mode(StrEnum):
    """The direct (non-agent) surfaces selectable via the ``mode`` field."""

    SCHEMA = "schema"
    GRAPH_QUERY = "graph_query"
    VECTOR_SEARCH = "vector_search"


class RequestPayload(BaseModel):
    """Validated view of the untrusted ``/invocations`` request body.

    AgentCore hands the entrypoint a raw dict. This model is the single trust
    boundary: it validates ``mode``, coerces ``top_k`` to int, and centralizes
    the prompt-field aliases. The agent path and the direct data path resolve
    their text differently, so the raw fields are kept separate and exposed
    through :attr:`agent_prompt` / :attr:`data_query`.
    """

    model_config = ConfigDict(extra="ignore")

    mode: Mode | None = None
    top_k: int = Field(default=5, ge=MIN_TOP_K, le=MAX_TOP_K)
    # A missing, null, or empty user_id is "anonymous".
    user_id: str = "anonymous"

    prompt: str | None = None
    message: str | None = None
    query: str | None = None
    input_text: str | None = Field(default=None, validation_alias="inputText")
    input_: str | None = Field(default=None, validation_alias="input")

    @property
    def agent_prompt(self) -> str | None:
        """Prompt for the full ReAct agent (prompt > message > query > input)."""
        return self.prompt or self.message or self.query or self.input_text or self.input_

    @property
    def data_query(self) -> str | None:
        """Query text for the direct data surfaces (query > prompt > message)."""
        return self.query or self.prompt or self.message

    @field_validator("user_id", mode="before")
    @classmethod
    def _default_user_id(cls, value: object) -> object:
        """Map a missing or empty ``user_id`` to ``anonymous``."""
        return value or "anonymous"


def _printable(text: str) -> str:
    """Escape control characters, so a client value cannot forge log lines."""
    return "".join(
        char if char.isprintable() else char.encode("unicode_escape").decode("ascii")
        for char in text
    )


def _invalid_fields(error: ValidationError) -> str:
    """Names of the fields that failed validation, without values or messages."""
    names = dict.fromkeys(
        ".".join(str(part) for part in detail["loc"]) or "(body)" for detail in error.errors()
    )
    return ", ".join(names)


def _invalid_details(error: ValidationError) -> str:
    """Each failed field with its error type, for the log, without the values."""
    return ", ".join(
        f"{'.'.join(str(part) for part in detail['loc']) or '(body)'} ({detail['type']})"
        for detail in error.errors()
    )


@app.entrypoint
async def invoke(
    payload: dict | None,
    context: RequestContext,
) -> AsyncGenerator[dict, None]:
    """AgentCore Runtime handler: direct Neo4j GraphRAG, streamed.

    The runtime serves four surfaces off the single ``/invocations``
    endpoint, selected by an optional ``mode`` field in the payload:

    - ``{"mode": "schema"}``: the live Neo4j schema string.
    - ``{"mode": "graph_query", "query": "..."}``: Text2Cypher directly.
    - ``{"mode": "vector_search", "query": "...", "top_k": N}``: the vector
      retriever directly.
    - no ``mode``, or ``{"prompt": "..."}``: the full ReAct agent, streamed.

    The three data modes emit one ``chunk`` then ``complete``, so the SSE
    parser in ``client.transport`` handles them with no special casing.

    The session ID comes from the AgentCore session header, which the Runtime
    sets on every request. A local call without the header gets a fresh ID.
    """
    raw = payload or {}

    try:
        req = RequestPayload.model_validate(raw)
    except ValidationError as e:
        # The full detail echoes the rejected values, which can be the prompt
        # text. Log only the field names and the error types.
        logger.warning("Invalid request payload: %s", _invalid_details(e))
        yield {
            "type": "error",
            "error": f"{INVALID_PAYLOAD} Invalid fields: {_invalid_fields(e)}",
        }
        return

    mode = req.mode
    logger.info(
        "Received request mode=%r payload keys: %s",
        mode,
        list(raw.keys()),
    )

    try:
        if mode is Mode.SCHEMA:
            # Blocking (connects + fetches schema, cached after); off-loop.
            schema = await asyncio.to_thread(get_graph_schema)
            yield {"type": "chunk", "data": schema}
            yield {"type": "complete"}
            logger.info("Schema request completed successfully")
            return

        if mode in (Mode.GRAPH_QUERY, Mode.VECTOR_SEARCH):
            query = req.data_query
            if not query:
                logger.warning("No query provided for mode=%s", mode.value)
                yield {
                    "type": "error",
                    "error": (
                        f"No query provided for mode '{mode.value}'. Include "
                        f"'query' in your request."
                    ),
                }
                return
            # The query is user text. Its length goes to INFO, the text to DEBUG.
            logger.info("%s direct call query_chars=%d", mode.value, len(query))
            logger.debug("%s query: %s", mode.value, query)
            if mode is Mode.GRAPH_QUERY:
                result = await asyncio.to_thread(graph_query, query)
            else:
                result = await asyncio.to_thread(vector_search, query, req.top_k)
            yield {"type": "chunk", "data": result}
            yield {"type": "complete"}
            logger.info("%s request completed successfully", mode.value)
            return

        prompt = req.agent_prompt

        if not prompt:
            logger.warning("No prompt provided in request")
            yield {
                "type": "error",
                "error": ("No prompt provided. Please include 'prompt' in your request."),
            }
            return

        session_id = context.session_id or f"local-{uuid.uuid4()}"
        # The prompt is user text. Its length goes to INFO, the text to DEBUG.
        logger.info(
            "Request session=%s user=%s prompt_chars=%d",
            _printable(session_id),
            _printable(req.user_id),
            len(prompt),
        )
        logger.debug("Prompt: %s", prompt)
        logger.info("Model: %s", settings.model_id)

        # First call connects to Neo4j + fetches the schema (cached after);
        # both are blocking, so keep them off the event loop.
        schema = await asyncio.to_thread(get_graph_schema)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=schema)

        # One memory manager per request, closed on every path below. The
        # build blocks, so it runs in a worker thread.
        build = asyncio.create_task(
            asyncio.to_thread(_build_agent, session_id, req.user_id, system_prompt)
        )
        try:
            # A client disconnect cancels this await, but the thread keeps
            # building. The shield keeps the build task running, so the
            # finally below can wait for it before closing the manager.
            agent, _ = await asyncio.shield(build)

            # Strands repeats ``current_tool_use`` on every input delta while
            # a tool call is being assembled; dedupe by toolUseId so each call
            # surfaces exactly once. Emitting these as ``tool`` events lets
            # the client print a labelled boundary where a retriever tool ran.
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
        finally:
            await _close_after_build(build)

        yield {"type": "complete"}
        logger.info("Request completed successfully")

    except ConfigError as e:
        # The detail names the missing setting. Keep it in the server log.
        logger.error("Configuration error: %s", e)
        yield {
            "type": "error",
            "error": "The agent is not configured. Check the server logs.",
        }
    except UNREACHABLE as e:
        logger.error("Neo4j connection error: %s", e, exc_info=True)
        yield {
            "type": "error",
            "error": (
                "Could not reach the Neo4j database. Check NEO4J_URI / "
                "credentials and that the instance is running."
            ),
        }
    except neo4j.exceptions.ClientError as e:
        if not is_transaction_timeout(e):
            logger.exception("Neo4j error")
            yield {"type": "error", "error": GENERIC_ERROR}
            return
        logger.warning("Neo4j transaction timed out: %s", e)
        yield {
            "type": "error",
            "error": "The query took too long. Try a narrower question.",
        }
    except Exception:
        logger.exception("Error processing request")
        yield {"type": "error", "error": GENERIC_ERROR}


def _build_agent(
    session_id: str, user_id: str, system_prompt: str
) -> tuple[Agent, Neo4jSessionManager]:
    """Build one request's memory manager and Agent. Runs in a worker thread.

    The manager connects and restores the session history while the Agent is
    built. If the build fails, the manager is closed here before the error is
    raised. The caller closes only a manager whose Agent was built.
    """
    memory = session_manager(session_id, user_id)
    try:
        agent = Agent(
            model=model,
            tools=[graph_query_tool, vector_search_tool],
            system_prompt=system_prompt,
            session_manager=memory,
        )
    except Exception:
        _close_memory(memory)
        raise
    return agent, memory


# Close tasks still running. The event loop keeps only weak references to
# tasks, so this set keeps each one alive until it ends.
_closing: set[asyncio.Task[None]] = set()


async def _close_after_build(
    build: asyncio.Task[tuple[Agent, Neo4jSessionManager]],
) -> None:
    """Close a request's memory manager once its build has ended.

    A client disconnect cancels the request while the build thread may still
    be running. Closing then would race the constructor, which would reconnect
    the closed manager and leak its driver and loop thread. So this waits for
    the build first. The close runs in its own task behind a shield, so a
    second cancel cannot stop it halfway.
    """
    closing = asyncio.create_task(_await_build_then_close(build))
    _closing.add(closing)
    closing.add_done_callback(_closing.discard)
    await asyncio.shield(closing)


async def _await_build_then_close(
    build: asyncio.Task[tuple[Agent, Neo4jSessionManager]],
) -> None:
    try:
        _, memory = await build
    except Exception:
        # A failed build already closed its manager in _build_agent. The
        # request path reports the error.
        return
    await asyncio.to_thread(_close_memory, memory)


def _close_memory(memory: Neo4jSessionManager) -> None:
    """Flush and close a request's memory manager. Blocks.

    A failure is logged, not raised. It runs after the answer has streamed or
    while another error is already propagating, and must not replace either.
    """
    try:
        memory.close()
    except Exception:
        logger.exception("Could not close the memory session %s", _printable(memory.session_id))


def main(default_port: int = 7070) -> None:
    """Start the server in the foreground. Stop it with Ctrl+C.

    This is the only server entry point. ``uv run fleet-server`` calls it
    with port 7070, so local runs never collide with a local service on 8080.
    AgentCore Runtime runs the root ``main.py``, which calls it with 8080.
    ``AGENT_PORT`` overrides both. For local OTEL tracing, prefix the command
    with ``opentelemetry-instrument``.
    """
    port = int(os.environ.get("AGENT_PORT", str(default_port)))
    if os.environ.get(NEO4J_PASSWORD_SECRET_ARN):
        # Read the secret before serving, so a bad ARN or a missing IAM grant
        # stops startup instead of failing the first request.
        neo4j_password()
    # Build the memory settings before serving, so a missing MEM_NEO4J_* value
    # or an unreadable memory secret stops startup.
    memory_settings()
    logger.info(
        "Starting Aircraft Fleet GraphRAG Agent with model: %s on port %s",
        settings.model_id,
        port,
    )
    app.run(port=port)
