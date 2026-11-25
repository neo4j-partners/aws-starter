"""Map Strands stream events to the client SSE event format.

The client events:

- ``{"type": "chunk", "data": ...}``: supervisor answer text
- ``{"type": "agent", "name": ...}``: a specialist was called
- ``{"type": "tool", "name": ...}``: a graph tool was called
- ``{"type": "tool_complete", "call_id": ..., "status": ..., "duration_ms": ...}``:
  a specialist or graph tool call finished. A successful graph query also
  carries ``evidence_ids``, the fleet IDs in its result. Sent only with trace on.
- ``{"type": "followups", "questions": [...]}``: up to three suggested follow-up
  questions, sent by the server after the answer and before ``complete``. Sent
  only when the payload has ``"followups": true``, and only when the follow-up
  call succeeds. Clients that do not know the event ignore it.
- ``{"type": "complete"}`` and ``{"type": "error", "error": ...}``: sent by the server

With trace on, the ``agent`` and ``tool`` events also carry ``call_id`` and
``parent_id``. A graph tool's ``parent_id`` is the specialist call that ran it.
"""

import re
from collections.abc import AsyncIterator, Iterator
from time import monotonic
from typing import Any

from strands import Agent

from fleet_supervisor.core.agents import SPECIALIST_NAMES
from fleet_supervisor.core.tool_stream import (
    RESULT_EVENT_KEY,
    TRACE_STATE_KEY,
    observe_tool_results,
)

FLEET_ID = re.compile(
    r"\b(?:AC\d{4,}(?:-S\d{2}(?:-C\d{2})?)?|ME\d{4,}|FL\d{5,}|N\d{5}[A-Z]?)(?![\w-])"
)


class EventMapper:
    """Turn one request's Strands events into client events.

    Strands repeats ``current_tool_use`` on every input delta while a tool
    call is assembled, so each call is reported once per ``toolUseId``.
    """

    def __init__(self, *, trace: bool = False) -> None:
        self._seen_tool_ids: set[str] = set()
        self.specialists: list[str] = []
        self._trace = trace
        self._started: dict[str, tuple[str, float]] = {}

    def stream(self, agent: Agent, prompt: str) -> AsyncIterator[dict[str, Any]]:
        """Start the agent stream with individual tool results when requested."""
        if self._trace:
            observe_tool_results(agent)
            return agent.stream_async(prompt, invocation_state={TRACE_STATE_KEY: True})
        return agent.stream_async(prompt)

    def map(self, event: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yield the client events for one Strands event."""
        if stream := event.get("tool_stream_event"):
            # Events from inside a specialist. Only its graph tool calls are
            # forwarded. Its text reaches the user through the supervisor.
            inner = stream.get("data")
            if isinstance(inner, dict):
                yield from self._map_tools(inner, stream.get("tool_use", {}).get("toolUseId"))
            return

        if "data" in event:
            yield {"type": "chunk", "data": event["data"]}
        else:
            yield from self._map_tools(event, None)

    def _map_tools(self, event: dict[str, Any], parent_id: str | None) -> Iterator[dict[str, Any]]:
        if tool_use := event.get("current_tool_use"):
            yield from self._tool_event(tool_use, parent_id)
        elif self._trace:
            if result := event.get(RESULT_EVENT_KEY):
                yield from self._tool_result(result, parent_id, event["duration_ms"])
            elif message := event.get("message"):
                # The result message also covers calls that were cancelled before execution.
                for block in message.get("content", []):
                    if result := block.get("toolResult"):
                        yield from self._tool_result(result, parent_id)

    def _tool_event(
        self, tool_use: dict[str, Any], parent_id: str | None = None
    ) -> Iterator[dict[str, Any]]:
        tool_id = tool_use.get("toolUseId")
        name = tool_use.get("name")
        if not tool_id or not name:
            return
        call_id = f"{parent_id}/{tool_id}" if parent_id else tool_id
        if call_id in self._seen_tool_ids:
            return
        self._seen_tool_ids.add(call_id)
        details = {}
        if self._trace:
            self._started[call_id] = (name, monotonic())
            details = {"call_id": call_id, "parent_id": parent_id}
        if agent_name := SPECIALIST_NAMES.get(name):
            self.specialists.append(agent_name)
            yield {"type": "agent", "name": agent_name, **details}
        else:
            yield {"type": "tool", "name": name, **details}

    def _tool_result(
        self, result: dict[str, Any], parent_id: str | None, duration_ms: int | None = None
    ) -> Iterator[dict[str, Any]]:
        tool_id = result["toolUseId"]
        call_id = f"{parent_id}/{tool_id}" if parent_id else tool_id
        if not (started := self._started.pop(call_id, None)):
            return
        name, start = started
        failed = result["status"] == "error"
        event = {
            "type": "tool_complete",
            "call_id": call_id,
            "status": "error" if failed else "success",
            "duration_ms": duration_ms
            if duration_ms is not None
            else round((monotonic() - start) * 1000),
        }
        if name == "graph_query_tool" and not failed:
            # The graph query returns row text. Send only the fleet IDs in it.
            content = result.get("content", [])
            refs = dict.fromkeys(FLEET_ID.findall(str(content)[:100_000]))
            event["evidence_ids"] = list(refs)[:30]
        yield event
