"""One wire, two transports — the only place clients touch the network.

``fleet_graphrag.server`` serves four surfaces off ``/invocations`` and emits four
SSE event shapes: ``{"type": "chunk", "data": ...}``,
``{"type": "tool", "name": ...}``, ``{"type": "error", "error": ...}``,
``{"type": "complete"}``. Both transports below produce that same byte
stream, so a single parser handles them:

- :func:`invoke_local`    — HTTP POST to a locally running runtime (port 7070).
- :func:`invoke_deployed` — boto3 ``bedrock-agentcore`` data plane (deployed).

:func:`invoke` dispatches on ``target`` and returns the shape callers expect:
``{"status": "success", "response": "..."}`` or
``{"status": "error", "errors": [...]}``.
"""

from __future__ import annotations

import codecs
import json
import logging
import subprocess
import uuid
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Literal

import boto3
import httpx
from botocore.config import Config

logger = logging.getLogger(__name__)

# graphrag-agent/, two levels above fleet_graphrag/client/. The AgentCore CLI
# project lives in agentcore/ under it, so `agentcore status` runs from here
# regardless of the caller's cwd.
AGENT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_URL = "http://localhost:7070/invocations"

# A full agent turn with adaptive thinking and several tool calls can stream
# for minutes. botocore's 60 s default read timeout would cut it off.
DEPLOYED_READ_TIMEOUT_S = 300

# Reported when the stream stops partway through a character.
TRUNCATED_STREAM = "The response stream was cut off before it finished."

# `agentcore status` reads CloudFormation outputs. It returns in a few seconds.
STATUS_TIMEOUT_S = 60

# The Runtime name in agentcore/agentcore.json and the aws-targets.json entry
# that ./agent.sh deploy uses.
RUNTIME_NAME = "graphrag_agent"
DEPLOY_TARGET = "default"

Target = Literal["local", "deployed"]

# The header the Runtime sets from runtimeSessionId. BedrockAgentCoreApp reads
# it into RequestContext.session_id, so a local call can send it too.
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"


def new_session_id() -> str:
    """A fresh session ID. A UUID meets the Runtime's 33-character minimum."""
    return str(uuid.uuid4())


class DeploymentNotFoundError(RuntimeError):
    """The deployed Runtime ARN could not be read from ``agentcore status``."""


@lru_cache(maxsize=1)
def get_agent_config() -> tuple[str, str]:
    """Read ``(agent_arn, region)`` from ``agentcore status --json``.

    The AgentCore CLI resolves the Runtime ARN from the deployed stack of
    :data:`DEPLOY_TARGET`. The result is cached for the life of the process,
    so a load test runs the CLI once. A failure is not cached.
    Raises :class:`DeploymentNotFoundError` when the CLI is missing, the
    status call fails, or the Runtime is not deployed.
    """
    try:
        proc = subprocess.run(
            ["agentcore", "status", "--json", "--target", DEPLOY_TARGET],
            cwd=AGENT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=STATUS_TIMEOUT_S,
        )
    except FileNotFoundError as e:
        raise DeploymentNotFoundError(
            "The agentcore CLI is not installed. Install it with "
            "'npm install -g @aws/agentcore'."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise DeploymentNotFoundError(
            f"'agentcore status' did not finish in {STATUS_TIMEOUT_S} s."
        ) from e

    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise DeploymentNotFoundError(f"'agentcore status' failed: {detail}")
    return parse_status(proc.stdout)


def parse_status(output: str) -> tuple[str, str]:
    """Return ``(agent_arn, region)`` for :data:`RUNTIME_NAME` in status JSON.

    The Runtime must be listed by name with ``deploymentState`` "deployed"
    and an ARN. The region comes from the status output, which reports the
    target's region.
    """
    try:
        status = json.loads(output)
    except json.JSONDecodeError as e:
        raise DeploymentNotFoundError(
            f"'agentcore status --json' did not return JSON: {output.strip()}"
        ) from e
    if not isinstance(status, dict):
        raise DeploymentNotFoundError(
            f"'agentcore status --json' did not return an object: {output.strip()}"
        )

    region = status.get("region")
    if not isinstance(region, str) or not region:
        raise DeploymentNotFoundError(
            "'agentcore status --json' did not report the target region."
        )

    resources = status.get("resources")
    if not isinstance(resources, list):
        resources = []
    runtime = next(
        (
            resource
            for resource in resources
            if isinstance(resource, dict)
            and resource.get("resourceType") == "runtime"
            and resource.get("name") == RUNTIME_NAME
        ),
        None,
    )
    if runtime is None:
        raise DeploymentNotFoundError(
            f"The project has no Runtime named '{RUNTIME_NAME}'."
        )
    arn = runtime.get("arn")
    if runtime.get("deploymentState") != "deployed" or not isinstance(arn, str) or not arn:
        raise DeploymentNotFoundError(
            f"Runtime '{RUNTIME_NAME}' is not deployed to target "
            f"'{DEPLOY_TARGET}'. Run './agent.sh deploy' first."
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
    anything that is not one of the four known shapes is ignored.
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
        # A labelled boundary where the agent called a retriever tool.
        # Display-only: kept out of content_parts so the returned response
        # string stays the agent's prose, not the trace.
        if stream:
            name = data.get("name", "")
            print(f"\n\n  → {name}\n", end="\n", flush=True)
    elif data.get("type") == "error":
        errors.append(data.get("error", "Unknown error"))


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _consume_sse(
    chunks: Iterable[bytes], stream: bool
) -> tuple[list[str], list[str]]:
    """Parse ``data: {...}\\n\\n`` events off a byte iterator as they arrive.

    Lines may end in ``\\r\\n``, ``\\r``, or ``\\n``, as the SSE format allows.
    """
    content_parts: list[str] = []
    errors: list[str] = []
    buffer = ""
    # A trailing \r may be the first half of a \r\n split across two chunks,
    # so it waits for the next chunk before it is normalized.
    held_cr = ""
    # A multibyte character can straddle two chunks. The incremental decoder
    # holds the partial bytes until the rest of the character arrives. Invalid
    # bytes become U+FFFD instead of ending the stream.
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    for raw in chunks:
        text = held_cr + decoder.decode(raw)
        held_cr = "\r" if text.endswith("\r") else ""
        buffer += _normalize_newlines(text.removesuffix(held_cr))
        while "\n\n" in buffer:
            event, buffer = buffer.split("\n\n", 1)
            _handle_sse_event(event, content_parts, errors, stream)
    # Bytes still pending here are the start of a character the stream never
    # finished, so the response was cut off.
    pending_bytes, _ = decoder.getstate()
    buffer += _normalize_newlines(held_cr + decoder.decode(b"", final=True))
    if buffer.strip():
        _handle_sse_event(buffer, content_parts, errors, stream)
    if pending_bytes:
        logger.warning("Response stream ended inside a UTF-8 character")
        errors.append(TRUNCATED_STREAM)
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
    session_id: str | None = None,
) -> dict:
    """Invoke the deployed runtime via the boto3 ``bedrock-agentcore`` data plane.

    Calls that pass the same ``session_id`` share conversation memory. Without
    one, each call starts a new session.
    """
    agent_arn, region = get_agent_config()
    logger.info("Agent ARN: %s | region: %s | payload: %s", agent_arn, region, payload)

    client = boto3.client(
        "bedrock-agentcore",
        region_name=region,
        config=Config(read_timeout=DEPLOYED_READ_TIMEOUT_S),
    )
    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=session_id or new_session_id(),
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
    session_id: str | None = None,
) -> dict:
    """Invoke a locally running ``fleet_graphrag.server`` over HTTP+SSE (port 7070).

    ``session_id`` goes in the AgentCore session header. Without it, the
    server starts a new session for the call.
    """
    logger.info("Local URL: %s | payload: %s", url, payload)
    headers = {SESSION_HEADER: session_id} if session_id else {}
    try:
        with (
            httpx.Client(timeout=timeout) as c,
            c.stream("POST", url, json=payload, headers=headers) as r,
        ):
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
    session_id: str | None = None,
) -> dict:
    """Invoke the runtime, choosing the transport by ``target``.

    ``payload`` is passed through verbatim, so ``{"prompt": "..."}`` runs the
    full agent and ``{"mode": "schema" | "graph_query" | "vector_search", ...}``
    hits the direct surfaces of the same runtime. Calls with the same
    ``session_id`` share conversation memory.
    """
    if target == "deployed":
        return invoke_deployed(payload, stream=stream, session_id=session_id)
    return invoke_local(payload, stream=stream, session_id=session_id)
