#!/usr/bin/env python3
"""Clear a deleted or cross-region AgentCore runtime binding from local config.

The legacy ``agentcore configure`` command retains deployment metadata from an
earlier configuration.  That is normally convenient, but it causes deploy to
call ``UpdateAgentRuntime`` against a runtime ID in the wrong region, or one
that has since been deleted.  A missing binding makes the CLI create a runtime
instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import boto3
import yaml
from botocore.exceptions import BotoCoreError, ClientError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--agent", required=True)
    return parser.parse_args()


def runtime_arn_region(runtime_arn: object) -> str | None:
    if not isinstance(runtime_arn, str):
        return None
    parts = runtime_arn.split(":", 4)
    return parts[3] if len(parts) == 5 and parts[0] == "arn" else None


def clear_binding(config: dict, agent_name: str, reason: str) -> bool:
    agent = config.get("agents", {}).get(agent_name)
    if not isinstance(agent, dict):
        print(f"No configuration found for agent '{agent_name}'; skipping runtime preflight.")
        return False

    deployment = agent.get("bedrock_agentcore")
    if not isinstance(deployment, dict) or not deployment.get("agent_id"):
        return False

    deployment["agent_id"] = None
    deployment["agent_arn"] = None
    deployment["agent_session_id"] = None
    print(f"Cleared stale AgentCore runtime binding ({reason}).")
    return True


def save_config(path: Path, config: dict) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, default_flow_style=False, sort_keys=False)
    temporary_path.replace(path)


def main() -> int:
    args = parse_args()
    if not args.config.exists():
        return 0

    with args.config.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    agent = config.get("agents", {}).get(args.agent)
    if not isinstance(agent, dict):
        print(f"No configuration found for agent '{args.agent}'; skipping runtime preflight.")
        return 0

    deployment = agent.get("bedrock_agentcore")
    if not isinstance(deployment, dict):
        return 0
    runtime_id = deployment.get("agent_id")
    if not runtime_id:
        return 0

    aws_config = agent.get("aws") or {}
    region = aws_config.get("region")
    arn_region = runtime_arn_region(deployment.get("agent_arn"))
    if region and arn_region and region != arn_region:
        if clear_binding(config, args.agent, f"runtime ARN region {arn_region} differs from configured region {region}"):
            save_config(args.config, config)
        return 0

    if not region:
        print("AgentCore runtime preflight skipped: no AWS region is configured.")
        return 0

    try:
        boto3.client("bedrock-agentcore-control", region_name=region).get_agent_runtime(agentRuntimeId=runtime_id)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            print(
                "AgentCore runtime preflight could not verify the existing binding; "
                f"leaving it unchanged: {error}",
                file=sys.stderr,
            )
            return 0
        if clear_binding(config, args.agent, f"runtime '{runtime_id}' no longer exists in {region}"):
            save_config(args.config, config)
    except BotoCoreError as error:
        print(
            "AgentCore runtime preflight could not verify the existing binding; "
            f"leaving it unchanged: {error}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
