#!/usr/bin/env python3
"""Remove what ``agentcore destroy`` leaves behind for this agent.

The legacy toolkit's destroy keeps three things: the CodeBuild source bucket
``bedrock-agentcore-codebuild-sources-<account>-<region>``, the memory's
vended log group, and the local ``.bedrock_agentcore/<agent>/`` build cache.
Destroy also deletes ``.bedrock_agentcore.yaml``, so ``agent.sh`` copies that
file first and passes the copy here as ``--snapshot``.

Each step is narrow. The bucket goes only when it is empty, because every
toolkit agent in the account and Region shares it. The log group goes only
when the toolkit created the memory, because destroy keeps a pre-existing
memory. The cache goes only for this agent, and its parent folder only when
nothing else is left in it. A missing resource is reported, not treated as an
error.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import boto3
import yaml
from botocore.exceptions import BotoCoreError, ClientError

CACHE_DIR_NAME = ".bedrock_agentcore"
MEMORY_LOG_GROUP_PREFIX = "/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/"

ClientFactory = Callable[..., object]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        type=Path,
        required=True,
        help="Copy of .bedrock_agentcore.yaml taken before agentcore destroy.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path of .bedrock_agentcore.yaml after agentcore destroy.",
    )
    parser.add_argument("--agent", required=True)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        required=True,
        help=f"The agent's local {CACHE_DIR_NAME}/ folder.",
    )
    return parser.parse_args()


def load_agent(path: Path, agent_name: str) -> dict | None:
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    agent = (config.get("agents") or {}).get(agent_name)
    return agent if isinstance(agent, dict) else None


def error_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


def source_bucket_name(account: str, region: str) -> str:
    return f"bedrock-agentcore-codebuild-sources-{account}-{region}"


def remove_source_bucket(s3, bucket: str, account: str) -> str:
    """Delete the shared source bucket when it holds no objects or versions."""
    try:
        listing = s3.list_object_versions(Bucket=bucket, MaxKeys=1, ExpectedBucketOwner=account)
    except ClientError as error:
        if error_code(error) == "NoSuchBucket":
            return f"Not found: S3 bucket {bucket}"
        raise
    if listing.get("Versions") or listing.get("DeleteMarkers"):
        return f"Skipped: S3 bucket {bucket} is not empty; other agents may use it"
    s3.delete_bucket(Bucket=bucket, ExpectedBucketOwner=account)
    return f"Removed: S3 bucket {bucket}"


def remove_memory_log_group(logs, memory: dict) -> str:
    """Delete the log group of a memory that the toolkit created."""
    memory_id = memory.get("memory_id")
    if not memory_id or memory.get("mode") == "NO_MEMORY":
        return "Skipped: memory log group; the agent had no memory"
    if not memory.get("was_created_by_toolkit"):
        return f"Skipped: memory log group; memory {memory_id} was pre-existing"
    log_group = f"{MEMORY_LOG_GROUP_PREFIX}{memory_id}"
    try:
        logs.delete_log_group(logGroupName=log_group)
    except ClientError as error:
        if error_code(error) == "ResourceNotFoundException":
            return f"Not found: log group {log_group}"
        raise
    return f"Removed: log group {log_group}"


def is_plain_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def remove_cache_dir(cache_dir: Path, agent_name: str) -> str:
    """Delete this agent's build cache, then the cache folder if it is empty."""
    if cache_dir.name != CACHE_DIR_NAME:
        return f"Skipped: {cache_dir} is not a {CACHE_DIR_NAME} folder"
    agent_cache = cache_dir / agent_name
    if not cache_dir.exists() and not cache_dir.is_symlink():
        return f"Not found: local cache {agent_cache}"
    if not is_plain_dir(cache_dir):
        return f"Skipped: {cache_dir} is not a plain folder"
    if not agent_cache.exists() and not agent_cache.is_symlink():
        result = f"Not found: local cache {agent_cache}"
    elif not is_plain_dir(agent_cache):
        return f"Skipped: {agent_cache} is not a plain folder"
    else:
        shutil.rmtree(agent_cache)
        result = f"Removed: local cache {agent_cache}"
    if not any(cache_dir.iterdir()):
        cache_dir.rmdir()
    return result


def clean_leftovers(
    agent: dict,
    agent_name: str,
    cache_dir: Path,
    client_factory: ClientFactory = boto3.client,
) -> tuple[list[str], list[str]]:
    """Return report lines and failure lines for the three leftovers."""
    report: list[str] = []
    failures: list[str] = []
    aws = agent.get("aws") or {}
    region = aws.get("region")
    account = aws.get("account")

    if not region:
        report.append("Skipped: S3 bucket and memory log group; no Region in the config")
    else:
        try:
            if not account:
                sts = client_factory("sts", region_name=region)
                account = sts.get_caller_identity()["Account"]
            s3 = client_factory("s3", region_name=region)
            report.append(remove_source_bucket(s3, source_bucket_name(account, region), account))
        except (BotoCoreError, ClientError) as error:
            failures.append(f"Could not remove the S3 source bucket in {region}: {error}")
        memory = agent.get("memory") or {}
        try:
            logs = client_factory("logs", region_name=region)
            report.append(remove_memory_log_group(logs, memory))
        except (BotoCoreError, ClientError) as error:
            failures.append(
                f"Could not remove the log group of memory {memory.get('memory_id')} "
                f"in {region}: {error}"
            )

    try:
        report.append(remove_cache_dir(cache_dir, agent_name))
    except OSError as error:
        failures.append(f"Could not remove the local cache {cache_dir}: {error}")
    return report, failures


def main() -> int:
    args = parse_args()
    try:
        agent = load_agent(args.snapshot, args.agent)
    except (OSError, yaml.YAMLError) as error:
        print(f"Could not read the config snapshot: {error}", file=sys.stderr)
        return 2
    if agent is None:
        print(f"Agent '{args.agent}' is not in the config snapshot.", file=sys.stderr)
        return 2

    # Destroy removes the agent from the config only when it finished without
    # errors. A cancelled or failed destroy leaves the agent in place.
    if args.config.exists() and load_agent(args.config, args.agent) is not None:
        print(
            f"agentcore destroy did not remove '{args.agent}' from {args.config.name}. "
            "It was cancelled or failed, so the leftovers stay in place."
        )
        return 0

    report, failures = clean_leftovers(agent, args.agent, args.cache_dir)
    for line in report:
        print(line)
    for line in failures:
        print(line, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
