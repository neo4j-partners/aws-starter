#!/usr/bin/env python3
"""Finance Agent (LangGraph) — local CLI.

Connects to the Neo4j MCP server via AgentCore Gateway and uses a ReAct agent
to answer questions about SEC filings, companies, and financial data. Runs
directly in your terminal — no AgentCore Runtime involved.

Usage:
    uv run python langgraph/simple-agent.py                            # demo
    uv run python langgraph/simple-agent.py "Tell me about Apple Inc"  # ask
"""

import asyncio
import logging
import sys

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient

from common import (
    AWS_REGION,
    MODEL_ID,
    SYSTEM_PROMPT,
    get_active_credentials,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

DEMO_QUESTIONS = [
    "What companies are in the database?",
    "Tell me about Apple Inc. What are their key risk factors?",
    "Who are the largest institutional owners of NVIDIA?",
    "Compare the risk factors between Apple and NVIDIA.",
]


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


async def run_query(question: str):
    """Connect to MCP server via Gateway, build agent, run one question."""
    credentials = get_active_credentials()
    gateway_url = credentials["gateway_url"]
    access_token = credentials["access_token"]
    region = credentials.get("region", AWS_REGION)

    print(f"Gateway: {gateway_url}")
    print(f"Model:   {MODEL_ID}")
    print()

    client = build_mcp_client(gateway_url, access_token)
    tools = await client.get_tools()
    print(f"Tools: {[t.name for t in tools]}")
    print()

    llm = get_llm(region)
    agent = create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)
    result = await agent.ainvoke({"messages": [("human", question)]})

    messages = result.get("messages", [])
    if messages and hasattr(messages[-1], "content"):
        print(messages[-1].content)
    else:
        print("No response from agent")


async def run_demo():
    for i, q in enumerate(DEMO_QUESTIONS, 1):
        print("=" * 70)
        print(f"  [{i}] {q}")
        print("=" * 70)
        print()
        await run_query(q)
        print()


def main():
    try:
        if len(sys.argv) > 1:
            asyncio.run(run_query(" ".join(sys.argv[1:])))
        else:
            asyncio.run(run_demo())
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
