#!/usr/bin/env python3
"""
Finance Agent — Neo4j Aura Agent MCP Demo

Connects to a Neo4j Aura Agent MCP server and uses a ReAct agent
to answer questions about SEC filings, companies, and financial data.

Setup:
    export AURA_MCP_URL="https://your-aura-agent-mcp-endpoint"
    export AURA_API_KEY="your-api-key"          # optional

Usage:
    uv run python simple-agent.py                             # Run demo queries
    uv run python simple-agent.py "Tell me about Apple Inc"   # Ask a question
"""

import asyncio
import os
import sys

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient

MCP_URL = os.environ.get("AURA_MCP_URL", os.environ.get("AURA_AGENT_MCP_SERVER", ""))
API_KEY = os.environ.get("AURA_API_KEY", "")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

SYSTEM_PROMPT = """You are a financial analysis assistant with access to a Neo4j knowledge graph \
containing SEC filing data, company information, risk factors, and institutional ownership.

Use the available tools to answer questions. Cite specific data from the graph. \
Be concise but thorough."""

DEMO_QUESTIONS = [
    "What companies are in the database?",
    "Tell me about Apple Inc. What are their key risk factors?",
    "Who are the largest institutional owners of NVIDIA?",
    "Compare the risk factors between Apple and NVIDIA.",
]


def get_llm():
    return init_chat_model(
        MODEL_ID,
        model_provider="bedrock_converse",
        region_name=AWS_REGION,
        temperature=0,
    )


async def run_query(question: str):
    """Connect to MCP server, build agent, run one question."""
    # Build MCP connection config
    mcp_config = {
        "aura-agent": {
            "transport": "streamable_http",
            "url": MCP_URL,
        }
    }
    if API_KEY:
        mcp_config["aura-agent"]["headers"] = {"x-api-key": API_KEY}

    print(f"MCP:   {MCP_URL}")
    print(f"Model: {MODEL_ID}")
    print()

    # Connect and discover tools
    client = MultiServerMCPClient(mcp_config)
    tools = await client.get_tools()
    print(f"Tools: {[t.name for t in tools]}")
    print()

    # Run the agent
    llm = get_llm()
    agent = create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)
    result = await agent.ainvoke({"messages": [("human", question)]})

    # Print response
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
    if not MCP_URL:
        print("ERROR: Set AURA_MCP_URL environment variable")
        print()
        print("  export AURA_MCP_URL='https://your-aura-agent-mcp-endpoint'")
        print("  export AURA_API_KEY='your-api-key'   # optional")
        sys.exit(1)

    if len(sys.argv) > 1:
        asyncio.run(run_query(" ".join(sys.argv[1:])))
    else:
        asyncio.run(run_demo())


if __name__ == "__main__":
    main()
