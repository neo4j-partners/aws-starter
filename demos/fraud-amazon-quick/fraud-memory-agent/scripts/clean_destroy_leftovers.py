#!/usr/bin/env python3
"""Remove what ``agentcore destroy`` leaves behind for this agent.

The legacy toolkit's destroy keeps four things: the CodeBuild source bucket
``bedrock-agentcore-codebuild-sources-<account>-<region>``, the memory's
vended log group, the local ``.bedrock_agentcore/<agent>/`` build cache, and
the Runtime's log groups under
``/aws/bedrock-agentcore/runtimes/<runtime-id>-``.
Destroy also deletes ``.bedrock_agentcore.yaml``, so ``agent.sh`` copies that
file first and passes the copy here as ``--snapshot``.

Each step is narrow. The bucket goes only when it is empty, because every
toolkit agent in the account and Region shares it. The log group goes only
when the toolkit created the memory, because destroy keeps a pre-existing
memory. The cache goes only for this agent, and its parent folder only when
nothing else is left in it. The Runtime's log groups go only after the Runtime
is gone, and only under the exact runtime ID followed by a dash. A missing
resource is reported, not treated as an error.

Exit codes: 0 when the cleanup ran without failures, 1 when a step failed or
the config could not be read after destroy, 2 when the snapshot is unusable,
and 3 when destroy did not remove the agent, so nothing was cleaned.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

import boto3
import yaml
from botocore.exceptions import BotoCoreError, ClientError

CACHE_DIR_NAME = ".bedrock_agentcore"
MEMORY_LOG_GROUP_PREFIX = "/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/"
# AgentCore writes each runtime's logs to <prefix><runtime-id>-<endpoint>.
RUNTIME_LOG_GROUP_PREFIX = "/aws/bedrock-agentcore/runtimes/"
# The AgentCore runtime ID pattern: the runtime name, a dash, and 10 characters.
RUNTIME_ID_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{0,99}-[a-zA-Z0-9]{10}")
# Destroy asks AgentCore to delete the runtime but does not wait for it.
RUNTIME_DELETE_TIMEOUT = 600
RUNTIME_DELETE_POLL = 10
# agent.sh reads this exit code as "destroy did not finish".
EXIT_DESTROY_NOT_FINISHED = 3

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


def runtime_is_gone(control, runtime_id: str) -> bool:
    """Wait for the runtime to disappear. Return False if it outlasts the timeout."""
    deadline = time.monotonic() + RUNTIME_DELETE_TIMEOUT
    while True:
        try:
            control.get_agent_runtime(agentRuntimeId=runtime_id)
        except ClientError as error:
            if error_code(error) == "ResourceNotFoundException":
                return True
            raise
        if time.monotonic() >= deadline:
            return False
        time.sleep(RUNTIME_DELETE_POLL)


def remove_runtime_log_groups(logs, runtime_id: str, region: str) -> tuple[list[str], list[str]]:
    """Delete the runtime's log groups. Return report lines and failure lines.

    The prefix ends with the dash after the full ID, so it cannot match another
    runtime's group. A failed delete does not stop the others.
    """
    prefix = f"{RUNTIME_LOG_GROUP_PREFIX}{runtime_id}-"
    names = [
        group["logGroupName"]
        for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=prefix)
        for group in page.get("logGroups", [])
        if group["logGroupName"].startswith(prefix)
    ]
    if not names:
        return [f"Not found: log groups under {prefix} in {region}"], []
    report: list[str] = []
    failures: list[str] = []
    for name in names:
        try:
            logs.delete_log_group(logGroupName=name)
        except ClientError as error:
            if error_code(error) == "ResourceNotFoundException":
                report.append(f"Not found: log group {name}")
            else:
                failures.append(f"Could not remove log group {name} in {region}: {error}")
        except BotoCoreError as error:
            failures.append(f"Could not remove log group {name} in {region}: {error}")
        else:
            report.append(f"Removed: log group {name}")
    return report, failures


def clean_runtime_log_groups(
    agent: dict, region: str, client_factory: ClientFactory
) -> tuple[list[str], list[str]]:
    """Remove the runtime's log groups once the runtime itself is gone."""
    runtime_id = (agent.get("bedrock_agentcore") or {}).get("agent_id")
    if not isinstance(runtime_id, str) or not RUNTIME_ID_PATTERN.fullmatch(runtime_id):
        return ["Skipped: runtime log groups; no valid runtime ID in the config"], []
    prefix = f"{RUNTIME_LOG_GROUP_PREFIX}{runtime_id}-"
    try:
        control = client_factory("bedrock-agentcore-control", region_name=region)
        if not runtime_is_gone(control, runtime_id):
            return [], [
                f"Runtime {runtime_id} is still present after {RUNTIME_DELETE_TIMEOUT}s, "
                f"so its log groups under {prefix} in {region} stay in place"
            ]
        logs = client_factory("logs", region_name=region)
        return remove_runtime_log_groups(logs, runtime_id, region)
    except (BotoCoreError, ClientError) as error:
        return [], [f"Could not remove the log groups under {prefix} in {region}: {error}"]


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
    """Return report lines and failure lines for the four leftovers."""
    report: list[str] = []
    failures: list[str] = []
    aws = agent.get("aws") or {}
    region = aws.get("region")
    account = aws.get("account")

    if not region:
        report.append(
            "Skipped: S3 bucket, memory log group and runtime log groups; no Region in the config"
        )
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

    # Last, because it may wait for AgentCore to finish deleting the runtime.
    if region:
        runtime_report, runtime_failures = clean_runtime_log_groups(agent, region, client_factory)
        report.extend(runtime_report)
        failures.extend(runtime_failures)
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
    try:
        still_configured = args.config.exists() and load_agent(args.config, args.agent) is not None
    except (OSError, yaml.YAMLError) as error:
        print(
            f"Could not read {args.config.name} after destroy, so the leftovers stay "
            f"in place: {error}",
            file=sys.stderr,
        )
        return 1
    if still_configured:
        print(
            f"agentcore destroy did not remove '{args.agent}' from {args.config.name}. "
            "It was cancelled or failed, so the leftovers stay in place."
        )
        return EXIT_DESTROY_NOT_FINISHED

    report, failures = clean_leftovers(agent, args.agent, args.cache_dir)
    for line in report:
        print(line)
    for line in failures:
        print(line, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
