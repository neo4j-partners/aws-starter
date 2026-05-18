"""Framework-agnostic Neo4j schema fetch + process-level cache.

The schema is retrieved over a raw MCP session (not via any framework's tool
client) so both the LangGraph and Strands variants share one implementation
and one cache. It is fetched once on the first request and reused for the
life of the process.
"""

import logging
from datetime import timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)

_CACHED_SCHEMA: str | None = None


async def fetch_schema(gateway_url: str, access_token: str) -> str:
    """Fetch the schema from the MCP server via the Gateway."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with streamablehttp_client(
        gateway_url,
        headers,
        timeout=timedelta(seconds=60),
        terminate_on_close=False,
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Build a base-name -> full-name map to handle Gateway prefixing
            # (tools come back as ``{target}___{tool}``).
            result = await session.list_tools()
            tool_map = {}
            for tool in result.tools:
                full_name = tool.name
                if "___" in full_name:
                    base_name = full_name.split("___", 1)[1]
                else:
                    base_name = full_name
                tool_map[base_name] = full_name

            schema_tool = tool_map.get("get-schema")
            if not schema_tool:
                return "Schema not available"

            result = await session.call_tool(schema_tool, {})
            if result.content:
                return result.content[0].text
            return "Schema not available"


async def get_cached_schema(gateway_url: str, access_token: str) -> str:
    """Return the cached schema, fetching it once on the first call."""
    global _CACHED_SCHEMA

    if _CACHED_SCHEMA is None:
        logger.info("Fetching schema from MCP server (first request)...")
        _CACHED_SCHEMA = await fetch_schema(gateway_url, access_token)
        logger.info(f"Schema cached ({len(_CACHED_SCHEMA)} bytes)")

    return _CACHED_SCHEMA
