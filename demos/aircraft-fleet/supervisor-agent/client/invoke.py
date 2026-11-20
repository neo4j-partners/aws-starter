"""Invoke the deployed supervisor once, or run a continuous load test.

    uv run fleet-supervisor-invoke "What flights depart from JFK?"
    uv run fleet-supervisor-invoke load-test [interval_seconds]

The deployed runtime ARN comes from ``AGENT_ARN``. ``./agent.sh`` sets it.
The load test counts the specialist that actually handled each query, and
compares it with the domain the query is listed under in ``queries.txt``.
"""

import argparse
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from client.transport import InvokeResult, invoke_deployed, print_event

QUERIES_FILE = Path(__file__).resolve().parent / "queries.txt"
DOMAIN_TO_AGENT = {"Maintenance": "Maintenance Agent", "Operations": "Operations Agent"}
RULE = "=" * 70


class Query(NamedTuple):
    number: int
    text: str
    expected_agent: str


def load_queries(path: Path = QUERIES_FILE) -> list[Query]:
    """Read numbered queries. A ``# === <Domain> Domain`` header sets the expected agent."""
    queries: list[Query] = []
    expected = "Unknown"
    for line in path.read_text(encoding="utf-8").splitlines():
        if header := re.match(r"#\s*===\s*(\w+) Domain", line):
            expected = DOMAIN_TO_AGENT.get(header.group(1), "Unknown")
        elif match := re.match(r"^(\d+)\.\s+(.+)$", line.strip()):
            queries.append(Query(int(match.group(1)), match.group(2), expected))
    return queries


def deployed_target() -> tuple[str, str]:
    """Return ``(agent_arn, region)`` from the environment."""
    agent_arn = os.environ.get("AGENT_ARN")
    if not agent_arn:
        sys.exit(
            "ERROR: AGENT_ARN is not set. Run ./agent.sh deploy, then ./agent.sh invoke-cloud."
        )
    return agent_arn, os.getenv("AWS_REGION", "us-east-1")


def ask(prompt: str, stream: bool = True) -> tuple[InvokeResult, float]:
    agent_arn, region = deployed_target()
    start = time.monotonic()
    result = invoke_deployed(prompt, agent_arn, region, on_event=print_event if stream else None)
    return result, time.monotonic() - start


def run_once(prompt: str) -> None:
    print(f"{RULE}\nAircraft Fleet Supervisor Agent - Cloud Invocation\n{RULE}\n")
    print(f"Prompt: {prompt}\n")
    result, elapsed = ask(prompt)
    routed = ", ".join(result.specialists) or "no specialist"
    print(f"\n{RULE}\nElapsed: {elapsed:.1f}s | Routed to: {routed}\n{RULE}")
    if not result.ok:
        sys.exit(1)


def run_load_test(interval: int) -> None:
    queries = load_queries()
    if not queries:
        sys.exit(f"ERROR: no queries found in {QUERIES_FILE}")

    print(RULE)
    print("Aircraft Fleet Supervisor Agent - Cloud Load Test")
    print(f"{len(queries)} queries | one every {interval}s | Ctrl+C to stop")
    print(RULE)

    routed: Counter[str] = Counter()
    mismatches = errors = iterations = 0
    try:
        while True:
            query = random.choice(queries)
            iterations += 1
            print(f"\n[{time.strftime('%H:%M:%S')}] #{iterations} | query {query.number}")
            print(f"Expected: {query.expected_agent}\nQuery: {query.text}\n")

            result, elapsed = ask(query.text, stream=False)
            if result.ok:
                print(result.text[:1000] + ("\n... [truncated]" if len(result.text) > 1000 else ""))
                routed.update(result.specialists or ["no specialist"])
                if query.expected_agent not in result.specialists:
                    mismatches += 1
            else:
                errors += 1
                print(f"ERROR: {'; '.join(result.errors)}")

            actual = ", ".join(result.specialists) or "no specialist"
            print(f"\nElapsed {elapsed:.1f}s | Routed to: {actual}")
            print(f"Totals: {dict(routed)} | unexpected routes={mismatches} errors={errors}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n{RULE}\nStopped after {iterations} queries")
        print(f"Routed: {dict(routed)} | unexpected routes={mismatches} errors={errors}\n{RULE}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Invoke the deployed fleet supervisor.")
    parser.add_argument("prompt", nargs="*", help="question, or 'load-test [interval]'")
    args = parser.parse_args()

    if args.prompt[:1] == ["load-test"]:
        interval = args.prompt[1] if len(args.prompt) > 1 else "5"
        if not interval.isdigit():
            sys.exit(f"ERROR: interval must be a whole number of seconds, got '{interval}'")
        run_load_test(int(interval))
    else:
        run_once(" ".join(args.prompt) or "What are the most common maintenance faults?")


if __name__ == "__main__":
    main()
