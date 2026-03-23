#!/usr/bin/env python3
"""
Finance Agent — AgentCore Runtime Deployment

A ReAct agent for financial data analysis that connects to the Neo4j MCP server
via AgentCore Gateway.

Local testing:
    uv run python agent.py
    curl -X POST http://localhost:8080/invocations \
        -H "Content-Type: application/json" \
        -d '{"prompt": "What companies are in the database?"}'

Cloud deployment:
    agentcore configure -e agent.py
    agentcore deploy
    agentcore invoke '{"prompt": "What companies are in the database?"}'
"""

import json
import logging
import os
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = BedrockAgentCoreApp()

CREDENTIALS_FILE = ".mcp-credentials.json"
MODEL_ID = os.getenv("MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")

SYSTEM_PROMPT = """You are a financial analysis assistant with access to a Neo4j knowledge graph \
containing SEC filing data, company information, risk factors, and institutional ownership.

Use the available tools to answer questions. Cite specific data from the graph. \
Be concise but thorough."""


def load_credentials() -> dict:
    """Load credentials from .mcp-credentials.json."""
    path = Path(CREDENTIALS_FILE)
    if not path.exists():
        raise FileNotFoundError(
            "Credentials file not found: .mcp-credentials.json\n"
            "Copy from MCP server deployment: cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json ."
        )
    with open(path) as f:
        return json.load(f)


def get_llm(region: str = "us-west-2"):
    return init_chat_model(
        MODEL_ID,
        model_provider="bedrock_converse",
        region_name=region,
        temperature=0,
    )


@app.entrypoint
async def invoke(payload: dict = None):
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
        yield {"type": "error", "error": "No prompt provided. Include 'prompt' in your request."}
        return

    logger.info(f"Query: {prompt[:100]}...")

    try:
        credentials = load_credentials()
        gateway_url = credentials["gateway_url"]
        access_token = credentials["access_token"]
        region = credentials.get("region", AWS_REGION)

        logger.info(f"Gateway: {gateway_url}")

        llm = get_llm(region)

        mcp_client = MultiServerMCPClient(
            {
                "neo4j": {
                    "transport": "streamable_http",
                    "url": gateway_url,
                    "headers": {
                        "Authorization": f"Bearer {access_token}",
                    },
                }
            }
        )

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
