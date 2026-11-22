"""Offline checks for agent.sh with `uv` stubbed on PATH."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

AGENT_SH = Path(__file__).resolve().parents[1] / "agent.sh"

# Records its arguments, prints STUB_UV_OUTPUT and exits with STUB_UV_STATUS.
UV_STUB = """#!/bin/bash
printf '%s\\n' "$*" >> "$STUB_LOG"
[ -z "${STUB_UV_OUTPUT:-}" ] || printf '%s\\n' "$STUB_UV_OUTPUT"
exit "${STUB_UV_STATUS:-0}"
"""


def write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class AgentShTestCase(unittest.TestCase):
    """Runs a copy of agent.sh in a temporary agent folder."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "agent"
        self.bin = Path(temp.name) / "bin"
        self.root.mkdir()
        self.bin.mkdir()
        shutil.copy2(AGENT_SH, self.root / "agent.sh")
        # ensure_deps skips `uv sync` when .venv exists.
        (self.root / ".venv" / "bin").mkdir(parents=True)
        write_executable(self.bin / "uv", UV_STUB)
        self.log = Path(temp.name) / "calls.log"
        self.log.touch()

    def run_agent(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        run_env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(self.log),
            **env,
        }
        return subprocess.run(
            ["bash", str(self.root / "agent.sh"), *args],
            capture_output=True,
            text=True,
            env=run_env,
            check=False,
            timeout=60,
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()


class InvokeCloudTests(AgentShTestCase):
    def test_a_successful_response_is_printed_and_exits_0(self) -> None:
        output = '{"type": "chunk", "data": "Two chains found."}\n{"type": "complete"}'

        result = self.run_agent("invoke-cloud", "Find chains", STUB_UV_OUTPUT=output)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('{"type": "chunk", "data": "Two chains found."}', result.stdout)
        self.assertEqual(self.calls(), ['run agentcore invoke {"prompt": "Find chains"}'])

    def test_an_error_event_is_printed_and_exits_1(self) -> None:
        output = '{"type": "error", "error": "NAMS GET → 424: external_database_error"}'

        result = self.run_agent("invoke-cloud", "Find chains", STUB_UV_OUTPUT=output)

        self.assertEqual(result.returncode, 1)
        self.assertIn("external_database_error", result.stdout)
        self.assertIn("The agent returned an error event", result.stdout)

    def test_a_colored_error_event_is_still_detected(self) -> None:
        output = '\x1b[1m{\x1b[0m\x1b[32m"type"\x1b[0m: \x1b[32m"error"\x1b[0m, "error": "x"}'

        result = self.run_agent("invoke-cloud", "Find chains", STUB_UV_OUTPUT=output)

        self.assertEqual(result.returncode, 1)

    def test_the_word_error_inside_an_answer_is_not_an_error_event(self) -> None:
        output = '{"type": "chunk", "data": "{\\"type\\": \\"error\\"} is a JSON example."}'

        result = self.run_agent("invoke-cloud", "Find chains", STUB_UV_OUTPUT=output)

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_failed_cli_call_keeps_its_exit_code(self) -> None:
        result = self.run_agent(
            "invoke-cloud", "Find chains", STUB_UV_OUTPUT="Invocation failed", STUB_UV_STATUS="3"
        )

        self.assertEqual(result.returncode, 3)
        self.assertIn("Invocation failed", result.stdout)
        self.assertNotIn("The agent returned an error event", result.stdout)

    def test_no_prompt_sends_the_default_question(self) -> None:
        result = self.run_agent("invoke-cloud")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("highest risk scores", self.calls()[0])


if __name__ == "__main__":
    unittest.main()
