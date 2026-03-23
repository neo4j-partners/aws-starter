#!/usr/bin/env python3
"""
Finance Agent — Neo4j MCP via AgentCore Gateway

Connects to a Neo4j MCP server deployed on AgentCore via the Gateway
and uses a ReAct agent to answer questions about SEC filings, companies,
and financial data.

Setup:
    cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .

Usage:
    uv run python simple-agent.py                             # Run demo queries
    uv run python simple-agent.py "Tell me about Apple Inc"   # Ask a question
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient


CREDENTIALS_FILE = ".mcp-credentials.json"
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


def load_credentials() -> dict:
    """Load credentials from .mcp-credentials.json."""
    if not Path(CREDENTIALS_FILE).exists():
        print("ERROR: Credentials file not found: .mcp-credentials.json")
        print()
        print("Copy from the MCP server deployment:")
        print("  cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json .")
        sys.exit(1)

    with open(CREDENTIALS_FILE) as f:
        return json.load(f)


def get_llm(region: str = "us-west-2"):
    """Get the LLM to use for the agent (AWS Bedrock Claude via Converse API)."""
    return init_chat_model(
        MODEL_ID,
        model_provider="bedrock_converse",
        region_name=region,
        temperature=0,
    )


async def run_query(question: str):
    """Connect to MCP server via Gateway, build agent, run one question."""
    credentials = load_credentials()
    gateway_url = credentials["gateway_url"]
    access_token = credentials["access_token"]
    region = credentials.get("region", AWS_REGION)

    print(f"Gateway: {gateway_url}")
    print(f"Model:   {MODEL_ID}")
    print()

    # Connect to MCP server via Gateway
    client = MultiServerMCPClient(
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

    tools = await client.get_tools()
    print(f"Tools: {[t.name for t in tools]}")
    print()

    # Run the agent
    llm = get_llm(region)
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
    if len(sys.argv) > 1:
        asyncio.run(run_query(" ".join(sys.argv[1:])))
    else:
        asyncio.run(run_demo())


if __name__ == "__main__":
    main()
