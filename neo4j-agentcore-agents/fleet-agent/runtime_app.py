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
    ./agent.sh strands start
    curl -X POST http://localhost:8080/invocations \
        -H "Content-Type: application/json" \
        -d '{"prompt": "How many aircraft are in the database?"}'

Cloud deployment:
    ./agent.sh strands configure
    ./agent.sh strands deploy
    ./agent.sh strands invoke-cloud "How many aircraft are in the database?"
"""

import asyncio
import logging

import neo4j
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from tools import graph_query_tool, vector_search_tool

from common import AWS_REGION, MODEL_ID, SYSTEM_PROMPT_TEMPLATE, get_graph_schema

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
    model_id=MODEL_ID,
    region_name=AWS_REGION,
    temperature=0.0,
    streaming=True,
)


def extract_prompt_from_payload(
    payload: dict,
) -> tuple[str | None, str, str]:
    """Extract prompt + context from payload, supporting multiple fields.

    Returns ``(prompt, session_id, user_id)``.
    """
    prompt = (
        payload.get("prompt")
        or payload.get("message")
        or payload.get("query")
        or payload.get("inputText")
        or payload.get("input")
    )
    session_id = payload.get("session_id", "default_session")
    user_id = payload.get("user_id", "default_user")
    return prompt, session_id, user_id


@app.entrypoint
async def invoke(payload: dict | None = None):
    """AgentCore Runtime handler — direct Neo4j GraphRAG, streamed."""
    logger.info(
        f"Received request with payload keys: "
        f"{list(payload.keys()) if payload else []}"
    )

    if payload is None:
        payload = {}

    prompt, session_id, user_id = extract_prompt_from_payload(payload)

    if not prompt:
        logger.warning("No prompt provided in request")
        yield {
            "type": "error",
            "error": "No prompt provided. Please include 'prompt' in your request.",
        }
        return

    logger.info(
        f"Processing query for user {user_id}, session {session_id}: "
        f"{prompt[:100]}..."
    )
    logger.info(f"Model: {MODEL_ID}")

    try:
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
        logger.error(f"Configuration error: {e}")
        yield {"type": "error", "error": str(e)}
    except (neo4j.exceptions.Neo4jError, neo4j.exceptions.DriverError) as e:
        logger.error(f"Neo4j error: {e}", exc_info=True)
        yield {
            "type": "error",
            "error": (
                "Could not reach the Neo4j database. Check NEO4J_URI / "
                "credentials and that the instance is running."
            ),
        }
    except Exception as e:
        logger.error(f"Error processing request: {e}", exc_info=True)
        yield {
            "type": "error",
            "error": (
                f"Error processing your request: {str(e)}\n\n"
                "Please try rephrasing your question or check the logs."
            ),
        }


if __name__ == "__main__":
    logger.info(f"Starting Neo4j Fleet Agent with model: {MODEL_ID}")
    app.run()
