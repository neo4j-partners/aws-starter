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
    add)
        # The CLI reads the secret on stdin and writes it to .env.local.
        cat > /dev/null
        printf '%s\n' "AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=encrypted" \
            >> agentcore/.env.local
        ;;
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
        # Replace .env.local with a link after agent.sh checked it.
        if [ -n "$STUB_DEPLOY_LINK_ENV_LOCAL" ]; then
            rm -f agentcore/.env.local
            ln -s "$STUB_DEPLOY_LINK_ENV_LOCAL" agentcore/.env.local
        fi
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
        # Leave something at the strip copy's name for agent.sh's pid. A
        # $(...) subshell may sit between, so climb to the outermost agent.sh.
        owner=$PPID
        while parent=$(ps -o ppid= -p "$owner" | tr -d ' ') \
            && ps -o command= -p "$parent" | grep -qF /agent.sh; do
            owner=$parent
        done
        strip_copy="agentcore/.env.local.strip.$owner"
        case "${STUB_LOOKUP_PLANT_STRIP:-}" in
            fifo) mkfifo "$strip_copy" ;;
            dangling) ln -s "$STUB_TMP/missing" "$strip_copy" ;;
            devnull) ln -s /dev/null "$strip_copy" ;;
            stale) printf 'STALE=1\n' > "$strip_copy" ;;
        esac
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

# rm, cp, mv, awk, and chmod pass through to the real command. STUB_INTERRUPT_AFTER
# =cmd:N sends SIGINT to agent.sh right after the Nth call of cmd, the same as
# a Ctrl+C, or STUB_INTERRUPT_SIGNAL instead. STUB_PLANT_AFTER_STRIP_RM=N writes a file at the strip copy's
# name right after the Nth rm of that name, or with STUB_PLANT_DEVNULL a link
# to /dev/null. STUB_SKIP_STRIP_CHMOD makes chmod of the copy succeed without
# running. STUB_RECORD_STRIP_MODE makes awk
# record the copy's mode while the copy exists. STUB_RECORD_STRIP_SIZE makes
# chmod record the copy's size in bytes before it changes the mode.
STUB_PASSTHROUGH = r"""#!/bin/bash
name="${0##*/}"
real=/bin/"$name"
[ -x "$real" ] || real=/usr/bin/"$name"
if [ "$name" = chmod ] && [ -n "${STUB_RECORD_STRIP_SIZE:-}" ]; then
    case "${!#}" in
        *.env.local.strip.*)
            wc -c < "${!#}" | tr -d ' ' >> "${STUB_LOG%/*}/strip-sizes" ;;
    esac
fi
case "$name:${STUB_SKIP_STRIP_CHMOD:-}:${!#}" in
    chmod:?*:*.env.local.strip.*) status=0 ;;
    *) "$real" "$@"; status=$? ;;
esac
counter="${STUB_LOG%/*}/$name-calls"
count=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
echo "$count" > "$counter"
if [ "${STUB_INTERRUPT_AFTER:-}" = "$name:$count" ]; then
    # Signal agent.sh itself, even from inside one of its subshells.
    owner=$PPID
    while parent=$(ps -o ppid= -p "$owner" | tr -d ' ') \
        && ps -o command= -p "$parent" | grep -qF /agent.sh; do
        owner=$parent
    done
    kill -s "${STUB_INTERRUPT_SIGNAL:-INT}" "$owner"
fi
if [ "$name" = rm ] && [ -n "${STUB_PLANT_AFTER_STRIP_RM:-}" ]; then
    case "${!#}" in
        *.env.local.strip.*)
            counter="${STUB_LOG%/*}/strip-rm-calls"
            count=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
            echo "$count" > "$counter"
            if [ "$count" = "$STUB_PLANT_AFTER_STRIP_RM" ]; then
                if [ -n "${STUB_PLANT_DEVNULL:-}" ]; then
                    ln -s /dev/null "${!#}"
                else
                    printf 'PLANTED=1\n' > "${!#}"
                fi
            fi
            ;;
    esac
fi
if [ "$name" = awk ] && [ -n "${STUB_RECORD_STRIP_MODE:-}" ]; then
    for copy in agentcore/.env.local.strip.*; do
        [ -f "$copy" ] && stat -f %Lp "$copy" >> "${STUB_LOG%/*}/strip-modes"
    done
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
        ("awk", STUB_PASSTHROUGH),
        ("chmod", STUB_PASSTHROUGH),
        ("uv", "#!/bin/bash\n"),
    ):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return root


def run_destroy(
    project: Path, umask: int = -1, **stub_env: str
) -> subprocess.CompletedProcess[str]:
    return run_agent(project, "destroy", "--yes", umask=umask, **stub_env)


def run_agent(
    project: Path, *args: str, stdin: str = "", umask: int = -1, **stub_env: str
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
        umask=umask,
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


def target_with_account(account: object) -> str:
    return json.dumps([{"name": "default", "account": account, "region": "us-west-2"}])


# An account must be a 12-digit string. Anything else would reach STS and
# compare as a mismatch, or match by accident.
@pytest.mark.parametrize(
    "targets",
    [
        "[]",
        "not json",
        '[{"name": "default"}]',
        target_with_account(""),
        target_with_account("12345"),
        target_with_account("1111 2222 3333"),
        target_with_account(111122223333),
    ],
)
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


# Each signal exits with 128 plus its number, as the shell reports it.
@pytest.mark.parametrize(("signal", "code"), [("INT", 130), ("TERM", 143), ("HUP", 129)])
def test_an_interrupt_during_deploy_restores_the_spec_once(
    project: Path, signal: str, code: int
) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_destroy(project, STUB_DEPLOY_SIGNAL=signal)

    assert result.returncode == code
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
        # The CLI's \s also matches a vertical tab and a form feed.
        "\x0bAGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\n"
        "export\x0cAGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET\x0b=value\n"
    )
    env_local.write_text(kept + removed)

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert env_local.read_text() == kept


# The CLI writes .env.local with mode 0600, so the rewrite does the same.
def test_destroy_narrows_a_wider_file_mode_to_0600(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o644)

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert env_local.read_text() == "A=1\n"
    assert stat.S_IMODE(env_local.stat().st_mode) == 0o600


# mv would replace the link with a regular file and leave the secret in the
# link's target, so a linked .env.local stops the run before anything changes.
@pytest.mark.parametrize(
    ("args", "stdin"), [(("destroy", "--yes"), ""), (("destroy",), "y\n"), (("deploy",), "")]
)
def test_a_linked_env_local_is_refused_before_any_change(
    project: Path, args: tuple[str, ...], stdin: str
) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    target = project.parent / "shared.env"
    target.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local = project / "agentcore" / ".env.local"
    env_local.symlink_to(target)

    result = run_agent(project, *args, stdin=stdin)

    assert result.returncode == 1
    assert "agentcore/.env.local is a symbolic link" in result.stdout
    assert "Continue?" not in result.stdout
    assert env_local.is_symlink()
    assert target.read_text() == "AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n"
    assert spec.read_bytes() == tracked
    assert not any("deploy" in call or "remove" in call or "add" in call for call in calls(project))


# The start check passed, then .env.local became a link. mv would replace
# the link and leave the secret in its target, so the strip refuses.
def test_a_link_made_after_the_start_check_is_not_replaced(project: Path) -> None:
    target = project.parent / "shared.env"
    target.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("A=1\n")

    result = run_destroy(project, STUB_DEPLOY_LINK_ENV_LOCAL=str(target))

    assert result.returncode == 1
    assert "agentcore/.env.local is a symbolic link" in result.stderr
    # The restore was the last try, so the line is left to delete by hand.
    assert (
        "Delete the AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET line "
        "from agentcore/.env.local by hand." in result.stderr
    )
    assert env_local.is_symlink()
    assert target.read_text() == "AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n"
    assert not list(env_local.parent.glob(".env.local.*"))


def ready_to_deploy(project: Path) -> None:
    """Add what deploy reads before the strip: a venv, ../.env, and credentials."""
    (project / ".venv").mkdir()
    (project.parent / ".env").write_text("")
    (project.parent / ".mcp-credentials.json").write_text(
        json.dumps(
            {
                "client_id": "id",
                "client_secret": "secret",
                "scope": "fleet/invoke",
                "stack_name": "neo4j-mcp-server-fleet",
            }
        )
    )


# Whatever sits at the copy's name is removed first, so the copy is always a
# new regular file. Before, a FIFO hung the open, a link to /dev/null took
# the lines, and a dangling link or a stale copy stopped the deploy.
@pytest.mark.parametrize("planted", ["fifo", "dangling", "devnull", "stale"])
def test_anything_left_at_the_copy_name_does_not_stop_the_strip(
    project: Path, planted: str
) -> None:
    ready_to_deploy(project)
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o600)

    result = run_agent(
        project,
        "deploy",
        STUB_STACK_STATUS="https://cognito-idp.example/.well-known/openid-configuration",
        STUB_LOOKUP_PLANT_STRIP=planted,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not env_local.is_symlink()
    assert env_local.read_text() == "A=1\n"
    assert stat.S_IMODE(env_local.stat().st_mode) == 0o600
    assert not list(env_local.parent.glob(".env.local.*"))


# set -C refuses a file that appears at the copy's name between the strip's
# remove and its create. The deploy stops, and on_exit's restore strips the
# line with a fresh copy.
def test_a_file_made_at_the_copy_name_after_the_remove_is_refused(project: Path) -> None:
    ready_to_deploy(project)
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o600)

    result = run_agent(
        project,
        "deploy",
        STUB_STACK_STATUS="https://cognito-idp.example/.well-known/openid-configuration",
        STUB_PLANT_AFTER_STRIP_RM="1",
    )

    assert result.returncode == 1
    assert "cannot overwrite existing file" in result.stderr
    # The restore removed the line, so nothing is left to do by hand.
    assert "by hand" not in result.stderr
    assert not any(
        call.startswith(("agentcore add", "agentcore deploy")) for call in calls(project)
    )
    assert env_local.read_text() == "A=1\n"
    assert not list(env_local.parent.glob(".env.local.*"))


# set -C opens a link to a device. chmod of the root-owned /dev/null would
# fail, so the stub skips it, and only the regular-file check stops mv from
# putting the link in place of .env.local.
def test_a_link_to_a_device_made_at_the_copy_name_is_refused(project: Path) -> None:
    ready_to_deploy(project)
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o600)

    result = run_agent(
        project,
        "deploy",
        STUB_STACK_STATUS="https://cognito-idp.example/.well-known/openid-configuration",
        STUB_PLANT_AFTER_STRIP_RM="1",
        STUB_PLANT_DEVNULL="1",
        STUB_SKIP_STRIP_CHMOD="1",
    )

    assert result.returncode == 1
    assert "Could not remove" in result.stderr
    assert not any(
        call.startswith(("agentcore add", "agentcore deploy")) for call in calls(project)
    )
    assert not env_local.is_symlink()
    assert env_local.read_text() == "A=1\n"
    assert not list(env_local.parent.glob(".env.local.*"))


# umask 077 creates the copy with mode 0600, so the filtered lines are never
# readable by others, even before chmod.
def test_the_copy_is_0600_while_it_exists_under_a_wide_umask(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o600)

    result = run_destroy(project, umask=0o022, STUB_RECORD_STRIP_MODE="1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (project.parent / "strip-modes").read_text() == "600\n"
    assert stat.S_IMODE(env_local.stat().st_mode) == 0o600


# A default ACL on Linux can override umask 077, so chmod must set 0600
# before any line lands in the copy.
def test_the_copy_is_0600_before_any_line_is_written(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o600)

    result = run_destroy(project, STUB_RECORD_STRIP_SIZE="1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (project.parent / "strip-sizes").read_text() == "0\n"
    assert env_local.read_text() == "A=1\n"


def test_an_interrupt_during_the_secret_strip_leaves_no_copy(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o600)

    # The strip's awk has written the copy, and mv has not replaced the file.
    result = run_destroy(project, STUB_INTERRUPT_AFTER="awk:1")

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
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")

    result = run_destroy(project, STUB_MKTEMP_LOSE=str(lost))

    assert result.returncode != 0
    assert (project.parent / "mktemp-calls").read_text() == f"{lost}\n"
    assert spec.read_bytes() == tracked
    assert not list(env_local.parent.glob(".env.local.*"))
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


# A closed terminal sends HUP, and kill sends TERM, so on_exit ignores both
# as well as INT.
@pytest.mark.parametrize("signal", ["INT", "TERM", "HUP"])
def test_an_interrupt_during_the_restore_after_a_failed_deploy_still_finishes_it(
    project: Path, signal: str
) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")

    # The failed deploy exits through set -e while the INT trap still exits
    # 130. cp 1 backs up the spec and cp 2 restores it, so the Ctrl+C lands
    # mid-restore and only the EXIT trap ignoring INT lets the restore finish.
    result = run_destroy(
        project, STUB_DEPLOY_EXIT="1", STUB_INTERRUPT_AFTER="cp:2", STUB_INTERRUPT_SIGNAL=signal
    )

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
