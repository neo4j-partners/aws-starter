"""Offline checks for the Gateway MCP client."""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

import httpx

from core import factory
from core.credentials import IdentityCredentials

GATEWAY_URL = "https://gateway.example.com/mcp"
IDENTITY = IdentityCredentials(GATEWAY_URL, "FraudMemory_default_fraud-gateway", ("s/1",))


def jwt(exp: float) -> str:
    """An unsigned JWT with only an exp claim."""
    body = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"h.{body}.sig"


class McpClientTests(unittest.TestCase):
    @patch("core.factory.identity_credentials", return_value=None)
    @patch("core.factory.load_credentials", return_value={"gateway_url": GATEWAY_URL})
    def test_transport_uses_mcp_default_timeouts(self, _load, _identity) -> None:
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


class JwtDeadlineTests(unittest.TestCase):
    def test_refreshes_a_margin_before_exp(self) -> None:
        deadline = factory.jwt_deadline(jwt(time.time() + 3600))
        expected = time.monotonic() + 3600 - factory.TOKEN_EXPIRY_MARGIN_S
        self.assertAlmostEqual(deadline, expected, delta=2)

    def test_unreadable_token_gets_a_short_life(self) -> None:
        with self.assertLogs("core.factory", "WARNING"):
            deadline = factory.jwt_deadline("not-a-jwt")
        expected = time.monotonic() + factory.UNREADABLE_EXPIRY_MAX_AGE_S
        self.assertAlmostEqual(deadline, expected, delta=2)


class IdentityGatewayTokensTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Mock()
        self.client.get_token = AsyncMock(
            side_effect=[jwt(time.time() + 3600), jwt(time.time() + 7200)]
        )
        patcher = patch(
            "bedrock_agentcore.services.identity.IdentityClient", return_value=self.client
        )
        self.identity_client = patcher.start()
        self.addCleanup(patcher.stop)
        self.tokens = factory.IdentityGatewayTokens(IDENTITY)

    def test_fetches_once_and_reuses_the_token(self) -> None:
        first = self.tokens.get("wat-1")
        second = self.tokens.get("wat-2")
        self.assertEqual(first, second)
        self.client.get_token.assert_awaited_once_with(
            provider_name=IDENTITY.provider_name,
            agent_identity_token="wat-1",
            scopes=["s/1"],
            auth_flow="M2M",
            force_authentication=False,
        )
        self.identity_client.assert_called_once_with(factory.AWS_REGION)

    def test_rejected_token_forces_a_new_one(self) -> None:
        first = self.tokens.get("wat-1")
        second = self.tokens.get("wat-1", first)
        self.assertNotEqual(first, second)
        self.assertTrue(self.client.get_token.await_args.kwargs["force_authentication"])

    def test_rejecting_a_replaced_token_reuses_the_new_one(self) -> None:
        first = self.tokens.get("wat-1")
        second = self.tokens.get("wat-1", first)
        self.assertEqual(self.tokens.get("wat-1", first), second)
        self.assertEqual(self.client.get_token.await_count, 2)

    def test_expired_token_is_replaced(self) -> None:
        first = self.tokens.get("wat-1")
        self.tokens._token = factory.AccessToken(first, time.monotonic() - 1)
        self.assertNotEqual(self.tokens.get("wat-1"), first)
        self.assertFalse(self.client.get_token.await_args.kwargs["force_authentication"])

    def test_concurrent_first_calls_share_one_fetch(self) -> None:
        results: list[str] = []
        threads = [
            threading.Thread(target=lambda: results.append(self.tokens.get("wat")))
            for _ in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(set(results)), 1)
        self.client.get_token.assert_awaited_once()


class IdentityGatewayAuthTests(unittest.TestCase):
    def run_flow(self, statuses: list[int]) -> tuple[list[str], Mock]:
        tokens = Mock()
        tokens.get.side_effect = ["token-1", "token-2"]
        auth = factory.IdentityGatewayAuth(tokens, "wat-1")
        sent: list[str] = []

        async def drive() -> None:
            flow = auth.async_auth_flow(httpx.Request("POST", GATEWAY_URL))
            request = await anext(flow)
            for status in statuses:
                sent.append(request.headers["Authorization"])
                try:
                    request = await flow.asend(httpx.Response(status))
                except StopAsyncIteration:
                    return

        asyncio.run(drive())
        return sent, tokens

    def test_sends_the_identity_token(self) -> None:
        sent, tokens = self.run_flow([200])
        self.assertEqual(sent, ["Bearer token-1"])
        tokens.get.assert_called_once_with("wat-1")

    def test_401_forces_one_refresh_and_retry(self) -> None:
        sent, tokens = self.run_flow([401, 401])
        self.assertEqual(sent, ["Bearer token-1", "Bearer token-2"])
        tokens.get.assert_called_with("wat-1", "token-1")
        self.assertEqual(tokens.get.call_count, 2)


class BuildMcpClientIdentityTests(unittest.TestCase):
    @patch("core.factory.load_credentials")
    @patch("core.factory.identity_gateway_tokens")
    @patch("core.factory.workload_access_token", return_value="wat-1")
    @patch("core.factory.identity_credentials", return_value=IDENTITY)
    def test_cloud_path_uses_identity_and_never_reads_the_file(
        self, _identity, _wat, tokens, load
    ) -> None:
        with patch("core.factory.MCPClient") as mcp_client:
            factory.build_mcp_client()
        kwargs = mcp_client.call_args.kwargs
        self.assertEqual(kwargs["url"], GATEWAY_URL)
        self.assertIsInstance(kwargs["auth_provider"], factory.IdentityGatewayAuth)
        tokens.assert_called_once_with(IDENTITY)
        load.assert_not_called()

    def test_missing_workload_token_fails(self) -> None:
        with (
            patch(
                "bedrock_agentcore.runtime.BedrockAgentCoreContext.get_workload_access_token",
                return_value=None,
            ),
            self.assertRaisesRegex(RuntimeError, "workload access token"),
        ):
            factory.workload_access_token()


if __name__ == "__main__":
    unittest.main()
