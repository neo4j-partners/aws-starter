#!/usr/bin/env python3
"""Finance Agent (LangGraph) — AgentCore Runtime deployment.

A ReAct agent for financial data analysis that connects to the Neo4j MCP
server via AgentCore Gateway. The OAuth2 token is refreshed automatically, so
the deployed agent keeps working past the initial token's expiry.

Local testing:
    ./agent.sh start
    curl -X POST http://localhost:8080/invocations \
        -H "Content-Type: application/json" \
        -d '{"prompt": "What companies are in the database?"}'

Cloud deployment:
    ./agent.sh configure
    ./agent.sh deploy
    ./agent.sh invoke-cloud "What companies are in the database?"
"""

import logging

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient

from common import (
    AWS_REGION,
    MODEL_ID,
    SYSTEM_PROMPT,
    get_active_credentials,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = BedrockAgentCoreApp()


def get_llm(region: str = AWS_REGION):
    """Get the Bedrock Claude LLM via the Converse API."""
    return init_chat_model(
        MODEL_ID,
        model_provider="bedrock_converse",
        region_name=region,
        temperature=0,
    )


def build_mcp_client(gateway_url: str, access_token: str) -> MultiServerMCPClient:
    """Build an MCP client pointed at the Neo4j MCP server via Gateway."""
    return MultiServerMCPClient(
        {
            "neo4j": {
                "transport": "streamable_http",
                "url": gateway_url,
                "headers": {"Authorization": f"Bearer {access_token}"},
            }
        }
    )


@app.entrypoint
async def invoke(payload: dict | None = None):
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

    logger.info(f"Query: {prompt[:100]}...")

    try:
        credentials = get_active_credentials()
        gateway_url = credentials["gateway_url"]
        access_token = credentials["access_token"]
        region = credentials.get("region", AWS_REGION)

        logger.info(f"Gateway: {gateway_url}")
        logger.info(f"Model: {MODEL_ID}")

        llm = get_llm(region)
        mcp_client = build_mcp_client(gateway_url, access_token)

        tools = await mcp_client.get_tools()
        logger.info(f"Loaded {len(tools)} tools: {[t.name for t in tools]}")

        agent = create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)
        result = await agent.ainvoke({"messages": [("human", prompt)]})

        messages = result.get("messages", [])
        if messages and hasattr(messages[-1], "content"):
            response_text = messages[-1].content
        else:
            response_text = "No response from agent"

        yield {"type": "chunk", "data": response_text}
        yield {"type": "complete"}

        logger.info("Request completed successfully")

    except FileNotFoundError as e:
        logger.error(f"Credentials error: {e}")
        yield {"type": "error", "error": str(e)}
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        yield {"type": "error", "error": f"Error processing request: {str(e)}"}


if __name__ == "__main__":
    app.run(port=8080)
