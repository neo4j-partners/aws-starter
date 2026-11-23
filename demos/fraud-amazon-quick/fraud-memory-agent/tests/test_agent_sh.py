"""Offline checks for agent.sh with `uv` stubbed on PATH."""

from __future__ import annotations

import os
import shutil
import signal
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

AGENT_SH = Path(__file__).resolve().parents[1] / "agent.sh"

# Records its arguments, prints STUB_UV_OUTPUT, deletes STUB_UV_REMOVE when set
# (as `agentcore destroy` deletes the config) and exits with STUB_UV_STATUS.
UV_STUB = """#!/bin/bash
printf '%s\\n' "$*" >> "$STUB_LOG"
[ -z "${STUB_UV_OUTPUT:-}" ] || printf '%s\\n' "$STUB_UV_OUTPUT"
[ -z "${STUB_UV_REMOVE:-}" ] || rm -f "$STUB_UV_REMOVE"
# Ctrl+C: interrupt agent.sh, which is the parent of this stub.
[ -z "${STUB_UV_SIGINT:-}" ] || kill -INT "$PPID"
exit "${STUB_UV_STATUS:-0}"
"""

# Stands in for .venv/bin/python. Records its arguments, copies the file after
# --snapshot to STUB_SNAPSHOT_COPY and exits with STUB_PY_STATUS.
PYTHON_STUB = """#!/bin/bash
printf 'python %s\\n' "$*" >> "$STUB_LOG"
while [ $# -gt 0 ]; do
    if [ "$1" = "--snapshot" ]; then cp "$2" "$STUB_SNAPSHOT_COPY"; fi
    shift
done
exit "${STUB_PY_STATUS:-0}"
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
        # agent.sh's mktemp files land here, so tests can check they are gone.
        self.tmp = Path(temp.name) / "tmp"
        self.tmp.mkdir()

    def run_agent(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        run_env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(self.log),
            "TMPDIR": str(self.tmp),
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

    def test_the_response_file_is_removed_on_every_exit(self) -> None:
        for env in ({}, {"STUB_UV_STATUS": "3"}, {"STUB_UV_OUTPUT": '{"type": "error"}'}):
            with self.subTest(env=env):
                self.run_agent("invoke-cloud", "Find chains", **env)

                self.assertEqual(list(self.tmp.iterdir()), [])

    def test_ctrl_c_removes_the_response_file(self) -> None:
        result = self.run_agent("invoke-cloud", "Find chains", STUB_UV_SIGINT="1")

        self.assertEqual(result.returncode, -signal.SIGINT)
        self.assertEqual(list(self.tmp.iterdir()), [])


class DestroyTests(AgentShTestCase):
    CONFIG = "agents:\n  fraud_memory_agent:\n    name: fraud_memory_agent\n"

    def setUp(self) -> None:
        super().setUp()
        write_executable(self.root / ".venv" / "bin" / "python", PYTHON_STUB)
        self.config = self.root / ".bedrock_agentcore.yaml"
        self.snapshot_copy = self.log.parent / "snapshot-copy.yaml"

    def destroy(self, **env: str) -> subprocess.CompletedProcess[str]:
        # env can override STUB_UV_REMOVE, for a destroy that keeps the config.
        defaults = {
            "STUB_UV_REMOVE": str(self.config),
            "STUB_SNAPSHOT_COPY": str(self.snapshot_copy),
        }
        return self.run_agent("destroy", **{**defaults, **env})

    def test_destroy_cleans_up_from_a_copy_of_the_config(self) -> None:
        self.config.write_text(self.CONFIG)

        result = self.destroy()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        uv_call, python_call = self.calls()
        self.assertEqual(uv_call, "run agentcore destroy")
        self.assertIn("python scripts/clean_destroy_leftovers.py --snapshot ", python_call)
        self.assertIn(f"--config {self.config}", python_call)
        self.assertIn("--agent fraud_memory_agent", python_call)
        self.assertIn(f"--cache-dir {self.root / '.bedrock_agentcore'}", python_call)
        self.assertEqual(self.snapshot_copy.read_text(), self.CONFIG)
        self.assertIn("Cleanup complete!", result.stdout)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_a_destroy_that_did_not_finish_does_not_claim_cleanup_complete(self) -> None:
        self.config.write_text(self.CONFIG)

        # The helper exits 3 when destroy left the agent in the config.
        result = self.destroy(STUB_UV_REMOVE="", STUB_PY_STATUS="3")

        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertNotIn("Cleanup complete!", result.stdout)
        self.assertNotIn("Some leftovers were not removed", result.stdout)
        self.assertIn(
            "Destroy did not finish, so fraud_memory_agent is still deployed", result.stdout
        )
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_ctrl_c_during_destroy_removes_the_config_copy(self) -> None:
        self.config.write_text(self.CONFIG)

        result = self.destroy(STUB_UV_REMOVE="", STUB_UV_SIGINT="1")

        self.assertEqual(result.returncode, -signal.SIGINT)
        self.assertEqual(self.calls(), ["run agentcore destroy"])
        self.assertNotIn("Cleanup complete!", result.stdout)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_a_failed_config_copy_removes_the_empty_temp_file(self) -> None:
        self.config.write_text(self.CONFIG)
        self.config.chmod(0)
        self.addCleanup(self.config.chmod, 0o644)

        result = self.destroy()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_a_failed_destroy_skips_the_cleanup(self) -> None:
        self.config.write_text(self.CONFIG)

        result = self.destroy(STUB_UV_STATUS="4")

        self.assertEqual(result.returncode, 4)
        self.assertEqual(self.calls(), ["run agentcore destroy"])
        self.assertNotIn("Cleanup complete!", result.stdout)

    def test_a_cleanup_failure_exits_1(self) -> None:
        self.config.write_text(self.CONFIG)

        result = self.destroy(STUB_PY_STATUS="1")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Some leftovers were not removed", result.stdout)
        self.assertNotIn("Cleanup complete!", result.stdout)

    def test_no_config_runs_destroy_without_the_cleanup(self) -> None:
        result = self.destroy()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls(), ["run agentcore destroy"])
        self.assertIn("leftover cleanup was skipped", result.stdout)


if __name__ == "__main__":
    unittest.main()
