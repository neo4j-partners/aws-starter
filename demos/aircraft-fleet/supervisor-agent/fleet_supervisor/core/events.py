"""Map Strands stream events to the client SSE event format.

The client events:

- ``{"type": "chunk", "data": ...}``: supervisor answer text
- ``{"type": "agent", "name": ...}``: a specialist was called
- ``{"type": "tool", "name": ...}``: a graph tool was called
- ``{"type": "complete"}`` and ``{"type": "error", "error": ...}``: sent by the server
"""

from collections.abc import Iterator
from typing import Any

from fleet_supervisor.core.agents import SPECIALIST_NAMES


class EventMapper:
    """Turn one request's Strands events into client events.

    Strands repeats ``current_tool_use`` on every input delta while a tool
    call is assembled, so each call is reported once per ``toolUseId``.
    """

    def __init__(self) -> None:
        self._seen_tool_ids: set[str] = set()
        self.specialists: list[str] = []

    def map(self, event: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yield the client events for one Strands event."""
        if stream := event.get("tool_stream_event"):
            # Events from inside a specialist. Only its graph tool calls are
            # forwarded. Its text reaches the user through the supervisor.
            inner = stream.get("data")
            if isinstance(inner, dict) and (tool_use := inner.get("current_tool_use")):
                yield from self._tool_event(tool_use)
            return

        if "data" in event:
            yield {"type": "chunk", "data": event["data"]}
        elif tool_use := event.get("current_tool_use"):
            yield from self._tool_event(tool_use)

    def _tool_event(self, tool_use: dict[str, Any]) -> Iterator[dict[str, Any]]:
        tool_id = tool_use.get("toolUseId")
        name = tool_use.get("name")
        if not tool_id or not name or tool_id in self._seen_tool_ids:
            return
        self._seen_tool_ids.add(tool_id)
        if agent_name := SPECIALIST_NAMES.get(name):
            self.specialists.append(agent_name)
            yield {"type": "agent", "name": agent_name}
        else:
            yield {"type": "tool", "name": name}
