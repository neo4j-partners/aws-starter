"""Offline checks for scripts/clean_destroy_leftovers.py with AWS mocked."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "Operation")


def agent_config(**memory: object) -> dict:
    return {
        "aws": {"account": ACCOUNT, "region": REGION},
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
        self.sts = Mock()
        self.sts.get_caller_identity.return_value = {"Account": ACCOUNT}
        self.regions: list[str] = []

    def __call__(self, service: str, *, region_name: str) -> Mock:
        self.regions.append(region_name)
        return getattr(self, service)


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
        return clean.clean_leftovers(agent, AGENT, self.cache_dir, self.clients)

    def test_all_three_leftovers_are_removed(self) -> None:
        self.make_agent_cache()

        report, failures = self.run_clean(agent_config())

        self.assertEqual(failures, [])
        self.assertEqual(
            report,
            [
                f"Removed: S3 bucket {BUCKET}",
                f"Removed: log group {LOG_GROUP}",
                f"Removed: local cache {self.cache_dir / AGENT}",
            ],
        )
        self.clients.s3.list_object_versions.assert_called_once_with(
            Bucket=BUCKET, MaxKeys=1, ExpectedBucketOwner=ACCOUNT
        )
        self.clients.s3.delete_bucket.assert_called_once_with(
            Bucket=BUCKET, ExpectedBucketOwner=ACCOUNT
        )
        self.clients.logs.delete_log_group.assert_called_once_with(logGroupName=LOG_GROUP)
        self.assertFalse(self.cache_dir.exists())
        self.assertEqual(set(self.clients.regions), {REGION})

    def test_missing_resources_are_reported_as_not_found(self) -> None:
        self.clients.s3.list_object_versions.side_effect = client_error("NoSuchBucket")
        self.clients.logs.delete_log_group.side_effect = client_error("ResourceNotFoundException")

        report, failures = self.run_clean(agent_config())

        self.assertEqual(failures, [])
        self.assertEqual(
            report,
            [
                f"Not found: S3 bucket {BUCKET}",
                f"Not found: log group {LOG_GROUP}",
                f"Not found: local cache {self.cache_dir / AGENT}",
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
        self.clients.logs.delete_log_group.assert_not_called()

    def test_an_agent_without_memory_has_no_log_group(self) -> None:
        for memory in ({"mode": "NO_MEMORY"}, {"memory_id": None}):
            with self.subTest(memory=memory):
                report, _ = self.run_clean(agent_config(**memory))

                self.assertEqual(report[1], "Skipped: memory log group; the agent had no memory")
        self.clients.logs.delete_log_group.assert_not_called()

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
            report[0], "Skipped: S3 bucket and memory log group; no Region in the config"
        )
        self.assertEqual(self.clients.regions, [])

    def test_other_aws_errors_are_failures_and_later_steps_still_run(self) -> None:
        self.clients.s3.list_object_versions.side_effect = client_error("AccessDenied")
        self.clients.logs.delete_log_group.side_effect = client_error("AccessDeniedException")
        self.make_agent_cache()

        report, failures = self.run_clean(agent_config())

        self.assertEqual(len(failures), 2)
        self.assertIn("S3 source bucket", failures[0])
        self.assertIn("AccessDenied", failures[0])
        self.assertIn("log group of memory mem-123 in us-east-1", failures[1])
        self.assertEqual(report, [f"Removed: local cache {self.cache_dir / AGENT}"])

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

        self.assertEqual(code, 0)
        self.assertIn("leftovers stay in place", stdout)
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
