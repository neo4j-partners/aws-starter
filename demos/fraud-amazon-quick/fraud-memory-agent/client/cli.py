#!/usr/bin/env python3
"""Finance Agent — terminal client.

A thin client. It does not build an agent: it sends a prompt to a running
``runtime_app.py`` and streams the answer back. ``--remote`` switches the
target from the local server to the deployed AgentCore runtime; nothing else
changes.

Usage:
    uv run python -m client.cli                       # ask the default prompt
    uv run python -m client.cli "your question"       # ask (local server)
    uv run python -m client.cli --remote "question"   # ask the deployed agent
    uv run python -m client.cli --user-id alice "..."  # scope memory to a user

For the full demo question set use ``client.demo``. Local use needs the
server running in another terminal:
    ./agent.sh start
"""

from __future__ import annotations

import argparse
import sys

from client.invoke import DEFAULT_PROMPT, DEFAULT_USER_ID
from client.transport import Target, invoke


def ask(question: str, target: Target, user_id: str) -> None:
    print("=" * 70)
    print(f"Finance Agent (Strands) — {target}")
    print("=" * 70)
    print(f"User ID:  {user_id}")
    print(f"Question: {question}")
    print("-" * 70)
    result = invoke(
        {"prompt": question, "user_id": user_id}, target=target, stream=True
    )
    if result.get("status") != "success":
        print(f"ERROR: {result.get('errors', ['Unknown error'])}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Terminal client for the Finance Agent."
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Target the deployed AgentCore runtime instead of localhost:7020.",
    )
    parser.add_argument(
        "--user-id",
        default=DEFAULT_USER_ID,
        help=f"Memory scope for the request (default: {DEFAULT_USER_ID})",
    )
    parser.add_argument(
        "question",
        nargs="*",
        help=f"Question to ask. Omit for the default: {DEFAULT_PROMPT!r}",
    )
    args = parser.parse_args()
    target: Target = "deployed" if args.remote else "local"
    question = " ".join(args.question) if args.question else DEFAULT_PROMPT

    try:
        ask(question, target, args.user_id)
    except Exception as e:  # noqa: BLE001 - surface any client-side failure
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
