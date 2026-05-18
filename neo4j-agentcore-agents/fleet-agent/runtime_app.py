#!/usr/bin/env python3
"""Neo4j Fleet Agent (Strands) — AgentCore Runtime.

A Strands-native agent that connects **directly to Neo4j** (no MCP server, no
AgentCore Gateway). Two ``neo4j-graphrag`` retrievers are exposed as Strands
tools:

- ``graph_query``   — Text2Cypher over the live schema (exact/aggregate).
- ``vector_search`` — semantic search over maintenance-document chunks.

The model and tools are built once at module load; the schema is fetched once
and injected into the system prompt at ``Agent`` construction. Each request
streams the answer with ``stream_async``.

Local testing:
    ./agent.sh start
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
from collections.abc import AsyncGenerator
from enum import Enum

import neo4j
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from strands import Agent
from strands.models import BedrockModel

from agent import (
    SYSTEM_PROMPT_TEMPLATE,
    get_graph_schema,
    graph_query,
    settings,
    vector_search,
)
from agent.tools import graph_query_tool, vector_search_tool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = BedrockAgentCoreApp()

model = BedrockModel(
    model_id=settings.model_id,
    region_name=settings.aws_region,
    temperature=0.0,
    streaming=True,
)


class Mode(str, Enum):
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
    session_id: str = "default_session"
    user_id: str = "default_user"

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
    payload: dict | None = None,
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

        logger.info(
            "Processing query for user %s, session %s: %s...",
            req.user_id,
            req.session_id,
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

        async for event in agent.stream_async(prompt):
            if "data" in event:
                yield {"type": "chunk", "data": event["data"]}

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
    except Exception as e:
        logger.error("Error processing request: %s", e, exc_info=True)
        yield {
            "type": "error",
            "error": (
                f"Error processing your request: {str(e)}\n\n"
                "Please try rephrasing your question or check the logs."
            ),
        }


if __name__ == "__main__":
    # AgentCore Runtime requires the deployed container to serve 8080, so
    # that is the default. Local runs override via AGENT_PORT (./agent.sh
    # start sets 7070) to avoid colliding with a local service on 8080.
    port = int(os.environ.get("AGENT_PORT", "8080"))
    logger.info(
        "Starting Neo4j Fleet Agent with model: %s on port %s",
        settings.model_id,
        port,
    )
    app.run(port=port)
