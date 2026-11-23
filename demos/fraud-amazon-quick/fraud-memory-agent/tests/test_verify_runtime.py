"""Offline checks for the READY polling in scripts/verify_agentcore_runtime.py."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_agentcore_runtime.py"
_SPEC = importlib.util.spec_from_file_location("verify_agentcore_runtime", _SCRIPT)
verify = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verify)

RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/fraud_memory_agent-AbC123"


class FakeClock:
    """A clock that only advances when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def control_returning(*statuses: dict[str, str]) -> Mock:
    control = Mock()
    control.get_agent_runtime.side_effect = list(statuses)
    return control


class WaitForReadyTests(unittest.TestCase):
    def wait(self, control: Mock, clock: FakeClock, timeout: int = 600) -> str | None:
        with contextlib.redirect_stdout(io.StringIO()):
            return verify.wait_for_ready(
                control,
                "runtime-id",
                timeout_seconds=timeout,
                interval_seconds=15,
                sleep=clock.sleep,
                clock=clock.time,
            )

    def test_a_creating_runtime_is_polled_until_ready(self) -> None:
        clock = FakeClock()
        control = control_returning(
            {"status": "CREATING"}, {"status": "CREATING"}, {"status": "READY"}
        )

        self.assertIsNone(self.wait(control, clock))
        self.assertEqual(control.get_agent_runtime.call_count, 3)
        control.get_agent_runtime.assert_called_with(agentRuntimeId="runtime-id")
        self.assertEqual(clock.sleeps, [15, 15])

    def test_a_ready_runtime_needs_no_wait(self) -> None:
        clock = FakeClock()

        self.assertIsNone(self.wait(control_returning({"status": "READY"}), clock))
        self.assertEqual(clock.sleeps, [])

    def test_a_failed_runtime_fails_at_once_with_its_reason(self) -> None:
        clock = FakeClock()
        control = control_returning(
            {"status": "CREATING"},
            {"status": "CREATE_FAILED", "failureReason": "image pull failed"},
        )

        error = self.wait(control, clock)

        self.assertEqual(
            error, "Runtime is not ready: status='CREATE_FAILED'; reason=image pull failed"
        )
        self.assertEqual(clock.sleeps, [15])

    def test_an_update_failure_fails_without_waiting(self) -> None:
        clock = FakeClock()

        error = self.wait(control_returning({"status": "UPDATE_FAILED"}), clock)

        self.assertIn("status='UPDATE_FAILED'", error)
        self.assertIn("no failure reason supplied", error)
        self.assertEqual(clock.sleeps, [])

    def test_a_delete_failure_fails_without_waiting(self) -> None:
        clock = FakeClock()

        error = self.wait(control_returning({"status": "DELETE_FAILED"}), clock)

        self.assertIn("status='DELETE_FAILED'", error)
        self.assertEqual(clock.sleeps, [])

    def test_a_deleting_runtime_fails_without_waiting(self) -> None:
        clock = FakeClock()

        error = self.wait(control_returning({"status": "DELETING"}), clock)

        self.assertIn("status='DELETING'", error)
        self.assertEqual(clock.sleeps, [])

    def test_an_updating_runtime_is_polled_until_ready(self) -> None:
        clock = FakeClock()
        control = control_returning({"status": "UPDATING"}, {"status": "READY"})

        self.assertIsNone(self.wait(control, clock))
        self.assertEqual(clock.sleeps, [15])

    def test_a_runtime_that_never_becomes_ready_times_out(self) -> None:
        clock = FakeClock()
        control = Mock()
        control.get_agent_runtime.return_value = {"status": "CREATING"}

        error = self.wait(control, clock, timeout=40)

        self.assertEqual(
            error, "Runtime did not reach READY within 40 seconds: last status='CREATING'"
        )
        self.assertEqual(clock.sleeps, [15, 15, 10])
        self.assertEqual(control.get_agent_runtime.call_count, 4)


class ArgumentTests(unittest.TestCase):
    def run_main(self, *flags: str) -> tuple[int, str]:
        argv = ["verify", "--runtime-arn", RUNTIME_ARN, *flags]
        stderr = io.StringIO()
        with patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
            code = verify.main()
        return code, stderr.getvalue()

    def test_a_negative_ready_timeout_is_rejected(self) -> None:
        code, stderr = self.run_main("--ready-timeout-seconds", "-1")

        self.assertEqual(code, 2)
        self.assertIn("--ready-timeout-seconds must not be negative", stderr)

    def test_a_poll_interval_below_1_is_rejected(self) -> None:
        code, stderr = self.run_main("--poll-interval-seconds", "0")

        self.assertEqual(code, 2)
        self.assertIn("--poll-interval-seconds must be positive", stderr)

    def test_a_malformed_arn_is_rejected(self) -> None:
        with patch.object(sys, "argv", ["verify", "--runtime-arn", "not-an-arn"]):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = verify.main()

        self.assertEqual(code, 2)
        self.assertIn("Not an AgentCore Runtime ARN", stderr.getvalue())


class ParseRuntimeArnTests(unittest.TestCase):
    def test_id_and_region_come_from_the_arn(self) -> None:
        self.assertEqual(
            verify.parse_runtime_arn(RUNTIME_ARN), ("fraud_memory_agent-AbC123", "us-west-2")
        )

    def test_other_resource_types_are_rejected(self) -> None:
        for arn in (
            "arn:aws:bedrock-agentcore:us-west-2:123456789012:gateway/g-1",
            "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/",
            "arn:aws:lambda:us-west-2:123456789012:runtime/r-1",
            "arn:aws:bedrock-agentcore::123456789012:runtime/r-1",
        ):
            with self.subTest(arn=arn), self.assertRaises(ValueError):
                verify.parse_runtime_arn(arn)


class ConsumeSseTests(unittest.TestCase):
    def test_app_error_event_is_an_error(self) -> None:
        chunks = [
            b'data: {"type": "chunk", "data": "partial"}\n\n',
            b'data: {"error": "boom", "error_type": "RuntimeError",'
            b' "message": "An error occurred during streaming"}\n\n',
        ]
        answer, errors, completed = verify.consume_sse(chunks)
        self.assertEqual(answer, "partial")
        self.assertEqual(errors, ["RuntimeError: boom"])
        self.assertFalse(completed)


if __name__ == "__main__":
    unittest.main()
