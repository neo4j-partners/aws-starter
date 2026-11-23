"""Offline checks for the Gateway MCP client."""

from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx

from core import factory

GATEWAY_URL = "https://gateway.example.com/mcp"


class McpClientTests(unittest.TestCase):
    @patch("core.factory.load_credentials", return_value={"gateway_url": GATEWAY_URL})
    def test_transport_uses_mcp_default_timeouts(self, _load) -> None:
        """A tool call that runs longer than 5 seconds must not time out."""
        seen: dict = {}

        @asynccontextmanager
        async def fake_streamable_http_client(url, http_client):
            seen["url"] = url
            seen["timeout"] = http_client.timeout
            yield (None, None, None)

        async def open_transport() -> None:
            client = factory.build_mcp_client()
            async with client._transport_callable():
                pass

        with patch(
            "mcp.client.streamable_http.streamable_http_client",
            fake_streamable_http_client,
        ):
            asyncio.run(open_transport())

        self.assertEqual(seen["url"], GATEWAY_URL)
        self.assertEqual(seen["timeout"].connect, 30.0)
        self.assertEqual(seen["timeout"].read, 300.0)

    @patch(
        "core.factory.get_active_credentials",
        return_value={"access_token": "token-1"},
    )
    def test_auth_sends_current_token(self, _creds) -> None:
        async def first_request() -> httpx.Request:
            flow = factory.GatewayTokenAuth().async_auth_flow(httpx.Request("POST", GATEWAY_URL))
            return await anext(flow)

        request = asyncio.run(first_request())
        self.assertEqual(request.headers["Authorization"], "Bearer token-1")


if __name__ == "__main__":
    unittest.main()
