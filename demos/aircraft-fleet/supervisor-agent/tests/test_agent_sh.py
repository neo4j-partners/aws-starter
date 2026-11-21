"""Tests for ``agent.sh destroy`` with stub ``agentcore`` and ``aws`` commands.

Each test copies agent.sh and the tracked agentcore.json into a temporary
folder and puts stub scripts first on PATH, so nothing reaches AWS. The stubs
log every call to calls.log and act on STUB_* environment variables.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "111122223333"

STUB_AGENTCORE = r"""#!/bin/bash
echo "agentcore $*" >> "$STUB_LOG"
case "$1" in
    status) printf '%s\n' "$STUB_STATUS_JSON" ;;
    remove)
        jq --arg n "$4" 'del(.runtimes[] | select(.name == $n))' \
            agentcore/agentcore.json > agentcore/agentcore.json.stub
        mv agentcore/agentcore.json.stub agentcore/agentcore.json
        ;;
    deploy)
        if [ -n "$STUB_DEPLOY_TARGETS" ]; then
            printf '%s\n' "$STUB_DEPLOY_TARGETS" > agentcore/aws-targets.json
        fi
        if [ -n "$STUB_DEPLOY_LOCK_SPEC" ]; then chmod 0444 agentcore/agentcore.json; fi
        if [ -n "$STUB_DEPLOY_SIGNAL" ]; then kill -s "$STUB_DEPLOY_SIGNAL" "$PPID"; fi
        exit "${STUB_DEPLOY_EXIT:-0}"
        ;;
    *) exit 99 ;;
esac
"""

STUB_AWS = r"""#!/bin/bash
echo "aws $*" >> "$STUB_LOG"
case "$1 $2" in
    "sts get-caller-identity")
        if [ -n "$STUB_STS_ERROR" ]; then echo "$STUB_STS_ERROR" >&2; exit 254; fi
        echo "${STUB_CALLER_ACCOUNT:-111122223333}"
        ;;
    "cloudformation describe-stacks")
        # Ctrl+C reaches the whole foreground group, so the stub dies too.
        # bash ignores a SIGINT when its child exits normally.
        if [ -n "$STUB_LOOKUP_SIGNAL" ]; then kill -s "$STUB_LOOKUP_SIGNAL" "$PPID" "$$"; fi
        if [ -n "$STUB_AWS_ERROR" ]; then echo "$STUB_AWS_ERROR" >&2; exit 254; fi
        if [ -n "$STUB_STACK_STATUS" ]; then echo "$STUB_STACK_STATUS"; exit 0; fi
        echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id x does not exist" >&2
        exit 254
        ;;
    "bedrock-agentcore-control get-oauth2-credential-provider")
        if [ -n "$STUB_PROVIDER_EXISTS" ]; then echo '{}'; exit 0; fi
        echo "An error occurred (ResourceNotFoundException) when calling the GetOauth2CredentialProvider operation: CredentialProvider not found" >&2
        exit 254
        ;;
    *) exit 99 ;;
esac
"""

# rm, cp, and mv pass through to /bin. STUB_INTERRUPT_AFTER=cmd:N sends
# SIGINT to agent.sh right after the Nth call of cmd, the same as a Ctrl+C.
STUB_PASSTHROUGH = r"""#!/bin/bash
name="${0##*/}"
/bin/"$name" "$@"
status=$?
counter="${STUB_LOG%/*}/$name-calls"
count=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
echo "$count" > "$counter"
if [ "${STUB_INTERRUPT_AFTER:-}" = "$name:$count" ]; then
    kill -s INT "$PPID"
fi
exit "$status"
"""

# This macOS mktemp ignores TMPDIR, so a call without a template gets one
# in the test's own folder. That lets a test check that nothing was left
# behind. A call with a template keeps it. STUB_MKTEMP_LOSE=N makes the Nth
# call create its file and then fail without printing the name, the same as
# a Ctrl+C inside $(mktemp) before the caller stores the name.
STUB_MKTEMP = r"""#!/bin/bash
counter="${STUB_LOG%/*}/mktemp-calls"
count=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
echo "$count" > "$counter"
if [ "$#" -gt 0 ]; then
    made=$(/usr/bin/mktemp "$@") || exit
else
    made=$(/usr/bin/mktemp "$STUB_TMP/tmp.XXXXXX") || exit
fi
if [ "${STUB_MKTEMP_LOSE:-}" = "$count" ]; then exit 1; fi
echo "$made"
"""

CLEAN_STATUS = json.dumps(
    {
        "resources": [
            {"resourceType": "runtime", "name": "supervisor", "deploymentState": "local-only"}
        ]
    }
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "supervisor-agent"
    (root / "agentcore").mkdir(parents=True)
    shutil.copy2(AGENT_ROOT / "agent.sh", root / "agent.sh")
    shutil.copy2(AGENT_ROOT / "agentcore" / "agentcore.json", root / "agentcore" / "agentcore.json")
    # The first deploy writes this file. Git ignores it, so the test writes its own.
    (root / "agentcore" / "aws-targets.json").write_text(
        json.dumps([{"name": "default", "account": ACCOUNT, "region": "us-west-2"}])
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        ("agentcore", STUB_AGENTCORE),
        ("aws", STUB_AWS),
        ("mktemp", STUB_MKTEMP),
        ("rm", STUB_PASSTHROUGH),
        ("cp", STUB_PASSTHROUGH),
        ("mv", STUB_PASSTHROUGH),
    ):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return root


def run_destroy(project: Path, **stub_env: str) -> subprocess.CompletedProcess[str]:
    return run_agent(project, "destroy", "--yes", **stub_env)


def run_agent(
    project: Path, *args: str, stdin: str = "", **stub_env: str
) -> subprocess.CompletedProcess[str]:
    temp_dir = project.parent / "tmp"
    temp_dir.mkdir(exist_ok=True)
    env = {
        "STUB_TMP": str(temp_dir),
        "TMPDIR": str(temp_dir),
        "PATH": f"{project.parent / 'bin'}:{os.environ['PATH']}",
        "HOME": os.environ["HOME"],
        "STUB_LOG": str(project.parent / "calls.log"),
        "STUB_STATUS_JSON": CLEAN_STATUS,
        **stub_env,
    }
    return subprocess.run(
        ["bash", str(project / "agent.sh"), *args],
        capture_output=True,
        text=True,
        env=env,
        input=stdin,
        timeout=60,
        check=False,
    )


def calls(project: Path) -> list[str]:
    log = project.parent / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def test_clean_destroy_checks_aws_by_name_and_succeeds(project: Path) -> None:
    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Cleanup complete" in result.stdout
    assert not list((project.parent / "tmp").iterdir())
    logged = calls(project)
    assert any(
        "describe-stacks --region us-west-2 --stack-name AgentCore-fleetsupervisor-default" in c
        for c in logged
    )
    assert any(
        "get-oauth2-credential-provider --region us-west-2 "
        "--name fleetsupervisor_default_fleet-gateway" in c
        for c in logged
    )
    # The account is checked before the first agentcore call and again
    # after the deploy, before the lookups.
    sts = "aws sts get-caller-identity --query Account --output text --region us-west-2"
    assert logged[0] == sts
    deploy = logged.index("agentcore deploy --target default --yes")
    assert sts in logged[deploy:]


def test_credentials_for_another_account_fail_before_the_confirmation(project: Path) -> None:
    spec = (project / "agentcore" / "agentcore.json").read_text()

    result = run_agent(project, "destroy", stdin="y\n", STUB_CALLER_ACCOUNT="999988887777")

    assert result.returncode == 1
    assert f"account 999988887777, but target 'default' is in account {ACCOUNT}" in result.stdout
    assert "Continue?" not in result.stdout
    assert not any(c.startswith("agentcore") for c in calls(project))
    assert (project / "agentcore" / "agentcore.json").read_text() == spec


def test_an_account_change_during_the_deploy_fails_before_the_aws_lookups(project: Path) -> None:
    targets = [{"name": "default", "account": "999988887777", "region": "us-west-2"}]

    result = run_destroy(project, STUB_DEPLOY_TARGETS=json.dumps(targets))

    assert result.returncode == 1
    assert f"account {ACCOUNT}, but target 'default' is in account 999988887777" in result.stdout
    assert "Cleanup complete" not in result.stdout
    logged = calls(project)
    assert "agentcore deploy --target default --yes" in logged
    assert not any(c.startswith(("aws cloudformation", "aws bedrock")) for c in logged)


def test_a_failed_identity_check_fails(project: Path) -> None:
    result = run_destroy(project, STUB_STS_ERROR="An error occurred (ExpiredToken)")

    assert result.returncode == 1
    assert "Could not check the active AWS account with STS." in result.stdout
    assert "ExpiredToken" in result.stderr
    assert "Cleanup complete" not in result.stdout


@pytest.mark.parametrize("targets", ["[]", "not json", '[{"name": "default"}]'])
def test_an_unknown_target_account_fails(project: Path, targets: str) -> None:
    (project / "agentcore" / "aws-targets.json").write_text(targets)

    result = run_agent(project, "destroy", stdin="y\n")

    assert result.returncode == 1
    assert "Could not read the account for target 'default'" in result.stdout
    # Nothing ran: no confirmation, no STS call, and no agentcore call.
    assert "Continue?" not in result.stdout
    assert calls(project) == []


def test_a_directory_at_the_targets_path_fails_as_unreadable(project: Path) -> None:
    path = project / "agentcore" / "aws-targets.json"
    path.unlink()
    path.mkdir()

    result = run_destroy(project)

    assert result.returncode == 1
    assert "Could not read the account for target 'default'" in result.stdout
    assert "No deployment is recorded" not in result.stdout
    assert calls(project) == []


@pytest.mark.parametrize("args", [("--yes",), ("",)])
def test_a_missing_targets_file_fails_before_any_call(project: Path, args: tuple[str, ...]) -> None:
    (project / "agentcore" / "aws-targets.json").unlink()

    result = run_agent(project, "destroy", *args, stdin="y\n")

    assert result.returncode == 1
    assert (
        "No deployment is recorded in this checkout: agentcore/aws-targets.json is missing. "
        "Run destroy from the checkout that deployed."
    ) in result.stdout
    assert "Could not read the account" not in result.stdout
    assert "Continue?" not in result.stdout
    assert calls(project) == []


def test_status_without_a_resources_array_fails(project: Path) -> None:
    result = run_destroy(project, STUB_STATUS_JSON=json.dumps({"project": "fleetsupervisor"}))

    assert result.returncode == 1
    assert "Could not read the agentcore status output" in result.stdout
    assert "Cleanup complete" not in result.stdout


def test_a_stack_left_in_aws_fails_even_when_status_reads_clean(project: Path) -> None:
    result = run_destroy(project, STUB_STACK_STATUS="DELETE_FAILED")

    assert result.returncode == 1
    assert "stack AgentCore-fleetsupervisor-default: DELETE_FAILED" in result.stdout
    assert "Cleanup complete" not in result.stdout


def test_a_provider_left_in_aws_fails_and_names_the_delete_command(project: Path) -> None:
    result = run_destroy(project, STUB_PROVIDER_EXISTS="1")

    assert result.returncode == 1
    assert "credential provider fleetsupervisor_default_fleet-gateway" in result.stdout
    assert "delete-oauth2-credential-provider --region us-west-2" in result.stdout


def test_an_aws_error_other_than_not_found_fails(project: Path) -> None:
    result = run_destroy(
        project,
        STUB_AWS_ERROR="An error occurred (ExpiredToken) when calling the DescribeStacks operation",
    )

    assert result.returncode == 1
    assert "Could not check AWS for remaining resources" in result.stdout
    assert "ExpiredToken" in result.stdout
    assert "Cleanup complete" not in result.stdout


def test_destroy_needs_no_credentials_file_and_restores_the_spec(project: Path) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    assert not (project.parent / ".mcp-credentials.json").exists()

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    assert not any(c.startswith("agentcore add") for c in logged)
    assert "agentcore remove runtime --name supervisor" in logged
    assert "agentcore deploy --target default --yes" in logged
    assert spec.read_bytes() == tracked


def test_an_interrupt_during_deploy_restores_the_spec_once(project: Path) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_destroy(project, STUB_DEPLOY_SIGNAL="INT")

    assert result.returncode == 130
    assert spec.read_bytes() == tracked
    assert "Could not restore" not in result.stderr
    assert "Cleanup complete" not in result.stdout


def test_destroy_strips_a_left_secret_line_and_keeps_the_file_mode(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text(
        "# OAuth client secret for credential provider 'fleet-gateway' (set before deploy)\n"
        "AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=encrypted-value\n"
        "OTHER_SETTING=kept\n"
    )
    env_local.chmod(0o600)

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert env_local.read_text() == "OTHER_SETTING=kept\n"
    assert stat.S_IMODE(env_local.stat().st_mode) == 0o600
    assert not list(env_local.parent.glob(".env.local.*"))


def test_destroy_strips_only_the_exact_secret_variable(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    kept = (
        "OLD_AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=other\n"
        "# AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET= is set by deploy\n"
    )
    # The CLI reads these forms too, so each one is removed.
    removed = (
        "AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\n"
        "export AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\n"
        "  AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\n"
        "\texport\tAGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET = value\n"
    )
    env_local.write_text(kept + removed)

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert env_local.read_text() == kept


def test_destroy_keeps_a_wider_file_mode(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o644)

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert env_local.read_text() == "A=1\n"
    assert stat.S_IMODE(env_local.stat().st_mode) == 0o644


def test_an_interrupt_during_the_secret_strip_leaves_no_copy(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o600)

    # cp 1 backs up the spec, cp 2 restores it, cp 3 starts the strip's copy.
    result = run_destroy(project, STUB_INTERRUPT_AFTER="cp:3")

    assert result.returncode == 130, result.stdout + result.stderr
    assert env_local.read_text() == "A=1\n"
    assert not list(env_local.parent.glob(".env.local.*"))
    assert not list((project.parent / "tmp").iterdir())


def test_a_failed_configure_leaves_no_temporary_project(project: Path) -> None:
    shutil.rmtree(project / "agentcore")

    result = run_agent(project, "configure")

    assert result.returncode != 0
    assert "agentcore create --name fleetsupervisor --skip-install --skip-git" in calls(project)
    assert not list((project.parent / "tmp").iterdir())
    assert not (project / "agentcore").exists()


# destroy makes six temporary files: the spec backup, the status errors, and
# an output and an errors file for each of the two AWS lookups.
@pytest.mark.parametrize("lost", range(1, 7))
def test_a_temporary_file_whose_name_was_lost_is_still_removed(project: Path, lost: int) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_destroy(project, STUB_MKTEMP_LOSE=str(lost))

    assert result.returncode != 0
    assert (project.parent / "mktemp-calls").read_text() == f"{lost}\n"
    assert spec.read_bytes() == tracked
    assert not list((project.parent / "tmp").iterdir())


def test_an_interrupt_during_an_aws_lookup_leaves_no_temporary_file(project: Path) -> None:
    result = run_destroy(project, STUB_LOOKUP_SIGNAL="INT")

    assert result.returncode != 0
    assert "Cleanup complete" not in result.stdout
    assert not list((project.parent / "tmp").iterdir())


def test_a_failed_restore_keeps_the_backup_it_names(project: Path) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    try:
        result = run_destroy(project, STUB_DEPLOY_LOCK_SPEC="1")
    finally:
        spec.chmod(0o644)

    assert result.returncode == 1
    message = f"Could not restore agentcore/agentcore.json. The backup is at {project.parent}/tmp/"
    assert message in result.stderr
    backup = Path(result.stderr.split("The backup is at ")[1].split("\x1b")[0].strip())
    assert backup.read_bytes() == tracked


def test_a_failed_spec_backup_leaves_no_temporary_file(project: Path) -> None:
    spec = project / "agentcore" / "agentcore.json"
    spec.chmod(0)
    try:
        result = run_destroy(project)
    finally:
        spec.chmod(0o644)

    assert result.returncode == 1
    assert not list((project.parent / "tmp").iterdir())
    assert not any(c.startswith("agentcore remove") for c in calls(project))


def test_an_interrupt_right_after_the_backup_is_removed_reports_no_failure(
    project: Path,
) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_destroy(project, STUB_INTERRUPT_AFTER="rm:1")

    assert result.returncode == 130
    assert spec.read_bytes() == tracked
    assert "Could not restore" not in result.stderr
    assert not list((project.parent / "tmp").iterdir())


def test_an_interrupt_during_the_restore_after_a_failed_deploy_still_finishes_it(
    project: Path,
) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")

    # The failed deploy exits through set -e while the INT trap still exits
    # 130. cp 1 backs up the spec and cp 2 restores it, so the Ctrl+C lands
    # mid-restore and only the EXIT trap ignoring INT lets the restore finish.
    result = run_destroy(project, STUB_DEPLOY_EXIT="1", STUB_INTERRUPT_AFTER="cp:2")

    assert result.returncode == 1
    assert spec.read_bytes() == tracked
    assert env_local.read_text() == "A=1\n"
    assert "Could not restore" not in result.stderr
    assert not list(env_local.parent.glob(".env.local.*"))
    assert not list((project.parent / "tmp").iterdir())


def test_a_second_interrupt_during_the_restore_still_finishes_it(project: Path) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")

    # The first Ctrl+C lands during deploy. cp 1 backs up the spec and cp 2
    # restores it from the EXIT trap, so the second lands mid-restore.
    result = run_destroy(project, STUB_DEPLOY_SIGNAL="INT", STUB_INTERRUPT_AFTER="cp:2")

    assert result.returncode == 130
    assert spec.read_bytes() == tracked
    assert env_local.read_text() == "A=1\n"
    assert "Could not restore" not in result.stderr
    assert not list(env_local.parent.glob(".env.local.*"))
    assert not list((project.parent / "tmp").iterdir())
