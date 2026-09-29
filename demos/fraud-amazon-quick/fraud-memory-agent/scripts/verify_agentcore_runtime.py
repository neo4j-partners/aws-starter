#!/usr/bin/env python3
"""Verify that the configured AgentCore runtime is READY and can answer a graph query.

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
from collections.abc import Iterable
from pathlib import Path

import boto3
import yaml
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

DEFAULT_PROMPT = (
    "Use the Neo4j graph tools to identify one account with a high risk score. "
    "Give a one-sentence answer."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="Maximum read time for the graph invocation (default: 180).",
    )
    return parser.parse_args()


def configured_runtime(config_path: Path, agent_name: str) -> tuple[str, str, str]:
    with config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    agent = config.get("agents", {}).get(agent_name)
    if not isinstance(agent, dict):
        raise ValueError(f"Agent '{agent_name}' is not configured in {config_path}.")
    deployment = agent.get("bedrock_agentcore") or {}
    runtime_id = deployment.get("agent_id")
    runtime_arn = deployment.get("agent_arn")
    region = (agent.get("aws") or {}).get("region")
    if not all(isinstance(value, str) and value for value in (runtime_id, runtime_arn, region)):
        raise ValueError(
            "AgentCore runtime binding is incomplete. Run './agent.sh configure' and "
            "'./agent.sh deploy' first."
        )
    return runtime_id, runtime_arn, region


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
            elif event_type == "error":
                errors.append(str(message.get("error", "Unknown runtime error")))
            elif event_type == "complete":
                completed = True
    return "".join(content), errors, completed


def main() -> int:
    args = parse_args()
    if args.timeout_seconds < 1:
        print("--timeout-seconds must be positive.", file=sys.stderr)
        return 2
    if not args.config.exists():
        print(f"Configuration file not found: {args.config}", file=sys.stderr)
        return 2

    try:
        runtime_id, runtime_arn, region = configured_runtime(args.config, args.agent)
        client_config = Config(
            connect_timeout=10,
            read_timeout=args.timeout_seconds,
            retries={"max_attempts": 2, "mode": "standard"},
        )
        control = boto3.client(
            "bedrock-agentcore-control", region_name=region, config=client_config
        )
        runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
        status = runtime.get("status")
        if status != "READY":
            reason = runtime.get("failureReason") or "no failure reason supplied"
            print(
                f"Runtime is not ready: status={status!r}; reason={reason}",
                file=sys.stderr,
            )
            return 1
        print(f"Runtime READY: {runtime_arn}")

        session_suffix = uuid.uuid4().hex[:12]
        payload = {
            "prompt": args.prompt,
            "user_id": f"agentcore-smoke-{session_suffix}",
            "session_id": f"agentcore-smoke-{int(time.time())}-{session_suffix}",
        }
        runtime_client = boto3.client(
            "bedrock-agentcore", region_name=region, config=client_config
        )
        response = runtime_client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=str(uuid.uuid4()),
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
