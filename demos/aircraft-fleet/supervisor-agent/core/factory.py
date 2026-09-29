"""Bedrock LLM and MCP tool factories.

Kept out of ``core/__init__`` because importing this pulls the LangChain /
MCP dependency stack; the server and graph import it directly where needed.
"""

import logging

import boto3
from langchain_aws import ChatBedrockConverse
from langchain_mcp_adapters.client import MultiServerMCPClient

from core.config import AWS_REGION, MODEL_ID

logger = logging.getLogger(__name__)


def get_llm(region: str = AWS_REGION):
    """Get Claude LLM via AWS Bedrock Converse API."""
    bedrock_client = boto3.client("bedrock-runtime", region_name=region)
    return ChatBedrockConverse(
        client=bedrock_client,
        model=MODEL_ID,
        temperature=0,
    )


async def get_mcp_tools(gateway_url: str, access_token: str) -> list:
    """Get MCP tools from the Neo4j server via Gateway."""
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
    logger.info("Loaded %d MCP tools: %s", len(tools), [t.name for t in tools])
    return tools
