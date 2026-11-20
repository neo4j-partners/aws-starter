#!/usr/bin/env python3
"""Aircraft Fleet GraphRAG Agent (Strands) — AgentCore Runtime.

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

Cloud deployment:
    ./agent.sh configure
    ./agent.sh deploy
    ./agent.sh invoke-cloud "How many aircraft are in the database?"
"""

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from enum import StrEnum

from dotenv import find_dotenv, load_dotenv

# Local runs read the shared aircraft-fleet .env, found by walking up from the
# working directory. Existing env vars win, so Runtime env vars are untouched.
# This runs before the agent imports because ``agent.config`` resolves
# settings at import time.
load_dotenv(find_dotenv(usecwd=True))

import neo4j  # noqa: E402
from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field, ValidationError  # noqa: E402
from strands import Agent  # noqa: E402

from agent import (  # noqa: E402
    SYSTEM_PROMPT_TEMPLATE,
    get_graph_schema,
    graph_query,
    settings,
    vector_search,
)
from agent.model import build_bedrock_model  # noqa: E402
from agent.tools import graph_query_tool, vector_search_tool  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = BedrockAgentCoreApp()

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
    top_k: int = 5
    user_id: str | None = None

    prompt: str | None = None
    message: str | None = None
    query: str | None = None
    input_text: str | None = Field(default=None, validation_alias="inputText")
    input_: str | None = Field(default=None, validation_alias="input")

    @property
    def agent_prompt(self) -> str | None:
        """Prompt for the full ReAct agent (prompt > message > query > input)."""
        return (
            self.prompt
            or self.message
            or self.query
            or self.input_text
            or self.input_
        )

    @property
    def data_query(self) -> str | None:
        """Query text for the direct data surfaces (query > prompt > message)."""
        return self.query or self.prompt or self.message


@app.entrypoint
async def invoke(
    payload: dict | None,
    context: RequestContext,
) -> AsyncGenerator[dict, None]:
    """AgentCore Runtime handler — direct Neo4j GraphRAG, streamed.

    The runtime serves four surfaces off the single ``/invocations``
    endpoint, selected by an optional ``mode`` field in the payload:

    - ``{"mode": "schema"}`` — the live Neo4j schema string.
    - ``{"mode": "graph_query", "query": "..."}`` — Text2Cypher directly.
    - ``{"mode": "vector_search", "query": "...", "top_k": N}`` — the vector
      retriever directly.
    - no ``mode`` (or ``{"prompt": "..."}``) — the full ReAct agent, streamed.

    The three data modes emit one ``chunk`` then ``complete``, so the SSE
    parser in ``client.transport`` handles them with no special casing.

    The session ID comes from the AgentCore session header, which the Runtime
    sets on every request. A local call without the header gets a fresh ID.
    """
    raw = payload or {}

    try:
        req = RequestPayload.model_validate(raw)
    except ValidationError as e:
        logger.warning("Invalid request payload: %s", e)
        yield {
            "type": "error",
            "error": f"Invalid request payload: {e}",
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
            logger.info("%s direct call: %s...", mode.value, query[:100])
            if mode is Mode.GRAPH_QUERY:
                result = await asyncio.to_thread(graph_query, query)
            else:
                result = await asyncio.to_thread(
                    vector_search, query, req.top_k
                )
            yield {"type": "chunk", "data": result}
            yield {"type": "complete"}
            logger.info("%s request completed successfully", mode.value)
            return

        prompt = req.agent_prompt

        if not prompt:
            logger.warning("No prompt provided in request")
            yield {
                "type": "error",
                "error": (
                    "No prompt provided. Please include 'prompt' in your "
                    "request."
                ),
            }
            return

        session_id = context.session_id or f"local-{uuid.uuid4()}"
        logger.info(
            "Processing query for user %s, session %s: %s...",
            req.user_id,
            session_id,
            prompt[:100],
        )
        logger.info("Model: %s", settings.model_id)

        # First call connects to Neo4j + fetches the schema (cached after);
        # both are blocking, so keep them off the event loop.
        schema = await asyncio.to_thread(get_graph_schema)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=schema)

        agent = Agent(
            model=model,
            tools=[graph_query_tool, vector_search_tool],
            system_prompt=system_prompt,
        )

        # Strands repeats ``current_tool_use`` on every input delta while a
        # tool call is being assembled; dedupe by toolUseId so each call
        # surfaces exactly once. Emitting these as ``tool`` events lets the
        # client print a labelled boundary where a retriever tool ran.
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

    except RuntimeError as e:
        logger.error("Configuration error: %s", e)
        yield {"type": "error", "error": str(e)}
    except (neo4j.exceptions.Neo4jError, neo4j.exceptions.DriverError) as e:
        logger.error("Neo4j error: %s", e, exc_info=True)
        yield {
            "type": "error",
            "error": (
                "Could not reach the Neo4j database. Check NEO4J_URI / "
                "credentials and that the instance is running."
            ),
        }
    except Exception:
        logger.exception("Error processing request")
        yield {
            "type": "error",
            "error": (
                "Error processing your request. Please try rephrasing your "
                "question or check the server logs."
            ),
        }


def main(default_port: int = 7070) -> None:
    """Start the server in the foreground. Stop it with Ctrl+C.

    ``uv run fleet-server`` calls this with port 7070, so local runs never
    collide with a local service on 8080. The deployed Runtime runs this file
    as a script and must serve 8080. ``AGENT_PORT`` overrides both. For local
    OTEL tracing, prefix the command with ``opentelemetry-instrument``.
    """
    port = int(os.environ.get("AGENT_PORT", str(default_port)))
    logger.info(
        "Starting Aircraft Fleet GraphRAG Agent with model: %s on port %s",
        settings.model_id,
        port,
    )
    app.run(port=port)


if __name__ == "__main__":
    main(default_port=8080)
