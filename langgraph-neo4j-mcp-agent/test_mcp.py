#!/usr/bin/env python3
"""
Simple MCP connectivity test using low-level MCP client.
Run with: uv run test_mcp.py
"""

import asyncio
import json
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def load_credentials() -> dict:
    """Load credentials from .mcp-credentials.json"""
    creds_file = Path(__file__).parent / ".mcp-credentials.json"
    if not creds_file.exists():
        raise FileNotFoundError(f"Credentials file not found: {creds_file}")
    with open(creds_file) as f:
        return json.load(f)


async def test_connection():
    """Test MCP connection and list tools."""
    creds = load_credentials()
    gateway_url = creds["gateway_url"]
    access_token = creds["access_token"]

    print(f"Gateway: {gateway_url[:60]}...")
    print(f"Token: {access_token[:30]}...")
    print("-" * 50)

    headers = {"Authorization": f"Bearer {access_token}"}

    async with streamablehttp_client(
        gateway_url,
        headers,
        timeout=timedelta(seconds=120),
        terminate_on_close=False,
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize
            print("Initializing session...")
            await session.initialize()
            print("Session initialized!")

            # List tools
            print("\nListing tools...")
            result = await session.list_tools()
            print(f"Found {len(result.tools)} tools:")
            for tool in result.tools:
                print(f"  - {tool.name}")

            # Build tool map
            tool_map = {}
            for t in result.tools:
                base = t.name.split("___")[-1] if "___" in t.name else t.name
                tool_map[base] = t.name

            # Test get-schema
            print("\n" + "-" * 50)
            print("Calling get-schema...")
            schema_tool = tool_map.get("get-schema", "get-schema")
            schema_result = await session.call_tool(schema_tool, {})
            for item in schema_result.content:
                if hasattr(item, "text"):
                    print(item.text[:500])

            # Test read-cypher
            print("\n" + "-" * 50)
            print("Calling read-cypher...")
            cypher_tool = tool_map.get("read-cypher", "read-cypher")
            query = "MATCH (n) RETURN labels(n) AS label, count(*) AS count"
            cypher_result = await session.call_tool(cypher_tool, {"query": query})
            for item in cypher_result.content:
                if hasattr(item, "text"):
                    print(item.text[:500])

    print("\n" + "=" * 50)
    print("All tests passed!")


if __name__ == "__main__":
    asyncio.run(test_connection())
