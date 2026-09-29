"""One wire, two transports — the only place clients touch the network.

``runtime_app.py`` serves four surfaces off ``/invocations`` and emits four
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

import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Iterable, Literal

import boto3
import httpx
import yaml

logger = logging.getLogger(__name__)

# fleet-agent/ is the parent of client/; .bedrock_agentcore.yaml and the
# default local URL both anchor here regardless of the caller's cwd.
AGENT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_URL = "http://localhost:7070/invocations"

Target = Literal["local", "deployed"]


def get_agent_config() -> tuple[str, str]:
    """Read ``(agent_arn, region)`` from ``.bedrock_agentcore.yaml``.

    The file is created by ``./agent.sh configure``. Resolved against the
    agent root so it works no matter where the client is invoked from.
    """
    config_file = AGENT_ROOT / ".bedrock_agentcore.yaml"
    try:
        with config_file.open(encoding="utf-8") as f:
            config = yaml.safe_load(f)

        default_agent = config.get("default_agent")
        if not default_agent:
            raise ValueError(f"default_agent not found in {config_file}")

        agent_config = config.get("agents", {}).get(default_agent, {})
        arn = agent_config.get("bedrock_agentcore", {}).get("agent_arn")
        region = agent_config.get("aws", {}).get("region", "us-east-1")

        if not arn:
            raise ValueError(
                f"agent_arn not found for agent '{default_agent}' in "
                f"{config_file}"
            )
        return arn, region
    except FileNotFoundError:
        logger.error("%s not found", config_file)
        print(f"ERROR: {config_file} not found")
        print("")
        print("Run './agent.sh configure' and './agent.sh deploy' first")
        sys.exit(1)


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


def invoke_deployed(payload: dict, stream: bool = True) -> dict:
    """Invoke the deployed runtime via the boto3 ``bedrock-agentcore`` data plane."""
    agent_arn, region = get_agent_config()
    logger.info("Agent ARN: %s | region: %s | payload: %s", agent_arn, region, payload)

    client = boto3.client("bedrock-agentcore", region_name=region)
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
    """Invoke a locally running ``runtime_app.py`` over HTTP+SSE (port 7070)."""
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
) -> dict:
    """Invoke the runtime, choosing the transport by ``target``.

    ``payload`` is passed through verbatim, so ``{"prompt": "..."}`` runs the
    full agent and ``{"mode": "schema" | "graph_query" | "vector_search", ...}``
    hits the direct surfaces of the same runtime.
    """
    if target == "deployed":
        return invoke_deployed(payload, stream=stream)
    return invoke_local(payload, stream=stream)
