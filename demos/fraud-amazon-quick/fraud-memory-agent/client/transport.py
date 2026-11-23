"""One wire, two transports — the only place clients touch the network.

``server/runtime_app.py`` serves ``/invocations`` and emits three SSE event
shapes: ``{"type": "chunk", "data": ...}``, ``{"type": "tool", "name": ...}``,
and ``{"type": "complete"}``. When the stream fails, ``BedrockAgentCoreApp``
sends ``{"error": ..., "error_type": ..., "message": ...}`` instead. A request
with no prompt or no ``user_id`` gets HTTP 400 before any event. Both
transports below produce the same byte stream, so a single parser handles
them:

- :func:`invoke_local`    — HTTP POST to a locally running runtime (port 7020).
- :func:`invoke_deployed` — boto3 ``bedrock-agentcore`` data plane (deployed).

:func:`invoke` dispatches on ``target`` and returns the shape callers expect:
``{"status": "success", "response": "..."}`` or
``{"status": "error", "errors": [...]}``.

``payload`` is passed through verbatim, so ``{"prompt": "..."}`` runs the full
agent and ``{"prompt": "...", "user_id": "...", "session_id": "..."}`` reaches
the runtime's per-request memory scope unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import uuid
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Literal

import boto3
import httpx
from botocore.config import Config

logger = logging.getLogger(__name__)

# fraud-memory-agent/ is the parent of client/. The AgentCore CLI project
# lives here, so `agentcore status` runs here regardless of the caller's cwd.
AGENT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_URL = "http://localhost:7020/invocations"
# Must match the Runtime name in agentcore/agentcore.json and agent.sh.
RUNTIME_NAME = "fraud_memory_agent"
DEPLOY_TARGET = "default"
STATUS_TIMEOUT_SECONDS = 60

Target = Literal["local", "deployed"]

# Agent turns can include a model response, MCP calls, and NAMS writes.  The
# botocore default read timeout is 60 seconds, which is too short for that
# work, especially while several sessions are active.  Do not silently retry
# an invocation by default: after a read timeout the runtime may have already
# completed the turn and a retry would create duplicate memory records.
DEFAULT_DEPLOYED_CONNECT_TIMEOUT = 10.0
DEFAULT_DEPLOYED_READ_TIMEOUT = 300.0
DEFAULT_DEPLOYED_MAX_ATTEMPTS = 1
DEFAULT_DEPLOYED_MAX_POOL_CONNECTIONS = 16


def _positive_setting(
    name: str,
    default: float | int,
    *,
    minimum: float = 0.0,
    as_int: bool = False,
) -> float | int:
    """Read a positive numeric environment setting with a clear error."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = int(value) if as_int else float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a number, got {value!r}") from error
    if parsed <= minimum:
        qualifier = "positive" if minimum == 0 else f"greater than {minimum}"
        raise ValueError(f"{name} must be {qualifier}, got {value!r}")
    return parsed


def _deployed_settings(
    *,
    read_timeout: float | None = None,
    connect_timeout: float | None = None,
    max_attempts: int | None = None,
) -> tuple[float, float, int, int]:
    """Resolve deployed-client settings, allowing safe operational overrides."""
    resolved_read_timeout = (
        read_timeout
        if read_timeout is not None
        else _positive_setting("FRAUD_AGENTCORE_READ_TIMEOUT", DEFAULT_DEPLOYED_READ_TIMEOUT)
    )
    resolved_connect_timeout = (
        connect_timeout
        if connect_timeout is not None
        else _positive_setting("FRAUD_AGENTCORE_CONNECT_TIMEOUT", DEFAULT_DEPLOYED_CONNECT_TIMEOUT)
    )
    resolved_max_attempts = (
        max_attempts
        if max_attempts is not None
        else _positive_setting(
            "FRAUD_AGENTCORE_MAX_ATTEMPTS",
            DEFAULT_DEPLOYED_MAX_ATTEMPTS,
            as_int=True,
        )
    )
    max_pool_connections = _positive_setting(
        "FRAUD_AGENTCORE_MAX_POOL_CONNECTIONS",
        DEFAULT_DEPLOYED_MAX_POOL_CONNECTIONS,
        as_int=True,
    )
    if resolved_read_timeout <= 0:
        raise ValueError("read_timeout must be positive")
    if resolved_connect_timeout <= 0:
        raise ValueError("connect_timeout must be positive")
    if resolved_max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    return (
        float(resolved_read_timeout),
        float(resolved_connect_timeout),
        int(resolved_max_attempts),
        int(max_pool_connections),
    )


@lru_cache(maxsize=16)
def _deployed_client(
    region: str,
    read_timeout: float,
    connect_timeout: float,
    max_attempts: int,
    max_pool_connections: int,
):
    """Create one thread-safe, pooled AgentCore data-plane client per config."""
    return boto3.client(
        "bedrock-agentcore",
        region_name=region,
        config=Config(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            max_pool_connections=max_pool_connections,
            # Standard retry mode uses bounded exponential backoff.  The
            # default is one total attempt to prevent duplicate agent turns;
            # callers may opt in to retries for an explicitly idempotent run.
            retries={"mode": "standard", "total_max_attempts": max_attempts},
            tcp_keepalive=True,
        ),
    )


def _status_runtime_arn() -> str | None:
    """Read the deployed Runtime ARN from ``agentcore status --json``.

    Returns None when the Runtime is not deployed. Exits with a message when
    the CLI is missing or fails.
    """
    try:
        result = subprocess.run(
            ["agentcore", "status", "--json", "--target", DEPLOY_TARGET],
            cwd=AGENT_ROOT,
            capture_output=True,
            text=True,
            timeout=STATUS_TIMEOUT_SECONDS,
            check=True,
        )
        status = json.loads(result.stdout)
    except FileNotFoundError:
        sys.exit("ERROR: the agentcore CLI is not installed. Set AGENT_ARN instead.")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        sys.exit(f"ERROR: 'agentcore status' failed: {error}. Set AGENT_ARN instead.")
    except json.JSONDecodeError as error:
        sys.exit(f"ERROR: 'agentcore status --json' printed invalid JSON: {error}")
    for resource in status.get("resources") or []:
        if resource.get("resourceType") == "runtime" and resource.get("name") == RUNTIME_NAME:
            return resource.get("arn") or None
    return None


def get_agent_config() -> tuple[str, str]:
    """Return ``(agent_arn, region)`` for the deployed Runtime.

    ``AGENT_ARN`` wins when set. Otherwise the ARN comes from the AgentCore
    CLI's deployed state. The region is the ARN's region.
    """
    arn = os.environ.get("AGENT_ARN", "").strip() or _status_runtime_arn()
    if not arn:
        sys.exit(
            f"ERROR: runtime '{RUNTIME_NAME}' is not deployed.\n"
            "Run './agent.sh deploy' first, or set AGENT_ARN."
        )
    parts = arn.split(":")
    if len(parts) < 6 or parts[2] != "bedrock-agentcore" or not parts[3]:
        raise ValueError(f"Not an AgentCore Runtime ARN: {arn}")
    return arn, parts[3]


def _handle_sse_event(
    event: str,
    content_parts: list[str],
    errors: list[str],
    stream: bool = True,
) -> None:
    """Dispatch one SSE event, printing ``chunk`` text live when streaming.

    ``json.loads`` already yields real newlines, so no unescaping is needed;
    any other event shape is ignored.
    """
    event = event.strip()
    if not event:
        return
    if event.startswith("data: "):
        event = event[6:]
    try:
        data = json.loads(event)
    except json.JSONDecodeError:
        return
    if data.get("type") == "chunk":
        text = data.get("data", "")
        if stream:
            print(text, end="", flush=True)
        content_parts.append(text)
    elif data.get("type") == "tool":
        # A labelled boundary where the agent called a Neo4j/memory tool.
        # Display-only: kept out of content_parts so the returned response
        # string stays the agent's prose, not the trace.
        if stream:
            name = data.get("name", "")
            print(f"\n\n  → {name}\n", end="\n", flush=True)
    elif "error" in data:
        # BedrockAgentCoreApp's event when the runtime's stream raises.
        error_type = data.get("error_type")
        errors.append(f"{error_type}: {data['error']}" if error_type else str(data["error"]))


def _consume_sse(chunks: Iterable[bytes], stream: bool) -> tuple[list[str], list[str]]:
    """Parse ``data: {...}\\n\\n`` events off a byte iterator as they arrive."""
    content_parts: list[str] = []
    errors: list[str] = []
    buffer = ""
    for raw in chunks:
        buffer += raw.decode("utf-8")
        while "\n\n" in buffer:
            event, buffer = buffer.split("\n\n", 1)
            _handle_sse_event(event, content_parts, errors, stream)
    if buffer.strip():
        _handle_sse_event(buffer, content_parts, errors, stream)
    if stream:
        print()  # terminate the streamed line
    return content_parts, errors


def _result(content_parts: list[str], errors: list[str]) -> dict:
    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "success", "response": "".join(content_parts)}


def invoke_deployed(
    payload: dict,
    stream: bool = True,
    *,
    read_timeout: float | None = None,
    connect_timeout: float | None = None,
    max_attempts: int | None = None,
) -> dict:
    """Invoke the deployed runtime via the boto3 ``bedrock-agentcore`` data plane.

    ``payload`` is sent as-is. The boto3 ``runtimeSessionId`` is a separate
    transport-level id (fresh per call); the runtime's memory scope keys off
    the ``user_id``/``session_id`` *inside* the payload, not this id.
    """
    agent_arn, region = get_agent_config()
    logger.info("Agent ARN: %s | region: %s | payload: %s", agent_arn, region, payload)

    (
        resolved_read_timeout,
        resolved_connect_timeout,
        resolved_max_attempts,
        max_pool_connections,
    ) = _deployed_settings(
        read_timeout=read_timeout,
        connect_timeout=connect_timeout,
        max_attempts=max_attempts,
    )
    client = _deployed_client(
        region,
        resolved_read_timeout,
        resolved_connect_timeout,
        resolved_max_attempts,
        max_pool_connections,
    )
    # The runtime user ID makes the Runtime fetch a workload access token for
    # the request. The agent needs it to read its credentials from AgentCore
    # Identity. A payload with no user_id gets HTTP 400 from the runtime.
    extra = {"runtimeUserId": payload["user_id"]} if payload.get("user_id") else {}
    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps(payload).encode(),
        qualifier="DEFAULT",
        **extra,
    )
    content_parts, errors = _consume_sse(response.get("response", []), stream)
    return _result(content_parts, errors)


def invoke_local(
    payload: dict,
    stream: bool = True,
    url: str = LOCAL_URL,
    timeout: int = 180,
) -> dict:
    """Invoke a locally running ``runtime_app.py`` over HTTP+SSE (port 7020)."""
    logger.info("Local URL: %s | payload: %s", url, payload)
    try:
        with httpx.Client(timeout=timeout) as c, c.stream("POST", url, json=payload) as r:
            if r.status_code != 200:
                r.read()
                return {
                    "status": "error",
                    "errors": [f"HTTP {r.status_code}: {r.text}"],
                }
            content_parts, errors = _consume_sse(r.iter_bytes(), stream)
        return _result(content_parts, errors)
    except httpx.ConnectError:
        return {
            "status": "error",
            "errors": [f"Could not connect to {url}. Start the agent first: uv run fraud-server"],
        }


def invoke(
    payload: dict,
    *,
    target: Target = "local",
    stream: bool = True,
    timeout: float | None = None,
    max_attempts: int | None = None,
) -> dict:
    """Invoke the runtime, choosing the transport by ``target``.

    ``timeout`` is the HTTP read timeout for either target.  ``max_attempts``
    applies only to AgentCore and includes the initial attempt.  Keep it at
    one unless duplicate agent turns are acceptable.
    """
    if target == "deployed":
        return invoke_deployed(
            payload,
            stream=stream,
            read_timeout=timeout,
            max_attempts=max_attempts,
        )
    return invoke_local(
        payload,
        stream=stream,
        timeout=int(timeout) if timeout is not None else 180,
    )
