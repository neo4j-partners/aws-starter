"""Offline checks for the deployed AgentCore client configuration."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from client import transport


class DeployedTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        transport._deployed_client.cache_clear()

    def tearDown(self) -> None:
        transport._deployed_client.cache_clear()

    @patch("client.transport.get_agent_config", return_value=("runtime-arn", "us-east-1"))
    @patch("client.transport.boto3.client")
    def test_deployed_client_has_explicit_timeouts_and_no_implicit_retry(
        self, create_client: Mock, _: Mock
    ) -> None:
        fake_client = Mock()
        fake_client.invoke_agent_runtime.return_value = {"response": []}
        create_client.return_value = fake_client

        result = transport.invoke_deployed(
            {"prompt": "test"},
            stream=False,
            read_timeout=321,
            connect_timeout=12,
            max_attempts=1,
        )

        self.assertEqual(result, {"status": "success", "response": ""})
        _, kwargs = create_client.call_args
        config = kwargs["config"]
        self.assertEqual(kwargs["region_name"], "us-east-1")
        self.assertEqual(config.read_timeout, 321)
        self.assertEqual(config.connect_timeout, 12)
        self.assertEqual(config.retries, {"mode": "standard", "total_max_attempts": 1})
        self.assertTrue(config.tcp_keepalive)

    def test_invalid_attempt_count_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1"):
            transport._deployed_settings(max_attempts=0)

    def test_default_deployed_deadline_exceeds_botocore_default(self) -> None:
        read_timeout, connect_timeout, max_attempts, _ = transport._deployed_settings()

        self.assertEqual(read_timeout, 300)
        self.assertEqual(connect_timeout, 10)
        self.assertEqual(max_attempts, 1)


if __name__ == "__main__":
    unittest.main()
