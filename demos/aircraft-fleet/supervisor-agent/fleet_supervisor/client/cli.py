"""Ask the supervisor one question and stream the answer.

    uv run fleet-supervisor-cli "Which components fail most often?"
    uv run fleet-supervisor-cli --remote "Which routes have the most delays?"

Without ``--remote`` it calls the local server on port 7071. With it, it
calls the deployed runtime named by ``AGENT_ARN``. Both read the shared
aircraft-fleet .env, or the file ``FLEET_ENV_FILE`` names.
"""

import argparse
import os
import sys
import time

from fleet_supervisor.client.fleet_env import load_fleet_env, require_agent_arn

# The transport reads AGENT_PORT at import time, so the .env loads first.
load_fleet_env()

import httpx  # noqa: E402

from fleet_supervisor.client.transport import (  # noqa: E402
    invoke_deployed,
    invoke_local,
    print_event,
)

DEFAULT_PROMPT = "What are the most common maintenance faults?"


def ask(prompt: str, session_id: str | None, cloud: bool) -> None:
    """Stream one answer from the local server, or from the deployed runtime when ``cloud``."""
    agent_arn = require_agent_arn() if cloud else None
    print(f"Prompt: {prompt}\n")
    start = time.monotonic()
    try:
        if agent_arn:
            region = os.getenv("AWS_REGION", "us-east-1")
            result = invoke_deployed(prompt, agent_arn, region, session_id, print_event)
        else:
            result = invoke_local(prompt, session_id, print_event)
    except httpx.ConnectError:
        sys.exit("ERROR: no local server. Start it with: uv run fleet-supervisor-server")

    routed = ", ".join(result.specialists) or "no specialist"
    print(f"\n[{time.monotonic() - start:.1f}s | {routed} | {len(result.tools)} tool calls]")
    if not result.ok:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the aircraft fleet supervisor agent.")
    parser.add_argument("prompt", nargs="*", help="the question to ask")
    parser.add_argument("--remote", action="store_true", help="call the deployed runtime")
    parser.add_argument("--session-id", help="reuse a session ID across calls")
    args = parser.parse_args()
    ask(" ".join(args.prompt) or DEFAULT_PROMPT, args.session_id, cloud=args.remote)


if __name__ == "__main__":
    main()
