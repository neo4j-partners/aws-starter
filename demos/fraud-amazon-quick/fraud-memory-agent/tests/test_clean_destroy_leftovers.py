"""Offline checks for scripts/clean_destroy_leftovers.py with AWS mocked."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import yaml
from botocore.exceptions import ClientError

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "clean_destroy_leftovers.py"
_SPEC = importlib.util.spec_from_file_location("clean_destroy_leftovers", _SCRIPT)
clean = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(clean)

AGENT = "fraud_memory_agent"
ACCOUNT = "111122223333"
REGION = "us-east-1"
BUCKET = f"bedrock-agentcore-codebuild-sources-{ACCOUNT}-{REGION}"
LOG_GROUP = "/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/mem-123"
RUNTIME_ID = "fraud_memory_agent-AbCdE12345"
RUNTIME_PREFIX = f"/aws/bedrock-agentcore/runtimes/{RUNTIME_ID}-"
RUNTIME_LOG_GROUP = f"{RUNTIME_PREFIX}DEFAULT"


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "Operation")


def agent_config(**memory: object) -> dict:
    return {
        "aws": {"account": ACCOUNT, "region": REGION},
        "bedrock_agentcore": {"agent_id": RUNTIME_ID},
        "memory": {
            "mode": "STM_ONLY",
            "memory_id": "mem-123",
            "was_created_by_toolkit": True,
            **memory,
        },
    }


class FakeClients:
    """Hands out one Mock per AWS service and records the Region asked for."""

    def __init__(self) -> None:
        self.s3 = Mock()
        self.s3.list_object_versions.return_value = {}
        self.logs = Mock()
        self.runtime_log_groups = [RUNTIME_LOG_GROUP]
        self.logs.get_paginator.return_value.paginate.side_effect = self.paginate
        self.sts = Mock()
        self.sts.get_caller_identity.return_value = {"Account": ACCOUNT}
        self.control = Mock()
        self.control.get_agent_runtime.side_effect = client_error("ResourceNotFoundException")
        self.regions: list[str] = []

    def paginate(self, logGroupNamePrefix: str) -> list[dict]:
        groups = [name for name in self.runtime_log_groups if name.startswith(logGroupNamePrefix)]
        return [{"logGroups": [{"logGroupName": name} for name in groups]}]

    def __call__(self, service: str, *, region_name: str) -> Mock:
        self.regions.append(region_name)
        return self.control if service == "bedrock-agentcore-control" else getattr(self, service)


class CleanLeftoversTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cache_dir = self.root / ".bedrock_agentcore"
        self.clients = FakeClients()

    def make_agent_cache(self) -> Path:
        agent_cache = self.cache_dir / AGENT
        agent_cache.mkdir(parents=True)
        (agent_cache / "dependencies.zip").write_bytes(b"zip")
        return agent_cache

    def run_clean(self, agent: dict) -> tuple[list[str], list[str]]:
        """Run the cleanup and keep what it prints in self.stdout."""
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = clean.clean_leftovers(agent, AGENT, self.cache_dir, self.clients)
        self.stdout = stdout.getvalue()
        return result

    def test_the_runtime_wait_is_announced_before_polling(self) -> None:
        def get_agent_runtime(agentRuntimeId: str) -> None:
            # The message must already be out when the first poll happens.
            self.assertIn(
                f"Waiting for Runtime {RUNTIME_ID} to be deleted (up to 10 minutes)...",
                printed.getvalue(),
            )
            raise client_error("ResourceNotFoundException")

        self.clients.control.get_agent_runtime.side_effect = get_agent_runtime
        printed = io.StringIO()

        with contextlib.redirect_stdout(printed):
            clean.clean_leftovers(agent_config(), AGENT, self.cache_dir, self.clients)

        self.clients.control.get_agent_runtime.assert_called_once_with(agentRuntimeId=RUNTIME_ID)

    def test_all_four_leftovers_are_removed(self) -> None:
        self.make_agent_cache()

        report, failures = self.run_clean(agent_config())

        self.assertEqual(failures, [])
        self.assertEqual(
            report,
            [
                f"Removed: S3 bucket {BUCKET}",
                f"Removed: log group {LOG_GROUP}",
                f"Removed: local cache {self.cache_dir / AGENT}",
                f"Removed: log group {RUNTIME_LOG_GROUP}",
            ],
        )
        self.clients.s3.list_object_versions.assert_called_once_with(
            Bucket=BUCKET, MaxKeys=1, ExpectedBucketOwner=ACCOUNT
        )
        self.clients.s3.delete_bucket.assert_called_once_with(
            Bucket=BUCKET, ExpectedBucketOwner=ACCOUNT
        )
        self.assertEqual(
            self.clients.logs.delete_log_group.call_args_list,
            [call(logGroupName=LOG_GROUP), call(logGroupName=RUNTIME_LOG_GROUP)],
        )
        self.clients.control.get_agent_runtime.assert_called_once_with(agentRuntimeId=RUNTIME_ID)
        self.assertFalse(self.cache_dir.exists())
        self.assertEqual(set(self.clients.regions), {REGION})

    def test_missing_resources_are_reported_as_not_found(self) -> None:
        self.clients.s3.list_object_versions.side_effect = client_error("NoSuchBucket")
        self.clients.logs.delete_log_group.side_effect = client_error("ResourceNotFoundException")
        self.clients.runtime_log_groups = []

        report, failures = self.run_clean(agent_config())

        self.assertEqual(failures, [])
        self.assertEqual(
            report,
            [
                f"Not found: S3 bucket {BUCKET}",
                f"Not found: log group {LOG_GROUP}",
                f"Not found: local cache {self.cache_dir / AGENT}",
                f"Not found: log groups under {RUNTIME_PREFIX} in {REGION}",
            ],
        )
        self.clients.s3.delete_bucket.assert_not_called()

    def test_a_bucket_with_objects_is_kept(self) -> None:
        self.clients.s3.list_object_versions.return_value = {"Versions": [{"Key": "a.zip"}]}

        report, _ = self.run_clean(agent_config())

        self.assertIn("Skipped: S3 bucket", report[0])
        self.assertIn("not empty", report[0])
        self.clients.s3.delete_bucket.assert_not_called()

    def test_a_bucket_with_only_delete_markers_is_kept(self) -> None:
        self.clients.s3.list_object_versions.return_value = {"DeleteMarkers": [{"Key": "a.zip"}]}

        report, _ = self.run_clean(agent_config())

        self.assertIn("not empty", report[0])
        self.clients.s3.delete_bucket.assert_not_called()

    def test_a_pre_existing_memory_keeps_its_log_group(self) -> None:
        report, _ = self.run_clean(agent_config(was_created_by_toolkit=False))

        self.assertEqual(report[1], "Skipped: memory log group; memory mem-123 was pre-existing")
        # Only the runtime's log group is deleted.
        self.clients.logs.delete_log_group.assert_called_once_with(logGroupName=RUNTIME_LOG_GROUP)

    def test_an_agent_without_memory_has_no_log_group(self) -> None:
        for memory in ({"mode": "NO_MEMORY"}, {"memory_id": None}):
            with self.subTest(memory=memory):
                report, _ = self.run_clean(agent_config(**memory))

                self.assertEqual(report[1], "Skipped: memory log group; the agent had no memory")
        # Only the runtime's log group is deleted, once per subtest.
        self.assertEqual(
            self.clients.logs.delete_log_group.call_args_list,
            [call(logGroupName=RUNTIME_LOG_GROUP)] * 2,
        )

    def test_the_account_comes_from_sts_when_the_config_has_none(self) -> None:
        agent = agent_config()
        agent["aws"]["account"] = None

        report, _ = self.run_clean(agent)

        self.assertEqual(report[0], f"Removed: S3 bucket {BUCKET}")
        self.clients.sts.get_caller_identity.assert_called_once_with()

    def test_no_region_skips_both_aws_steps(self) -> None:
        agent = agent_config()
        agent["aws"]["region"] = None

        report, failures = self.run_clean(agent)

        self.assertEqual(failures, [])
        self.assertEqual(
            report[0],
            "Skipped: S3 bucket, memory log group and runtime log groups; no Region in the config",
        )
        self.assertEqual(self.clients.regions, [])

    def test_other_aws_errors_are_failures_and_later_steps_still_run(self) -> None:
        self.clients.s3.list_object_versions.side_effect = client_error("AccessDenied")
        self.clients.logs.delete_log_group.side_effect = client_error("AccessDeniedException")
        self.make_agent_cache()

        report, failures = self.run_clean(agent_config())

        self.assertEqual(len(failures), 3)
        self.assertIn("S3 source bucket", failures[0])
        self.assertIn("AccessDenied", failures[0])
        self.assertIn("log group of memory mem-123 in us-east-1", failures[1])
        self.assertIn(f"Could not remove log group {RUNTIME_LOG_GROUP} in us-east-1", failures[2])
        self.assertEqual(report, [f"Removed: local cache {self.cache_dir / AGENT}"])

    def test_only_this_runtimes_log_groups_are_removed(self) -> None:
        other = "/aws/bedrock-agentcore/runtimes/fraud_memory_agent-AbCdE123456-DEFAULT"
        self.clients.runtime_log_groups = [RUNTIME_LOG_GROUP, other]

        report, failures = self.run_clean(agent_config())

        self.assertEqual(failures, [])
        self.assertEqual(report[3], f"Removed: log group {RUNTIME_LOG_GROUP}")
        self.clients.logs.get_paginator.return_value.paginate.assert_called_once_with(
            logGroupNamePrefix=RUNTIME_PREFIX
        )
        self.assertNotIn(
            call(logGroupName=other), self.clients.logs.delete_log_group.call_args_list
        )

    def test_a_failed_runtime_log_group_delete_names_the_group(self) -> None:
        second = f"{RUNTIME_PREFIX}other"
        self.clients.runtime_log_groups = [RUNTIME_LOG_GROUP, second]

        def delete(logGroupName: str) -> None:
            if logGroupName == RUNTIME_LOG_GROUP:
                raise client_error("AccessDeniedException")

        self.clients.logs.delete_log_group.side_effect = delete

        report, failures = self.run_clean(agent_config())

        self.assertEqual(len(failures), 1)
        self.assertIn(f"Could not remove log group {RUNTIME_LOG_GROUP} in {REGION}", failures[0])
        self.assertEqual(report[3:], [f"Removed: log group {second}"])

    def test_a_runtime_log_group_gone_before_its_delete_is_not_an_error(self) -> None:
        def delete(logGroupName: str) -> None:
            if logGroupName == RUNTIME_LOG_GROUP:
                raise client_error("ResourceNotFoundException")

        self.clients.logs.delete_log_group.side_effect = delete

        report, failures = self.run_clean(agent_config())

        self.assertEqual(failures, [])
        self.assertEqual(report[3], f"Not found: log group {RUNTIME_LOG_GROUP}")

    def test_no_valid_runtime_id_skips_the_runtime_log_groups(self) -> None:
        for runtime in (
            None,
            {},
            {"agent_id": None},
            {"agent_id": "fraud_memory_agent"},
            {"agent_id": f"{RUNTIME_ID}*"},
        ):
            with self.subTest(runtime=runtime):
                agent = agent_config()
                agent["bedrock_agentcore"] = runtime

                report, failures = self.run_clean(agent)

                self.assertEqual(failures, [])
                self.assertEqual(
                    report[3], "Skipped: runtime log groups; no valid runtime ID in the config"
                )
        self.clients.control.get_agent_runtime.assert_not_called()
        self.clients.logs.get_paginator.assert_not_called()

    def test_the_runtime_log_groups_wait_until_the_runtime_is_gone(self) -> None:
        self.clients.control.get_agent_runtime.side_effect = [
            {"status": "DELETING"},
            client_error("ResourceNotFoundException"),
        ]

        with patch.object(clean.time, "sleep") as sleep:
            report, failures = self.run_clean(agent_config())

        self.assertEqual(failures, [])
        self.assertEqual(report[3], f"Removed: log group {RUNTIME_LOG_GROUP}")
        sleep.assert_called_once_with(clean.RUNTIME_DELETE_POLL)

    def test_a_runtime_that_outlasts_the_wait_keeps_its_log_groups(self) -> None:
        self.clients.control.get_agent_runtime.side_effect = None
        self.clients.control.get_agent_runtime.return_value = {"status": "DELETING"}

        with (
            patch.object(clean, "RUNTIME_DELETE_TIMEOUT", 0),
            patch.object(clean.time, "sleep") as sleep,
        ):
            report, failures = self.run_clean(agent_config())

        self.assertEqual(len(report), 3)
        self.assertEqual(len(failures), 1)
        self.assertIn(f"Runtime {RUNTIME_ID} is still present after 0s", failures[0])
        self.assertIn(RUNTIME_PREFIX, failures[0])
        sleep.assert_not_called()
        self.clients.logs.get_paginator.assert_not_called()

    def test_a_delete_failed_runtime_stops_the_wait_and_keeps_its_log_groups(self) -> None:
        cases = [
            ({"status": "DELETE_FAILED", "failureReason": "Role is missing"}, "Role is missing"),
            ({"status": "DELETE_FAILED"}, "no failure reason supplied"),
            ({"status": "DELETE_FAILED", "failureReason": ""}, "no failure reason supplied"),
        ]
        for response, reason in cases:
            with self.subTest(response=response):
                self.clients = FakeClients()
                self.clients.control.get_agent_runtime.side_effect = [
                    {"status": "DELETING"},
                    response,
                ]

                with patch.object(clean.time, "sleep") as sleep:
                    report, failures = self.run_clean(agent_config())

                self.assertEqual(len(report), 3)
                self.assertEqual(
                    failures,
                    [
                        f"Runtime {RUNTIME_ID} is DELETE_FAILED ({reason}), so its log groups "
                        f"under {RUNTIME_PREFIX} in {REGION} stay in place"
                    ],
                )
                # One sleep after DELETING, then the DELETE_FAILED poll ends the wait.
                sleep.assert_called_once_with(clean.RUNTIME_DELETE_POLL)
                self.assertEqual(self.clients.control.get_agent_runtime.call_count, 2)
                self.clients.logs.get_paginator.assert_not_called()

    def test_a_delete_failed_runtime_makes_main_exit_1(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        snapshot = Path(temp.name) / "snapshot.yaml"
        snapshot.write_text(yaml.safe_dump({"agents": {AGENT: agent_config()}}))
        self.clients.control.get_agent_runtime.side_effect = None
        self.clients.control.get_agent_runtime.return_value = {"status": "DELETE_FAILED"}
        argv = [
            "clean",
            *("--snapshot", str(snapshot)),
            *("--config", str(Path(temp.name) / ".bedrock_agentcore.yaml")),
            *("--agent", AGENT),
            *("--cache-dir", str(self.cache_dir)),
        ]
        stderr = io.StringIO()
        real_clean = clean.clean_leftovers

        def clean_with_fakes(agent: dict, agent_name: str, cache_dir: Path) -> tuple:
            return real_clean(agent, agent_name, cache_dir, self.clients)

        with (
            patch.object(sys, "argv", argv),
            patch.object(clean, "clean_leftovers", clean_with_fakes),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(stderr),
        ):
            code = clean.main()

        self.assertEqual(code, 1)
        self.assertIn("DELETE_FAILED (no failure reason supplied)", stderr.getvalue())

    def test_a_failed_runtime_check_or_listing_is_a_failure(self) -> None:
        for target in ("get_agent_runtime", "paginate"):
            with self.subTest(target=target):
                clients = FakeClients()
                error = client_error("ExpiredTokenException")
                if target == "get_agent_runtime":
                    clients.control.get_agent_runtime.side_effect = error
                else:
                    clients.logs.get_paginator.return_value.paginate.side_effect = error

                report, failures = clean.clean_leftovers(
                    agent_config(), AGENT, self.cache_dir, clients
                )

                self.assertEqual(len(report), 3)
                self.assertEqual(len(failures), 1)
                self.assertIn(
                    f"Could not remove the log groups under {RUNTIME_PREFIX}", failures[0]
                )

    def test_another_agents_cache_is_kept(self) -> None:
        self.make_agent_cache()
        other = self.cache_dir / "other_agent"
        other.mkdir()

        report, _ = self.run_clean(agent_config())

        self.assertEqual(report[2], f"Removed: local cache {self.cache_dir / AGENT}")
        self.assertFalse((self.cache_dir / AGENT).exists())
        self.assertTrue(other.is_dir())

    def test_a_symlinked_cache_is_not_followed(self) -> None:
        target = self.root / "elsewhere"
        target.mkdir()
        (target / "keep.txt").write_text("keep")
        self.cache_dir.mkdir()
        (self.cache_dir / AGENT).symlink_to(target)

        report, _ = self.run_clean(agent_config())

        self.assertEqual(report[2], f"Skipped: {self.cache_dir / AGENT} is not a plain folder")
        self.assertTrue((target / "keep.txt").exists())

    def test_a_cache_dir_with_another_name_is_not_touched(self) -> None:
        other = self.root / "build"
        (other / AGENT).mkdir(parents=True)

        report = clean.remove_cache_dir(other, AGENT)

        self.assertEqual(report, f"Skipped: {other} is not a .bedrock_agentcore folder")
        self.assertTrue((other / AGENT).is_dir())


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.snapshot = self.root / "snapshot.yaml"
        self.config = self.root / ".bedrock_agentcore.yaml"
        self.write(self.snapshot, {"agents": {AGENT: agent_config()}})

    @staticmethod
    def write(path: Path, config: dict) -> None:
        path.write_text(yaml.safe_dump(config))

    def run_main(self, clean_result: tuple[list[str], list[str]] | None = None) -> tuple:
        argv = [
            "clean",
            *("--snapshot", str(self.snapshot)),
            *("--config", str(self.config)),
            *("--agent", AGENT),
            *("--cache-dir", str(self.root / ".bedrock_agentcore")),
        ]
        stdout, stderr = io.StringIO(), io.StringIO()
        cleaner = Mock(return_value=clean_result or ([], []))
        with (
            patch.object(sys, "argv", argv),
            patch.object(clean, "clean_leftovers", cleaner),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = clean.main()
        return code, stdout.getvalue(), stderr.getvalue(), cleaner

    def test_a_completed_destroy_runs_the_cleanup(self) -> None:
        code, stdout, _, cleaner = self.run_main(([f"Removed: S3 bucket {BUCKET}"], []))

        self.assertEqual(code, 0)
        self.assertIn("Removed: S3 bucket", stdout)
        cleaner.assert_called_once_with(agent_config(), AGENT, self.root / ".bedrock_agentcore")

    def test_a_config_left_with_other_agents_still_counts_as_completed(self) -> None:
        self.write(self.config, {"agents": {"other_agent": agent_config()}})

        code, _, _, cleaner = self.run_main()

        self.assertEqual(code, 0)
        cleaner.assert_called_once()

    def test_a_cancelled_or_failed_destroy_skips_the_cleanup(self) -> None:
        self.write(self.config, {"agents": {AGENT: agent_config()}})

        code, stdout, _, cleaner = self.run_main()

        # agent.sh reads exit 3 as "destroy did not finish".
        self.assertEqual(code, 3)
        self.assertIn("leftovers stay in place", stdout)
        cleaner.assert_not_called()

    def test_an_unreadable_config_after_destroy_exits_1_without_a_traceback(self) -> None:
        self.config.write_text("agents: [unclosed\n")

        code, _, stderr, cleaner = self.run_main()

        self.assertEqual(code, 1)
        self.assertIn("Could not read .bedrock_agentcore.yaml after destroy", stderr)
        self.assertNotIn("Traceback", stderr)
        cleaner.assert_not_called()

    def test_failures_exit_1(self) -> None:
        code, _, stderr, _ = self.run_main(([], ["Could not remove the S3 source bucket: x"]))

        self.assertEqual(code, 1)
        self.assertIn("Could not remove the S3 source bucket", stderr)

    def test_a_snapshot_without_the_agent_exits_2(self) -> None:
        self.write(self.snapshot, {"agents": {"other_agent": agent_config()}})

        code, _, stderr, cleaner = self.run_main()

        self.assertEqual(code, 2)
        self.assertIn("is not in the config snapshot", stderr)
        cleaner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
