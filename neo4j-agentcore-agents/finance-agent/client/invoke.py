#!/usr/bin/env python3
"""Thin invocation client for the NAMS-enabled Finance Agent."""

from __future__ import annotations

import argparse
import random
import sys
import time

from client.transport import Target, invoke

DEFAULT_PROMPT = (
    "Which accounts have the highest risk scores, and who do they transfer money to?"
)
DEFAULT_USER_ID = "demo-user"
LOAD_PROMPTS = (
    DEFAULT_PROMPT,
    "Find communities of accounts that transfer money among themselves but rarely transact with merchants.",
    "Detect circular transfer chains where money leaves an account and returns to it.",
    "Show accounts with high betweenness centrality and explain their role in money flow.",
)


def invoke_agent(
    prompt: str,
    user_id: str = DEFAULT_USER_ID,
    session_id: str | None = None,
    target: Target = "deployed",
    stream: bool = True,
) -> dict:
    """Send one request, preserving the supplied NAMS user/session scope."""
    payload: dict[str, str] = {"prompt": prompt, "user_id": user_id}
    if session_id:
        payload["session_id"] = session_id
    return invoke(payload, target=target, stream=stream)


def _print_result(result: dict) -> None:
    if result.get("status") != "success":
        print(f"ERROR: {result.get('errors', ['Unknown error'])}")


def run_memory_demo(user_id: str, target: Target) -> None:
    """Create two NAMS-captured turns with one correlation session ID."""
    session_id = f"nams-demo-{user_id}"
    teach = (
        "I am a synthetic demo user. My simulated portfolio favors low-risk "
        "energy funds and I hold NVIDIA. Acknowledge this, then identify a "
        "relevant risk question to investigate."
    )
    recall = "Investigate a circular transfer chain for this synthetic demo user."
    print(f"NAMS capture demo ({target}); user={user_id}, session={session_id}")
    print("Both turns are stored in NAMS with the same client session metadata.")
    _print_result(invoke_agent(teach, user_id, session_id, target))
    _print_result(invoke_agent(recall, user_id, session_id, target))


def run_load_test(interval: int, user_id: str, target: Target) -> None:
    """Run an open-ended, low-rate stream in one NAMS conversation."""
    session_id = f"nams-load-{user_id}"
    iteration = 1
    print(f"Sending a request every {interval}s; press Ctrl+C to stop.")
    try:
        while True:
            prompt = random.choice(LOAD_PROMPTS)
            print(f"[{iteration}] {prompt}")
            _print_result(invoke_agent(prompt, user_id, session_id, target))
            iteration += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"Stopped after {iteration - 1} requests.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Invoke the NAMS-enabled Finance Agent.",
    )
    parser.add_argument(
        "command",
        nargs="*",
        help="'memory-demo', 'load-test', or a prompt to send",
    )
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument(
        "--local",
        action="store_true",
        help="Target localhost:7020 instead of the deployed runtime.",
    )
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be positive")
    target: Target = "local" if args.local else "deployed"
    command = args.command
    try:
        if command and command[0] == "memory-demo":
            run_memory_demo(args.user_id, target)
        elif command and command[0] == "load-test":
            run_load_test(args.interval, args.user_id, target)
        else:
            prompt = " ".join(command) if command else DEFAULT_PROMPT
            _print_result(invoke_agent(prompt, args.user_id, args.session_id, target))
    except Exception as error:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
