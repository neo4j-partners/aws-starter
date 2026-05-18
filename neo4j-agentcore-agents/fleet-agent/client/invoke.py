#!/usr/bin/env python3
"""Deployed-agent harness — single invocation and continuous load test.

Talks to the agent deployed on AgentCore Runtime over the boto3
``bedrock-agentcore`` data plane (via :mod:`client.transport`). The response
streams to the terminal token by token as the SSE events arrive.

Usage:
    uv run python -m client.invoke                       # default prompt
    uv run python -m client.invoke "How many aircraft?"  # custom prompt
    uv run python -m client.invoke load-test             # random queries, 5s
    uv run python -m client.invoke load-test 10          # custom interval (s)

Prerequisites:
    - Agent deployed (./agent.sh deploy)
    - AWS credentials configured
    - .bedrock_agentcore.yaml present (created by ./agent.sh configure)
"""

from __future__ import annotations

import logging
import random
import re
import sys
import time

from client.transport import AGENT_ROOT, invoke_deployed

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def load_queries() -> list[str]:
    """Load the numbered sample queries from the agent-root ``queries.txt``."""
    queries_file = AGENT_ROOT / "queries.txt"
    if not queries_file.exists():
        logging.error("queries.txt not found at %s", queries_file)
        return []

    queries: list[str] = []
    with open(queries_file) as f:
        for line in f:
            match = re.match(r"^\d+\.\s+(.+)$", line.strip())
            if match:
                queries.append(match.group(1))
    return queries


def _print_result(result: dict) -> None:
    """The success text already streamed live; only surface errors here."""
    if result.get("status") != "success":
        print(f"ERROR: {result.get('errors', ['Unknown error'])}")


def run_load_test(interval: int = 5) -> None:
    """Loop random queries against the deployed agent at ``interval`` seconds."""
    queries = load_queries()
    if not queries:
        print("ERROR: No queries found in queries.txt")
        sys.exit(1)

    print("=" * 70)
    print("Neo4j Fleet Agent - Load Test Mode")
    print("=" * 70)
    print(f"Loaded {len(queries)} queries from queries.txt")
    print(f"Running a random query every {interval} seconds...")
    print("Press Ctrl+C to stop")
    print("=" * 70)
    print("")

    iteration = 1
    try:
        while True:
            query_idx = random.randint(0, len(queries) - 1)
            query = queries[query_idx]

            print("=" * 70)
            print(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"Iteration {iteration} - Query #{query_idx + 1}"
            )
            print("=" * 70)
            print(f"Query: {query}")
            print("-" * 70)
            print("")

            _print_result(invoke_deployed({"prompt": query}))

            print("")
            print("-" * 70)
            print(f"Waiting {interval} seconds before next query...")
            print("")

            iteration += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("")
        print("=" * 70)
        print(f"Load test stopped after {iteration - 1} iterations")
        print("=" * 70)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "load-test":
        interval = 5
        if len(sys.argv) > 2:
            try:
                interval = int(sys.argv[2])
            except ValueError:
                print(
                    f"ERROR: Invalid interval '{sys.argv[2]}'. "
                    f"Must be a number."
                )
                sys.exit(1)
        run_load_test(interval)
        return

    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = "How many aircraft are in the database?"

    print("=" * 70)
    print("Neo4j Fleet Agent - Programmatic Invocation (deployed)")
    print("=" * 70)
    print("")
    print(f"Prompt: {prompt}")
    print("")
    print("=" * 70)
    print("Response:")
    print("=" * 70)
    _print_result(invoke_deployed({"prompt": prompt}))
    print("")


if __name__ == "__main__":
    main()
