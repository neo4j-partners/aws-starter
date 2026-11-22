"""Offline checks for the READY polling in scripts/verify_agentcore_runtime.py."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import Mock

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_agentcore_runtime.py"
_SPEC = importlib.util.spec_from_file_location("verify_agentcore_runtime", _SCRIPT)
verify = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verify)


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


if __name__ == "__main__":
    unittest.main()
