"""One wire, two transports — the only place clients touch the network.

``server/runtime_app.py`` serves ``/invocations`` and emits four SSE event
shapes: ``{"type": "chunk", "data": ...}``, ``{"type": "tool", "name": ...}``,
``{"type": "error", "error": ...}``, ``{"type": "complete"}``. Both transports
below produce that same byte stream, so a single parser handles them:

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
import sys
import uuid
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Literal

import boto3
import httpx
import yaml
from botocore.config import Config

logger = logging.getLogger(__name__)

# finance-agent/ is the parent of client/; .bedrock_agentcore.yaml and the
# default local URL both anchor here regardless of the caller's cwd.
AGENT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_URL = "http://localhost:7020/invocations"

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
        else _positive_setting(
            "FINANCE_AGENTCORE_READ_TIMEOUT", DEFAULT_DEPLOYED_READ_TIMEOUT
        )
    )
    resolved_connect_timeout = (
        connect_timeout
        if connect_timeout is not None
        else _positive_setting(
            "FINANCE_AGENTCORE_CONNECT_TIMEOUT", DEFAULT_DEPLOYED_CONNECT_TIMEOUT
        )
    )
    resolved_max_attempts = (
        max_attempts
        if max_attempts is not None
        else _positive_setting(
            "FINANCE_AGENTCORE_MAX_ATTEMPTS",
            DEFAULT_DEPLOYED_MAX_ATTEMPTS,
            as_int=True,
        )
    )
    max_pool_connections = _positive_setting(
        "FINANCE_AGENTCORE_MAX_POOL_CONNECTIONS",
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


def get_agent_config() -> tuple[str, str]:
    """Read ``(agent_arn, region)`` from ``.bedrock_agentcore.yaml``.

    The file is created by ``./agent.sh configure``. Resolved against the
    agent root so it works no matter where the client is invoked from.
    """
    config_file = AGENT_ROOT / ".bedrock_agentcore.yaml"
    try:
        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("%s not found", config_file)
        print(f"ERROR: {config_file} not found")
        print("")
        print("Run './agent.sh configure' and './agent.sh deploy' first")
        sys.exit(1)

    default_agent = config.get("default_agent")
    if not default_agent:
        raise ValueError(f"default_agent not found in {config_file}")

    agent_config = config.get("agents", {}).get(default_agent, {})
    arn = agent_config.get("bedrock_agentcore", {}).get("agent_arn")
    region = agent_config.get("aws", {}).get("region", "us-west-2")

    if not arn:
        raise ValueError(
            f"agent_arn not found for agent '{default_agent}' in {config_file}"
        )
    return arn, region


def _handle_sse_event(
    event: str,
    content_parts: list[str],
    errors: list[str],
    stream: bool = True,
) -> None:
    """Dispatch one SSE event, printing ``chunk`` text live when streaming.

    ``json.loads`` already yields real newlines, so no unescaping is needed;
    anything that is not one of the three known shapes is ignored.
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
    elif data.get("type") == "error":
        errors.append(data.get("error", "Unknown error"))


def _consume_sse(
    chunks: Iterable[bytes], stream: bool
) -> tuple[list[str], list[str]]:
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
    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps(payload).encode(),
        qualifier="DEFAULT",
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
        with httpx.Client(timeout=timeout) as c:
            with c.stream("POST", url, json=payload) as r:
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
            "errors": [
                f"Could not connect to {url}. Start the agent first: "
                f"./agent.sh start"
            ],
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
