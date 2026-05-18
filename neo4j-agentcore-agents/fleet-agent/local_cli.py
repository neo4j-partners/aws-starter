#!/usr/bin/env python3
"""Neo4j Fleet Agent (Strands) — local CLI.

A Strands-native terminal client that connects directly to Neo4j (no MCP
server, no Gateway). Uses the synchronous Strands agent call — the idiomatic
form for a one-shot CLI. The schema is injected into the system prompt.

Usage:
    uv run python strands/local_cli.py                  # demo queries
    uv run python strands/local_cli.py "your question"  # ask
"""

import logging
import sys

from strands import Agent
from strands.models import BedrockModel
from tools import graph_query_tool, vector_search_tool

from common import (
    AWS_REGION,
    MODEL_ID,
    SYSTEM_PROMPT_TEMPLATE,
    close,
    get_graph_schema,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

DEMO_QUESTIONS = [
    ("Count of Aircraft", "How many Aircraft are in the database?"),
    ("List Airports", "List 5 airports with their city and country."),
    ("Recent Maintenance Events", "Show me 3 recent maintenance events with their severity."),
    ("Flight Statistics", "How many flights are in the database and what operators fly them?"),
    ("Document Search", "What do the maintenance documents say about hydraulic system inspections?"),
]

model = BedrockModel(
    model_id=MODEL_ID,
    region_name=AWS_REGION,
    temperature=0.0,
    streaming=True,
)


def run_query(question: str):
    """Build the agent and answer one question."""
    print("=" * 70)
    print("Neo4j Fleet Agent (Strands)")
    print("=" * 70)
    print()

    schema = get_graph_schema()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=schema)

    print(f"Model: {MODEL_ID}")
    print("Tools: graph_query_tool, vector_search_tool")
    print()
    print("=" * 70)
    print(f"Question: {question}")
    print("=" * 70)
    print()

    agent = Agent(
        model=model,
        tools=[graph_query_tool, vector_search_tool],
        system_prompt=system_prompt,
    )
    result = agent(question)
    print(result)


def run_demo():
    print()
    print("#" * 76)
    print("#" + "NEO4J FLEET AGENT DEMO (Strands)".center(74) + "#")
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
    finally:
        close()


if __name__ == "__main__":
    main()
