"""SSE transport for the supervisor: a local and a deployed source.

The server streams ``data: {...}`` events: ``chunk``, ``agent``, ``tool``,
``error``, and ``complete``. The deployed source reads them with
``bedrock_agentcore.runtime.iter_events``. That reader takes only a boto3
response, so the local httpx source keeps a small parser of its own.
"""

import codecs
import json
import logging
import os
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from typing import Any

import boto3
import httpx
import urllib3.exceptions
from bedrock_agentcore import runtime
from botocore.config import Config

logger = logging.getLogger(__name__)

LOCAL_URL = f"http://localhost:{os.getenv('AGENT_PORT', '7071')}/invocations"

# A supervisor turn calls one or two specialists, each with several tool
# calls and adaptive thinking. botocore's 60 s default would cut it off.
READ_TIMEOUT_S = 300


@dataclass
class InvokeResult:
    """What one request returned."""

    text: str = ""
    specialists: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


EventHandler = Callable[[dict[str, Any]], None]


def iter_events(chunks: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    """Yield each SSE event from the local server as a dict, as the bytes arrive."""
    # Chunks can end in the middle of a multi-byte character.
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    for raw in chunks:
        buffer += decoder.decode(raw)
        while "\n\n" in buffer:
            message, buffer = buffer.split("\n\n", 1)
            if (event := _parse(message)) is not None:
                yield event
    buffer += decoder.decode(b"", final=True)
    if (event := _parse(buffer)) is not None:
        yield event


def _parse(message: str) -> dict[str, Any] | None:
    message = message.strip()
    if message.startswith("data: "):
        message = message[6:]
    if not message:
        return None
    try:
        event = json.loads(message)
    except json.JSONDecodeError:
        logger.warning("Skipping a non-JSON SSE message: %s", message[:200])
        return None
    return event if isinstance(event, dict) else None


def iter_deployed_events(response: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield each SSE event of an ``invoke_agent_runtime`` response as a dict."""
    for data in runtime.iter_events(response):
        if isinstance(data, dict):
            yield data
        elif isinstance(data, str):
            # The reader yields data that is not JSON as a string.
            logger.warning("Skipping a non-JSON SSE message: %s", data[:200])


def collect(events: Iterable[dict[str, Any]], on_event: EventHandler | None = None) -> InvokeResult:
    """Read every event into an ``InvokeResult``, calling ``on_event`` for each."""
    result = InvokeResult()
    parts: list[str] = []
    for event in events:
        if on_event:
            on_event(event)
        match event.get("type"):
            case "chunk":
                parts.append(event.get("data", ""))
            case "agent":
                result.specialists.append(event.get("name", ""))
            case "tool":
                result.tools.append(event.get("name", ""))
            case "error":
                result.errors.append(event.get("error", "Unknown error"))
    result.text = "".join(parts)
    return result


def print_event(event: dict[str, Any]) -> None:
    """Print one event as it arrives: answer text inline, routing on its own line."""
    match event.get("type"):
        case "chunk":
            print(event.get("data", ""), end="", flush=True)
        case "agent":
            print(f"\n[routed to {event.get('name')}]", flush=True)
        case "tool":
            print(f"  -> {event.get('name')}", flush=True)
        case "error":
            print(f"\nERROR: {event.get('error')}", flush=True)
        case "complete":
            print(flush=True)


@contextmanager
def stream_local(
    payload: dict[str, Any], session_id: str, url: str = LOCAL_URL
) -> Iterator[Iterator[dict[str, Any]]]:
    """Yield the events of one POST to a local server started with ``fleet-supervisor-server``."""
    headers = {"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id}
    with (
        httpx.Client(timeout=httpx.Timeout(READ_TIMEOUT_S, connect=10)) as client,
        client.stream("POST", url, json=payload, headers=headers) as response,
    ):
        response.raise_for_status()
        yield iter_events(response.iter_bytes())


@contextmanager
def stream_deployed(
    payload: dict[str, Any], agent_arn: str, region: str | None, session_id: str
) -> Iterator[Iterator[dict[str, Any]]]:
    """Yield the events of one call to the deployed runtime.

    The call names no Runtime user, because the agent needs no workload access
    token. So the caller needs only ``bedrock-agentcore:InvokeAgentRuntime``.

    A stream that fails partway raises urllib3's errors, not botocore's,
    because the AgentCore reader reads below botocore's response body.
    """
    client = boto3.client(
        "bedrock-agentcore",
        region_name=region,
        config=Config(read_timeout=READ_TIMEOUT_S, connect_timeout=10),
    )
    with closing(client):
        response = client.invoke_agent_runtime(
            agentRuntimeArn=agent_arn,
            # The service requires a session ID of at least 33 characters.
            runtimeSessionId=session_id,
            payload=json.dumps(payload).encode(),
            qualifier="DEFAULT",
        )
        with closing(response["response"]):
            yield iter_deployed_events(response)


def invoke_local(
    prompt: str,
    session_id: str | None = None,
    on_event: EventHandler | None = None,
    url: str = LOCAL_URL,
) -> InvokeResult:
    """POST to a local server started with ``uv run fleet-supervisor-server``."""
    with stream_local({"prompt": prompt}, session_id or str(uuid.uuid4()), url) as events:
        return collect(events, on_event)


def invoke_deployed(
    prompt: str,
    agent_arn: str,
    region: str,
    session_id: str | None = None,
    on_event: EventHandler | None = None,
) -> InvokeResult:
    """Invoke the deployed runtime and record a stream that fails partway as an error."""
    session_id = session_id or str(uuid.uuid4())
    with stream_deployed({"prompt": prompt}, agent_arn, region, session_id) as events:
        return collect(_error_on_stream_failure(events), on_event)


def _error_on_stream_failure(events: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """End the events with an ``error`` event when the stream fails partway."""
    try:
        yield from events
    except urllib3.exceptions.HTTPError as error:
        yield {"type": "error", "error": f"The deployed supervisor stream failed: {error}"}
