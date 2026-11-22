#!/usr/bin/env python3
"""
MCP connectivity test using FastMCP client.
Run with: uv run python tests/test_fastmcp.py
"""

import asyncio
import json
from pathlib import Path

CREDENTIALS_FILE = Path(__file__).parent.parent / ".mcp-credentials.json"


def load_credentials() -> dict:
    """Load credentials from .mcp-credentials.json"""
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(f"Credentials file not found: {CREDENTIALS_FILE}")
    with open(CREDENTIALS_FILE) as f:
        return json.load(f)


def test_connection():
    """Run the live Gateway check. pytest calls this without an async plugin."""
    # pytest is imported here so the script runs without it. The test skips
    # when the optional FastMCP client or the credentials from a deployed MCP
    # server are missing.
    import pytest

    pytest.importorskip("fastmcp")
    if not CREDENTIALS_FILE.exists():
        pytest.skip("needs .mcp-credentials.json from a deployed MCP server")
    asyncio.run(check_connection())


async def check_connection():
    """Test MCP connection using FastMCP client."""
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    creds = load_credentials()
    gateway_url = creds["gateway_url"]
    access_token = creds["access_token"]

    print(f"Gateway: {gateway_url[:60]}...")
    print(f"Token: {access_token[:30]}...")
    print("-" * 50)

    # Create FastMCP transport and client
    transport = StreamableHttpTransport(
        url=gateway_url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    client = Client(transport)

    async with client:
        # List tools
        print("Listing tools...")
        tools = await client.list_tools()
        print(f"Found {len(tools)} tools:")
        for tool in tools:
            print(f"  - {tool.name}")

        # Build tool map (handle Gateway prefix)
        tool_map = {}
        for t in tools:
            base = t.name.split("___")[-1] if "___" in t.name else t.name
            tool_map[base] = t.name

        # Test get_neo4j_schema
        print("\n" + "-" * 50)
        print("Calling get_neo4j_schema...")
        schema_tool = tool_map.get("get_neo4j_schema", "get_neo4j_schema")
        result = await client.call_tool(schema_tool, {})
        print(f"Result type: {type(result).__name__}")
        if hasattr(result, "content"):
            for item in result.content:
                if hasattr(item, "text"):
                    print(item.text[:500])
        else:
            print(result)

        # Test read_neo4j_cypher
        print("\n" + "-" * 50)
        print("Calling read_neo4j_cypher...")
        cypher_tool = tool_map.get("read_neo4j_cypher", "read_neo4j_cypher")
        query = "MATCH (n) RETURN labels(n) AS label, count(*) AS count"
        result = await client.call_tool(cypher_tool, {"query": query})
        if hasattr(result, "content"):
            for item in result.content:
                if hasattr(item, "text"):
                    print(item.text[:500])
        else:
            print(result)

    print("\n" + "=" * 50)
    print("All tests passed!")


if __name__ == "__main__":
    asyncio.run(check_connection())
