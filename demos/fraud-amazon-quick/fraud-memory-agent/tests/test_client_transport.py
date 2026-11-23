"""Offline checks for the deployed AgentCore client configuration."""

from __future__ import annotations

import json
import os
import subprocess
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


class SseParsingTests(unittest.TestCase):
    def test_app_error_event_is_reported(self) -> None:
        events = [
            b'data: {"type": "chunk", "data": "partial"}\n\n',
            b'data: {"error": "boom", "error_type": "RuntimeError",'
            b' "message": "An error occurred during streaming"}\n\n',
        ]
        content_parts, errors = transport._consume_sse(events, stream=False)
        self.assertEqual(content_parts, ["partial"])
        self.assertEqual(errors, ["RuntimeError: boom"])
        self.assertEqual(
            transport._result(content_parts, errors),
            {"status": "error", "errors": ["RuntimeError: boom"]},
        )


RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/fraud_memory_agent-AbC"


def status_output(resources: list[dict]) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout=json.dumps({"resources": resources}))


class AgentConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        env = patch.dict(
            os.environ, {k: v for k, v in os.environ.items() if k != "AGENT_ARN"}, clear=True
        )
        env.start()
        self.addCleanup(env.stop)

    @patch("client.transport.subprocess.run")
    def test_agent_arn_wins_without_calling_the_cli(self, run: Mock) -> None:
        os.environ["AGENT_ARN"] = RUNTIME_ARN
        self.assertEqual(transport.get_agent_config(), (RUNTIME_ARN, "us-west-2"))
        run.assert_not_called()

    @patch("client.transport.subprocess.run")
    def test_arn_comes_from_cli_status(self, run: Mock) -> None:
        run.return_value = status_output(
            [
                {"resourceType": "credential", "name": "fraud-gateway", "arn": "x"},
                {
                    "resourceType": "runtime",
                    "name": "fraud_memory_agent",
                    "deploymentState": "deployed",
                    "arn": RUNTIME_ARN,
                },
            ]
        )
        self.assertEqual(transport.get_agent_config(), (RUNTIME_ARN, "us-west-2"))
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["agentcore", "status", "--json", "--target", "default"])
        self.assertEqual(kwargs["cwd"], transport.AGENT_ROOT)

    @patch("client.transport.subprocess.run")
    def test_undeployed_runtime_exits_with_a_hint(self, run: Mock) -> None:
        run.return_value = status_output(
            [
                {
                    "resourceType": "runtime",
                    "name": "fraud_memory_agent",
                    "deploymentState": "local-only",
                }
            ]
        )
        with self.assertRaises(SystemExit) as caught:
            transport.get_agent_config()
        self.assertIn("./agent.sh deploy", str(caught.exception.code))

    @patch("client.transport.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_cli_exits_with_a_hint(self, _run: Mock) -> None:
        with self.assertRaises(SystemExit) as caught:
            transport.get_agent_config()
        self.assertIn("AGENT_ARN", str(caught.exception.code))

    def test_a_non_agentcore_arn_is_rejected(self) -> None:
        os.environ["AGENT_ARN"] = "arn:aws:lambda:us-west-2:123456789012:function:f"
        with self.assertRaises(ValueError):
            transport.get_agent_config()


if __name__ == "__main__":
    unittest.main()
