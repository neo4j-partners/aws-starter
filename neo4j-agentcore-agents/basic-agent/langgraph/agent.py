#!/usr/bin/env python3
"""Neo4j MCP Agent (LangGraph) — AgentCore Runtime.

A ReAct agent that connects to the Neo4j MCP server via AgentCore Gateway and
answers natural language questions about the database. The schema is fetched
once and cached; the OAuth2 token is auto-refreshed. The model response is
accumulated and returned as a single chunk (the Strands variant streams).

This is the decomposition of the former ``aircraft-agent.py`` monolith —
behavior is unchanged, the credential / token / schema logic now lives in the
shared ``common`` package.

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

import httpx
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient

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


def get_llm(region: str = AWS_REGION):
    """Get the LLM (AWS Bedrock Claude via Converse API)."""
    import boto3

    bedrock_client = boto3.client("bedrock-runtime", region_name=region)
    return init_chat_model(
        client=bedrock_client,
        model=MODEL_ID,
        model_provider="bedrock_converse",
        temperature=0,
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

    try:
        logger.info("Loading credentials...")
        credentials = get_active_credentials()

        gateway_url = credentials["gateway_url"]
        access_token = credentials["access_token"]
        region = credentials.get("region", AWS_REGION)

        logger.info(f"Gateway: {gateway_url}")
        logger.info(f"Model: {MODEL_ID}")

        # Schema is fetched once on the first request and cached.
        schema = await get_cached_schema(gateway_url, access_token)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=schema)

        llm = get_llm(region)

        logger.info("Connecting to MCP server...")
        mcp_client = MultiServerMCPClient(
            {
                "neo4j": {
                    "transport": "streamable_http",
                    "url": gateway_url,
                    "headers": {"Authorization": f"Bearer {access_token}"},
                }
            }
        )

        tools = await mcp_client.get_tools()
        logger.info(f"Loaded {len(tools)} tools: {[t.name for t in tools]}")

        agent = create_agent(llm, tools, system_prompt=system_prompt)

        logger.info("Running agent...")
        response_text = ""
        async for message_chunk, metadata in agent.astream(
            {"messages": [("human", prompt)]}, stream_mode="messages"
        ):
            if message_chunk.content:
                for content in message_chunk.content:
                    if isinstance(content, dict) and "text" in content:
                        response_text += content["text"]
                    elif isinstance(content, str):
                        response_text += content

        if not response_text:
            response_text = "No response from agent"

        yield {"type": "chunk", "data": response_text}
        yield {"type": "complete"}

        logger.info("Request completed successfully")

    except FileNotFoundError as e:
        logger.error(f"Credentials error: {e}")
        yield {"type": "error", "error": str(e)}
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
        yield {
            "type": "error",
            "error": f"HTTP error {e.response.status_code}: {e.response.text}",
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
    logger.info(f"Starting Neo4j MCP Agent with model: {MODEL_ID}")
    app.run()
