#!/usr/bin/env python3
"""Neo4j Fleet Agent — terminal client.

A thin client. It does not build an agent: it sends a prompt to a running
``runtime_app.py`` and streams the answer back. ``--remote`` switches the
target from the local server to the deployed AgentCore runtime; nothing else
changes.

Usage:
    uv run python -m client.cli                       # demo: first queries.txt entries
    uv run python -m client.cli "your question"       # ask (local server)
    uv run python -m client.cli --remote "question"   # ask the deployed agent

Local use needs the server running in another terminal:
    ./agent.sh start
"""

from __future__ import annotations

import argparse
import sys

from client.invoke import load_queries
from client.transport import Target, invoke

# Number of queries.txt entries to run when no question is given.
DEMO_COUNT = 5


def ask(question: str, target: Target) -> None:
    print("=" * 70)
    print(f"Neo4j Fleet Agent (Strands) — {target}")
    print("=" * 70)
    print(f"Question: {question}")
    print("-" * 70)
    result = invoke({"prompt": question}, target=target, stream=True)
    if result.get("status") != "success":
        print(f"ERROR: {result.get('errors', ['Unknown error'])}")
    print()


def run_demo(target: Target) -> None:
    queries = load_queries()[:DEMO_COUNT]
    if not queries:
        print("ERROR: No queries found in queries.txt")
        sys.exit(1)

    print()
    print("#" * 76)
    print("#" + "NEO4J FLEET AGENT DEMO (Strands)".center(74) + "#")
    print("#" * 76)
    for i, question in enumerate(queries, 1):
        print()
        print("=" * 76)
        print(f"  QUERY {i}/{len(queries)}")
        print("=" * 76)
        ask(question, target)
    print()
    print("#" * 76)
    print("#" + "DEMO COMPLETE".center(74) + "#")
    print("#" * 76)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Terminal client for the Neo4j Fleet Agent."
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Target the deployed AgentCore runtime instead of localhost:8080.",
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="Question to ask. Omit to run the queries.txt demo.",
    )
    args = parser.parse_args()
    target: Target = "deployed" if args.remote else "local"

    try:
        if args.question:
            ask(" ".join(args.question), target)
        else:
            run_demo(target)
    except Exception as e:  # noqa: BLE001 - surface any client-side failure
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
