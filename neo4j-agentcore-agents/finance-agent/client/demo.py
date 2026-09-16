#!/usr/bin/env python3
"""Run curated graph-analysis questions against the Finance Agent."""

from __future__ import annotations

import argparse
import sys

from client.transport import Target, invoke

DEMO_QUESTIONS = [
    "Which accounts have the highest risk scores, and who do they transfer money to?",
    "Find communities of accounts that transfer money among themselves but rarely transact with merchants.",
    "Show the accounts with the highest betweenness centrality and explain why they are money-flow intermediaries.",
    "Detect circular transfer chains where money leaves an account and returns to it, A to B to C to A.",
    "Pick a high-risk account, find behaviorally similar accounts via SIMILAR_TO, and check whether they share transfer counterparties.",
    "Which merchant categories see the most transaction volume by region?",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Showcase finance-agent graph questions, locally or remotely.",
    )
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--user-id", default="finance-demo")
    parser.add_argument(
        "--session-id",
        default="finance-demo",
        help="NAMS conversation ID reused across this demo.",
    )
    parser.add_argument("-n", "--number", type=int, metavar="N")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        for index, question in enumerate(DEMO_QUESTIONS, 1):
            print(f"{index}. {question}")
        return
    if args.number is not None and not 1 <= args.number <= len(DEMO_QUESTIONS):
        parser.error(f"-n must be between 1 and {len(DEMO_QUESTIONS)}")

    questions = (
        [DEMO_QUESTIONS[args.number - 1]] if args.number else DEMO_QUESTIONS
    )
    target: Target = "deployed" if args.remote else "local"
    try:
        for index, question in enumerate(questions, 1):
            print(f"\n[{index}/{len(questions)}] {question}\n")
            result = invoke(
                {
                    "prompt": question,
                    "user_id": args.user_id,
                    "session_id": args.session_id,
                },
                target=target,
                stream=True,
            )
            if result.get("status") != "success":
                print(f"ERROR: {result.get('errors', ['Unknown error'])}")
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as error:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
