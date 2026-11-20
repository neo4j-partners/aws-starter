"""Gateway tools that survive the end of an MCP session.

The Gateway can end the MCP session at any time, for example when it
restarts. A call made while the session is down fails in one of two ways:

- A call already in flight returns an error ``MCPToolResult``.
- A later call raises ``MCPClientInitializationError`` before
  ``MCPClient.call_tool_async`` reaches its own ``try``.

:class:`GatewayTool` catches both. It asks for a rebuilt client once and
retries the call once. If the retry also fails, or the rebuild fails, the
model gets :data:`UNAVAILABLE_RESULT`. The next request rebuilds again.
"""

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextvars import ContextVar
from typing import Any

from strands.tools.mcp import MCPAgentTool, MCPClient
from strands.types.events import ToolResultEvent
from strands.types.exceptions import MCPClientInitializationError
from strands.types.tools import AgentTool, ToolGenerator, ToolResult, ToolSpec, ToolUse

logger = logging.getLogger(__name__)

# The AgentCore session ID of the request being served, for log lines. The
# entrypoint sets it. Tool calls run in tasks that copy the context, so they
# see it too.
REQUEST_SESSION_ID: ContextVar[str] = ContextVar("request_session_id", default="-")

# The same wording as the graphrag agent's tools, so both agents tell the
# model the same thing.
UNAVAILABLE_RESULT = (
    "The graph database is unavailable right now. Tell the user the data could not be reached."
)


def session_is_running(client: MCPClient) -> bool:
    """Report whether the MCP client's session is still up.

    Strands has no public health check. ``_is_session_active`` is the check
    ``list_tools_sync`` and ``call_tool_async`` make before they run, so it
    matches when tool calls would start failing. tests/test_server.py pins it.
    """
    return client._is_session_active()


def stop_quietly(client: MCPClient) -> None:
    """Stop the client, logging a failure so it cannot hide another error."""
    try:
        client.stop(None, None, None)
    except Exception:
        logger.exception("Error while stopping the MCP client")


class GatewayConnection:
    """One started MCP client and its filtered tools, by name.

    Each tool call holds the connection while it runs. A rebuild retires the
    old connection, and the client stops when the last holder lets go, so a
    rebuild never stops a client under a running call, and no client thread
    outlives its last caller.
    """

    def __init__(self, client: MCPClient, tools: Sequence[MCPAgentTool]) -> None:
        self.client = client
        self.tools: dict[str, MCPAgentTool] = {tool.tool_name: tool for tool in tools}
        # Guards the counters. Holders run on request event loops, and
        # retire() runs on the rebuild's worker thread.
        self._lock = threading.Lock()
        self._holders = 0
        self._retired = False
        self._stopped = False

    def is_running(self) -> bool:
        return session_is_running(self.client)

    def _claim_stop(self) -> bool:
        """Return True once, for the caller that must stop the client. Hold the lock."""
        if self._retired and self._holders == 0 and not self._stopped:
            self._stopped = True
            return True
        return False

    def stop(self) -> None:
        """Stop the client now. For a connection that never served a call."""
        with self._lock:
            self._retired = True
            should_stop = self._claim_stop()
        if should_stop:
            stop_quietly(self.client)

    def retire(self) -> None:
        """Mark the connection replaced. Stop the client if no call holds it."""
        with self._lock:
            self._retired = True
            should_stop = self._claim_stop()
        if should_stop:
            logger.info("Stopped the replaced MCP client")
            stop_quietly(self.client)

    @contextlib.asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        """Keep the client running for one tool call."""
        with self._lock:
            self._holders += 1
        try:
            yield
        finally:
            with self._lock:
                self._holders -= 1
                should_stop = self._claim_stop()
            if should_stop:
                logger.info("Stopped the replaced MCP client after its last call")
                # stop() joins the client's thread, so keep it off the event loop.
                await asyncio.to_thread(stop_quietly, self.client)


# Returns the current connection, or None after a failed rebuild.
CurrentConnection = Callable[[], GatewayConnection | None]
# Returns a running connection other than ``stale``, rebuilding only when
# ``stale`` is still the current one.
Reconnect = Callable[[GatewayConnection | None], Awaitable[GatewayConnection]]


class _SessionEnded(Exception):
    """The call failed because the MCP session was down."""

    def __init__(self, cause: str) -> None:
        super().__init__(cause)
        self.cause = cause


class GatewayTool(AgentTool):
    """A Gateway tool that reconnects and retries once if the session ended.

    The spec is taken from the first client's tool and kept, so a rebuild
    never changes what the model sees. Each call looks up the tool by name
    on the current connection.
    """

    def __init__(
        self, tool: MCPAgentTool, current: CurrentConnection, reconnect: Reconnect
    ) -> None:
        super().__init__()
        self._name = tool.tool_name
        self._spec = tool.tool_spec
        self._current = current
        self._reconnect = reconnect

    @property
    def tool_name(self) -> str:
        return self._name

    @property
    def tool_spec(self) -> ToolSpec:
        return self._spec

    @property
    def tool_type(self) -> str:
        return "python"

    async def stream(
        self, tool_use: ToolUse, invocation_state: dict[str, Any], **kwargs: Any
    ) -> ToolGenerator:
        result = await self._call_with_retry(tool_use, invocation_state, kwargs)
        yield ToolResultEvent(result)

    async def _call_with_retry(
        self, tool_use: ToolUse, invocation_state: dict[str, Any], kwargs: dict[str, Any]
    ) -> ToolResult:
        connection = self._current()
        try:
            if connection is None:
                raise _SessionEnded("NoConnection")
            return await self._call(connection, tool_use, invocation_state, kwargs)
        except _SessionEnded as ended:
            logger.warning(
                "%s: the Gateway MCP session ended (session=%s, cause=%s); "
                "reconnecting and retrying once",
                self._name,
                REQUEST_SESSION_ID.get(),
                ended.cause,
            )

        try:
            connection = await self._reconnect(connection)
        except Exception as error:
            # The rebuild can fail in many ways: auth, network, or an empty
            # tool list. None of them may reach the model.
            logger.warning(
                "%s: reconnecting to the Gateway failed (session=%s, cause=%s)",
                self._name,
                REQUEST_SESSION_ID.get(),
                type(error).__name__,
            )
            logger.debug("Reconnect failure details", exc_info=error)
            return self._unavailable(tool_use)

        try:
            return await self._call(connection, tool_use, invocation_state, kwargs)
        except _SessionEnded as ended:
            logger.warning(
                "%s: the retry failed too (session=%s, cause=%s)",
                self._name,
                REQUEST_SESSION_ID.get(),
                ended.cause,
            )
            return self._unavailable(tool_use)

    async def _call(
        self,
        connection: GatewayConnection,
        tool_use: ToolUse,
        invocation_state: dict[str, Any],
        kwargs: dict[str, Any],
    ) -> ToolResult:
        """Run the tool once. Raise :class:`_SessionEnded` if the session was down."""
        tool = connection.tools.get(self._name)
        if tool is None:
            logger.warning("%s is not in the rebuilt Gateway tool list", self._name)
            return self._unavailable(tool_use)
        result: ToolResult | None = None
        async with connection.hold():
            try:
                async for event in tool.stream(tool_use, invocation_state, **kwargs):
                    if isinstance(event, ToolResultEvent):
                        result = event.tool_result
            except MCPClientInitializationError as error:
                raise _SessionEnded(type(error).__name__) from error
        if result is None:
            logger.warning("%s returned no result", self._name)
            return self._unavailable(tool_use)
        # Strands turns an in-flight failure into an error result and logs the
        # exception itself, so only the result is left to check here.
        if result["status"] == "error" and not connection.is_running():
            raise _SessionEnded("ErrorResultWhileSessionDown")
        return result

    @staticmethod
    def _unavailable(tool_use: ToolUse) -> ToolResult:
        return {
            "toolUseId": tool_use["toolUseId"],
            "status": "error",
            "content": [{"text": UNAVAILABLE_RESULT}],
        }
