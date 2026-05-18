#!/usr/bin/env python3
"""Finance Agent (Strands) — local CLI.

A Strands-native terminal client for the Neo4j MCP server via AgentCore
Gateway. Uses the synchronous Strands agent call — the idiomatic form for a
one-shot CLI.

Usage:
    uv run python strands/simple-agent.py                            # demo
    uv run python strands/simple-agent.py "Tell me about Apple Inc"  # ask
"""

import logging
import sys

from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient

from common import AWS_REGION, MODEL_ID, SYSTEM_PROMPT, get_active_credentials

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

DEMO_QUESTIONS = [
    "What companies are in the database?",
    "Tell me about Apple Inc. What are their key risk factors?",
    "Who are the largest institutional owners of NVIDIA?",
    "Compare the risk factors between Apple and NVIDIA.",
]

model = BedrockModel(
    model_id=MODEL_ID,
    region_name=AWS_REGION,
    temperature=0.0,
    max_tokens=4096,
    streaming=True,
)


def create_transport():
    """Transport factory — resolves a fresh token on every context entry."""
    credentials = get_active_credentials()
    return streamablehttp_client(
        credentials["gateway_url"],
        headers={"Authorization": f"Bearer {credentials['access_token']}"},
    )


mcp_client = MCPClient(create_transport)


def run_query(question: str):
    """Open a per-call MCP scope, build the agent, answer one question."""
    print(f"Model: {MODEL_ID}")
    print()
    with mcp_client:
        tools = mcp_client.list_tools_sync()
        print(f"Tools: {[t.tool_spec['name'] for t in tools]}")
        print()
        agent = Agent(model=model, tools=tools, system_prompt=SYSTEM_PROMPT)
        result = agent(question)
    print(result)


def run_demo():
    for i, q in enumerate(DEMO_QUESTIONS, 1):
        print("=" * 70)
        print(f"  [{i}] {q}")
        print("=" * 70)
        print()
        run_query(q)
        print()


def main():
    try:
        if len(sys.argv) > 1:
            run_query(" ".join(sys.argv[1:]))
        else:
            run_demo()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
