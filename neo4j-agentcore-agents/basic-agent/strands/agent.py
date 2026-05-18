#!/usr/bin/env python3
"""Neo4j MCP Agent (Strands) — AgentCore Runtime.

A Strands-native agent over the Neo4j MCP server via AgentCore Gateway. This
is written the Strands way, not a port of the LangGraph variant:

- The Bedrock model and the MCP client are built once at module load.
- The MCP transport factory resolves a *fresh* OAuth2 token on every context
  entry, so a long-running runtime never serves an expired Bearer token.
- The schema is fetched once and cached (shared ``common.schema``) and is
  injected into the system prompt at ``Agent`` construction.
- Each request opens its own ``with mcp_client:`` scope and streams the
  answer with ``stream_async``.

Local testing:
    ./agent.sh start
    curl -X POST http://localhost:8080/invocations \
        -H "Content-Type: application/json" \
        -d '{"prompt": "What is the database schema?"}'

Cloud deployment:
    ./agent.sh configure
    ./agent.sh deploy
    ./agent.sh invoke-cloud "What is the database schema?"
"""

import logging

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient

from common import (
    AWS_REGION,
    MODEL_ID,
    SYSTEM_PROMPT_TEMPLATE,
    get_active_credentials,
    get_cached_schema,
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

# Built once; reused across requests.
model = BedrockModel(
    model_id=MODEL_ID,
    region_name=AWS_REGION,
    temperature=0.0,
    streaming=True,
)


def create_transport():
    """Transport factory — invoked on every ``with mcp_client:`` entry.

    Resolving credentials here (not at module load) keeps the Bearer token
    fresh: ``get_active_credentials`` refreshes the OAuth2 token in memory
    whenever it is missing or close to expiring.
    """
    credentials = get_active_credentials()
    return streamablehttp_client(
        credentials["gateway_url"],
        headers={"Authorization": f"Bearer {credentials['access_token']}"},
    )


mcp_client = MCPClient(create_transport)


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
    """AgentCore Runtime handler — Neo4j queries via Gateway, streamed."""
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
        # Resolve credentials once for the schema fetch; the transport factory
        # reuses the same in-memory (fresh) token on context entry.
        credentials = get_active_credentials()
        gateway_url = credentials["gateway_url"]
        access_token = credentials["access_token"]

        schema = await get_cached_schema(gateway_url, access_token)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=schema)

        # Per-request MCP scope: factory runs on context entry.
        with mcp_client:
            tools = mcp_client.list_tools_sync()
            logger.info(f"Loaded {len(tools)} tools")

            agent = Agent(
                model=model,
                tools=tools,
                system_prompt=system_prompt,
            )

            async for event in agent.stream_async(prompt):
                if "data" in event:
                    yield {"type": "chunk", "data": event["data"]}

        yield {"type": "complete"}
        logger.info("Request completed successfully")

    except FileNotFoundError as e:
        logger.error(f"Credentials error: {e}")
        yield {"type": "error", "error": str(e)}
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
    logger.info(f"Starting Neo4j MCP Agent with model: {MODEL_ID}")
    app.run()
