"""Ask the supervisor one question and stream the answer.

    uv run fleet-supervisor-cli "Which components fail most often?"
    uv run fleet-supervisor-cli --remote "Which routes have the most delays?"

Without ``--remote`` it calls the local server on port 7071. With it, it
calls the deployed runtime named by ``AGENT_ARN``.
"""

import argparse
import os
import sys
import time

import httpx

from client.transport import invoke_deployed, invoke_local, print_event

DEFAULT_PROMPT = "What are the most common maintenance faults?"


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the aircraft fleet supervisor agent.")
    parser.add_argument("prompt", nargs="*", help="the question to ask")
    parser.add_argument("--remote", action="store_true", help="call the deployed runtime")
    parser.add_argument("--session-id", help="reuse a session ID across calls")
    args = parser.parse_args()
    prompt = " ".join(args.prompt) or DEFAULT_PROMPT

    print(f"Prompt: {prompt}\n")
    start = time.monotonic()
    try:
        if args.remote:
            agent_arn = os.environ.get("AGENT_ARN")
            if not agent_arn:
                sys.exit("ERROR: set AGENT_ARN, or run ./agent.sh invoke-cloud instead.")
            region = os.getenv("AWS_REGION", "us-east-1")
            result = invoke_deployed(prompt, agent_arn, region, args.session_id, print_event)
        else:
            result = invoke_local(prompt, args.session_id, print_event)
    except httpx.ConnectError:
        sys.exit("ERROR: no local server. Start it with: uv run fleet-supervisor-server")

    routed = ", ".join(result.specialists) or "no specialist"
    print(f"\n[{time.monotonic() - start:.1f}s | {routed} | {len(result.tools)} tool calls]")
    if not result.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
