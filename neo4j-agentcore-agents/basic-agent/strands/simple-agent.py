#!/usr/bin/env python3
"""Neo4j MCP Agent (Strands) — local CLI.

A Strands-native terminal client for the Neo4j MCP server via AgentCore
Gateway. Uses the synchronous Strands agent call — the idiomatic form for a
one-shot CLI. The cached schema is injected into the system prompt.

Usage:
    uv run python strands/simple-agent.py                  # demo queries
    uv run python strands/simple-agent.py "your question"  # ask
"""

import asyncio
import logging
import sys

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

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

DEMO_QUESTIONS = [
    ("Database Schema Overview", "What is the database schema? Give me a brief summary."),
    ("Count of Aircraft", "How many Aircraft are in the database?"),
    ("List Airports", "List 5 airports with their city and country."),
    ("Recent Maintenance Events", "Show me 3 recent maintenance events with their severity."),
    ("Flight Statistics", "How many flights are in the database and what operators fly them?"),
]

model = BedrockModel(
    model_id=MODEL_ID,
    region_name=AWS_REGION,
    temperature=0.0,
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
    print("=" * 70)
    print("Neo4j MCP Agent (Strands)")
    print("=" * 70)
    print()

    credentials = get_active_credentials()
    schema = asyncio.run(
        get_cached_schema(
            credentials["gateway_url"], credentials["access_token"]
        )
    )
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=schema)

    print(f"Model: {MODEL_ID}")
    print()

    with mcp_client:
        tools = mcp_client.list_tools_sync()
        print(f"Tools: {[t.tool_spec['name'] for t in tools]}")
        print()
        agent = Agent(model=model, tools=tools, system_prompt=system_prompt)
        print("=" * 70)
        print(f"Question: {question}")
        print("=" * 70)
        print()
        result = agent(question)

    print(result)


def run_demo():
    print()
    print("#" * 76)
    print("#" + "NEO4J MCP AGENT DEMO (Strands)".center(74) + "#")
    print("#" * 76)
    print()

    for i, (title, question) in enumerate(DEMO_QUESTIONS, 1):
        print()
        print("=" * 76)
        print(f"  QUERY {i}: {title}")
        print("=" * 76)
        print()
        run_query(question)
        print()

    print()
    print("#" * 76)
    print("#" + "DEMO COMPLETE".center(74) + "#")
    print("#" * 76)


def main():
    try:
        if len(sys.argv) < 2:
            run_demo()
        else:
            run_query(" ".join(sys.argv[1:]))
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
