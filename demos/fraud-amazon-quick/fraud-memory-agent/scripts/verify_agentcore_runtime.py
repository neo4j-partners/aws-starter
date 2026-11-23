#!/usr/bin/env python3
"""Verify that an AgentCore runtime is READY and can answer a graph query.

This is deliberately stricter than the control-plane deployment result.  A
runtime can be ``READY`` while its first invocation still fails because of an
import error, a missing runtime environment variable, or an unavailable MCP
dependency.  The smoke request exercises the full runtime, NAMS, model, and
Neo4j MCP path before callers are sent to it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections.abc import Callable, Iterable

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

DEFAULT_PROMPT = (
    "Use the Neo4j graph tools to identify one account with a high risk score. "
    "Give a one-sentence answer."
)
# A new runtime stays CREATING for a while after `agentcore deploy` returns.
DEFAULT_READY_TIMEOUT_SECONDS = 600
DEFAULT_POLL_INTERVAL_SECONDS = 15
# Statuses from which a runtime cannot become READY without a new deploy.
TERMINAL_STATUSES = frozenset({"CREATE_FAILED", "UPDATE_FAILED", "DELETING", "DELETE_FAILED"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-arn",
        required=True,
        help="The Runtime ARN, from 'agentcore status --json' or AGENT_ARN.",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="Maximum read time for the graph invocation (default: 180).",
    )
    parser.add_argument(
        "--ready-timeout-seconds",
        type=int,
        default=DEFAULT_READY_TIMEOUT_SECONDS,
        help=(
            "Maximum time to wait for the runtime to reach READY "
            f"(default: {DEFAULT_READY_TIMEOUT_SECONDS})."
        ),
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help=f"Time between runtime status checks (default: {DEFAULT_POLL_INTERVAL_SECONDS}).",
    )
    return parser.parse_args()


def parse_runtime_arn(runtime_arn: str) -> tuple[str, str]:
    """Return ``(runtime_id, region)`` from a Runtime ARN.

    The ARN has the form
    ``arn:aws:bedrock-agentcore:<region>:<account>:runtime/<runtime_id>``.
    """
    parts = runtime_arn.split(":")
    resource = parts[5] if len(parts) == 6 else ""
    kind, _, runtime_id = resource.partition("/")
    if parts[2:3] != ["bedrock-agentcore"] or not parts[3] or kind != "runtime" or not runtime_id:
        raise ValueError(f"Not an AgentCore Runtime ARN: {runtime_arn}")
    return runtime_id, parts[3]


def wait_for_ready(
    control,
    runtime_id: str,
    *,
    timeout_seconds: int,
    interval_seconds: int,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str | None:
    """Poll the runtime until it is READY.

    Returns None when the runtime is READY, or an error message when it
    reaches a terminal status or the timeout passes first.
    """
    deadline = clock() + timeout_seconds
    last_status = None
    while True:
        runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
        status = runtime.get("status")
        if status == "READY":
            return None
        if status in TERMINAL_STATUSES:
            reason = runtime.get("failureReason") or "no failure reason supplied"
            return f"Runtime is not ready: status={status!r}; reason={reason}"
        if status != last_status:
            print(f"Runtime status is {status!r}; waiting for READY...")
            last_status = status
        remaining = deadline - clock()
        if remaining <= 0:
            return (
                f"Runtime did not reach READY within {timeout_seconds} seconds: "
                f"last status={status!r}"
            )
        sleep(min(interval_seconds, remaining))


def consume_sse(chunks: Iterable[bytes]) -> tuple[str, list[str], bool]:
    """Return response text, runtime errors, and whether a complete event arrived."""
    buffer = ""
    content: list[str] = []
    errors: list[str] = []
    completed = False
    for raw in chunks:
        buffer += raw.decode("utf-8")
        while "\n\n" in buffer:
            event, buffer = buffer.split("\n\n", 1)
            if event.startswith("data: "):
                event = event[6:]
            try:
                message = json.loads(event)
            except json.JSONDecodeError:
                continue
            event_type = message.get("type")
            if event_type == "chunk":
                content.append(str(message.get("data", "")))
            elif "error" in message:
                # BedrockAgentCoreApp's event when the runtime's stream raises.
                error_type = message.get("error_type")
                text = str(message["error"])
                errors.append(f"{error_type}: {text}" if error_type else text)
            elif event_type == "complete":
                completed = True
    return "".join(content), errors, completed


def main() -> int:
    args = parse_args()
    if args.timeout_seconds < 1:
        print("--timeout-seconds must be positive.", file=sys.stderr)
        return 2
    if args.ready_timeout_seconds < 0:
        print("--ready-timeout-seconds must not be negative.", file=sys.stderr)
        return 2
    if args.poll_interval_seconds < 1:
        print("--poll-interval-seconds must be positive.", file=sys.stderr)
        return 2
    try:
        runtime_id, region = parse_runtime_arn(args.runtime_arn)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    runtime_arn = args.runtime_arn

    try:
        client_config = Config(
            connect_timeout=10,
            read_timeout=args.timeout_seconds,
            retries={"max_attempts": 2, "mode": "standard"},
        )
        control = boto3.client(
            "bedrock-agentcore-control", region_name=region, config=client_config
        )
        not_ready = wait_for_ready(
            control,
            runtime_id,
            timeout_seconds=args.ready_timeout_seconds,
            interval_seconds=args.poll_interval_seconds,
        )
        if not_ready:
            print(not_ready, file=sys.stderr)
            return 1
        print(f"Runtime READY: {runtime_arn}")

        session_suffix = uuid.uuid4().hex[:12]
        payload = {
            "prompt": args.prompt,
            "user_id": f"agentcore-smoke-{session_suffix}",
            "session_id": f"agentcore-smoke-{int(time.time())}-{session_suffix}",
        }
        runtime_client = boto3.client("bedrock-agentcore", region_name=region, config=client_config)
        # The runtime user ID makes the Runtime fetch a workload access token
        # for the request. The agent needs it to read its credentials from
        # AgentCore Identity.
        response = runtime_client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=str(uuid.uuid4()),
            runtimeUserId=payload["user_id"],
            payload=json.dumps(payload).encode("utf-8"),
            qualifier="DEFAULT",
        )
        status_code = response.get("statusCode")
        if status_code != 200:
            print(f"Smoke invocation returned HTTP {status_code!r}.", file=sys.stderr)
            return 1
        answer, errors, completed = consume_sse(response.get("response", []))
    except (BotoCoreError, ClientError, OSError, ValueError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1

    if errors:
        print(f"Runtime returned an error: {'; '.join(errors)}", file=sys.stderr)
        return 1
    if not completed:
        print("Runtime response ended without a complete event.", file=sys.stderr)
        return 1
    if not answer.strip():
        print("Runtime completed without response content.", file=sys.stderr)
        return 1
    print(f"Graph smoke test passed ({len(answer)} response characters).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
