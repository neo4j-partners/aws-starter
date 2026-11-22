"""Tests for ``agent.sh destroy`` with stub ``agentcore`` and ``aws`` commands.

Each test copies agent.sh and the tracked agentcore.json into a temporary
folder and puts stub scripts first on PATH, so nothing reaches AWS. The stubs
log every call to calls.log and act on STUB_* environment variables.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path
from signal import SIGHUP, SIGINT, SIGTERM

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
        # destroy checks the stack before it deploys. While
        # STUB_STACK_BEFORE_DEPLOY is set, even to "", the lookups before the
        # deploy read only it and the STUB_PRECHECK_* settings, and the
        # settings below act on the lookups after the deploy. "" reads as a
        # stack that does not exist. deploy leaves it unset, so its own
        # lookup reads STUB_STACK_STATUS.
        if [ -n "${STUB_STACK_BEFORE_DEPLOY+set}" ] && ! grep -q "^agentcore deploy" "$STUB_LOG"; then
            if [ -n "${STUB_PRECHECK_SIGNAL:-}" ]; then kill -s "$STUB_PRECHECK_SIGNAL" "$PPID" "$$"; fi
            if [ -n "${STUB_PRECHECK_ERROR:-}" ]; then echo "$STUB_PRECHECK_ERROR" >&2; exit 254; fi
            # Replace .env.local with a link after agent.sh checked it.
            if [ -n "${STUB_PRECHECK_LINK_ENV_LOCAL:-}" ]; then
                rm -f agentcore/.env.local
                ln -s "$STUB_PRECHECK_LINK_ENV_LOCAL" agentcore/.env.local
            fi
            if [ -n "$STUB_STACK_BEFORE_DEPLOY" ]; then echo "$STUB_STACK_BEFORE_DEPLOY"; exit 0; fi
            echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id x does not exist" >&2
            exit 254
        fi
        # Ctrl+C reaches the whole foreground group, so the stub dies too.
        # bash ignores a SIGINT when its child exits normally.
        if [ -n "$STUB_LOOKUP_SIGNAL" ]; then kill -s "$STUB_LOOKUP_SIGNAL" "$PPID" "$$"; fi
        # A $(...) subshell may sit between this stub and agent.sh, so climb
        # to the outermost agent.sh.
        owner=$PPID
        while parent=$(ps -o ppid= -p "$owner" | tr -d ' ') \
            && ps -o command= -p "$parent" | grep -qF /agent.sh; do
            owner=$parent
        done
        # A signal to agent.sh alone, while this stub goes on to exit
        # normally.
        if [ -n "${STUB_LOOKUP_SIGNAL_SCRIPT:-}" ]; then
            kill -s "$STUB_LOOKUP_SIGNAL_SCRIPT" "$owner"
        fi
        # Leave a file that is not this run's copy: one at the old fixed
        # name, or another run's copy whose PID starts with this run's.
        case "${STUB_LOOKUP_PLANT_STRIP:-}" in
            old) printf 'OLD=1\n' > "agentcore/.env.local.strip.$owner" ;;
            other) printf 'OTHER=1\n' > "agentcore/.env.local.strip.${owner}0.AbC123" ;;
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

# rm, cp, mv, and awk pass through to the real command.
# STUB_INTERRUPT_AFTER=cmd:N sends SIGINT to agent.sh right after the Nth
# call of cmd, the same as a Ctrl+C, or STUB_INTERRUPT_SIGNAL instead.
# STUB_RECORD_STRIP_MODE records the strip copy's mode and size in bytes
# while it holds the lines: awk's after awk writes them to its standard
# output, which is the copy, and mv's before mv moves the copy. mv also
# records the copy's name and agent.sh's PID.
STUB_PASSTHROUGH = r"""#!/bin/bash
name="${0##*/}"
real=/bin/"$name"
[ -x "$real" ] || real=/usr/bin/"$name"
# Print agent.sh's PID, even from inside one of its subshells.
agent_pid() {
    local owner=$PPID parent
    while parent=$(ps -o ppid= -p "$owner" | tr -d ' ') \
        && ps -o command= -p "$parent" | grep -qF /agent.sh; do
        owner=$parent
    done
    echo "$owner"
}
# stat's flags differ between macOS and Linux, so Python reads the mode. It
# reads its own standard output when no file is named.
record_strip() {
    python3 -c 'import os, stat, sys
st = os.stat(sys.argv[3]) if len(sys.argv) > 3 else os.fstat(1)
named = [os.path.basename(sys.argv[3]), sys.argv[4]] if len(sys.argv) > 3 else []
with open(sys.argv[1], "a") as log:
    print(sys.argv[2], format(stat.S_IMODE(st.st_mode), "o"), st.st_size, *named, file=log)' \
        "${STUB_LOG%/*}/strip-modes" "$@"
}
if [ -n "${STUB_RECORD_STRIP_MODE:-}" ] && [ "$name" = mv ]; then
    case "${@: -2:1}" in
        *.env.local.strip.*) record_strip mv "${@: -2:1}" "$(agent_pid)" ;;
    esac
fi
"$real" "$@"
status=$?
if [ -n "${STUB_RECORD_STRIP_MODE:-}" ] && [ "$name" = awk ]; then
    record_strip awk
fi
counter="${STUB_LOG%/*}/$name-calls"
count=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
echo "$count" > "$counter"
if [ "${STUB_INTERRUPT_AFTER:-}" = "$name:$count" ]; then
    kill -s "${STUB_INTERRUPT_SIGNAL:-INT}" "$(agent_pid)"
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

# npm logs its arguments and working folder. An install writes
# node_modules/.package-lock.json, as a complete real install does, unless
# STUB_NPM_EXIT makes it fail. As in real npm, `npm ci` refuses to run
# without package-lock.json, and `npm install` writes one.
STUB_NPM = r"""#!/bin/bash
echo "npm $* in ${PWD##*/supervisor-agent/}" >> "$STUB_LOG"
if [ -n "${STUB_NPM_EXIT:-}" ]; then echo "npm ERR! stub failure" >&2; exit "$STUB_NPM_EXIT"; fi
if [ "$1" = ci ] && [ ! -f package-lock.json ]; then
    echo "npm ERR! The npm ci command can only install with an existing package-lock.json" >&2
    exit 1
fi
if [ "$1" = install ]; then echo "{}" > package-lock.json; fi
mkdir -p node_modules
echo "{}" > node_modules/.package-lock.json
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
    (root / "agentcore" / "cdk").mkdir(parents=True)
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
        ("npm", STUB_NPM),
        ("rm", STUB_PASSTHROUGH),
        ("cp", STUB_PASSTHROUGH),
        ("mv", STUB_PASSTHROUGH),
        ("awk", STUB_PASSTHROUGH),
        ("uv", "#!/bin/bash\n"),
    ):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    # The CDK dependencies are installed unless a test removes them. The
    # tracked lockfile is older than the install, as after a clean install.
    lock = root / "agentcore" / "cdk" / "package-lock.json"
    lock.write_text("{}")
    install = root / "agentcore" / "cdk" / "node_modules"
    install.mkdir()
    (install / ".package-lock.json").write_text("{}")
    past = time.time() - 60
    os.utime(lock, (past, past))
    return root


def run_destroy(
    project: Path, umask: int = -1, **stub_env: str
) -> subprocess.CompletedProcess[str]:
    # The stack exists when destroy starts, unless a test says otherwise.
    stub_env = {"STUB_STACK_BEFORE_DEPLOY": "CREATE_COMPLETE", **stub_env}
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


def calls_after_deploy(project: Path) -> list[str]:
    logged = calls(project)
    return logged[logged.index("agentcore deploy --target default --yes") + 1 :]


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
    after = calls_after_deploy(project)
    assert not any(c.startswith(("aws cloudformation", "aws bedrock")) for c in after)


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


SECRET_LINE = "AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\n"
ABSENT_MESSAGE = (
    "Stack AgentCore-fleetsupervisor-default does not exist in us-west-2, "
    "so there is nothing to remove."
)


# With no stack there is nothing to remove. destroy skips the prompt, the
# CDK install, and the deploy, which the CLI fails when no stack exists.
def test_an_absent_stack_skips_the_deploy_and_succeeds(project: Path) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    remove_cdk_install(project)

    result = run_agent(project, "destroy", STUB_STACK_BEFORE_DEPLOY="")

    assert result.returncode == 0, result.stdout + result.stderr
    assert ABSENT_MESSAGE in result.stdout
    assert "Cleanup complete. Nothing is deployed in target 'default'." in result.stdout
    assert "Continue?" not in result.stdout
    logged = calls(project)
    assert not any(c.startswith(("agentcore remove", "agentcore deploy", "npm")) for c in logged)
    assert any("get-oauth2-credential-provider" in c for c in logged)
    assert spec.read_bytes() == tracked
    assert not list((project.parent / "tmp").iterdir())


# An interrupted deploy can leave the secret line in .env.local with no
# stack deployed. The restore after a deploy removes it, and so does this.
def test_an_absent_stack_still_strips_a_left_secret_line(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text(SECRET_LINE + "A=1\n")
    env_local.chmod(0o600)

    result = run_destroy(project, STUB_STACK_BEFORE_DEPLOY="")

    assert result.returncode == 0, result.stdout + result.stderr
    assert ABSENT_MESSAGE in result.stdout
    assert env_local.read_text() == "A=1\n"
    assert stat.S_IMODE(env_local.stat().st_mode) == 0o600
    assert not list(env_local.parent.glob(".env.local.*"))
    assert not any(c.startswith("agentcore deploy") for c in calls(project))


def test_an_absent_stack_with_a_provider_left_fails_and_names_the_delete_command(
    project: Path,
) -> None:
    result = run_destroy(project, STUB_STACK_BEFORE_DEPLOY="", STUB_PROVIDER_EXISTS="1")

    assert result.returncode == 1
    assert ABSENT_MESSAGE in result.stdout
    assert "credential provider fleetsupervisor_default_fleet-gateway" in result.stdout
    assert (
        "aws bedrock-agentcore-control delete-oauth2-credential-provider --region us-west-2 "
        "--name fleetsupervisor_default_fleet-gateway"
    ) in result.stdout
    assert "Cleanup complete" not in result.stdout
    assert not any(c.startswith(("agentcore remove", "agentcore deploy")) for c in calls(project))


def test_an_aws_error_in_the_stack_check_fails_before_any_change(project: Path) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_agent(
        project,
        "destroy",
        STUB_STACK_BEFORE_DEPLOY="CREATE_COMPLETE",
        STUB_PRECHECK_ERROR="An error occurred (ExpiredToken) when calling the DescribeStacks operation",
    )

    assert result.returncode == 1
    assert (
        "Could not check stack AgentCore-fleetsupervisor-default in us-west-2 with CloudFormation:"
        in result.stdout
    )
    assert "ExpiredToken" in result.stdout
    assert "Continue?" not in result.stdout
    assert not any(c.startswith("agentcore") for c in calls(project))
    assert spec.read_bytes() == tracked
    assert not list((project.parent / "tmp").iterdir())


# The start check passed, then .env.local became a link before the strip on
# the path with no stack. The strip refuses, and no later step retries it.
def test_an_absent_stack_with_a_failed_strip_fails_and_says_to_delete_by_hand(
    project: Path,
) -> None:
    target = project.parent / "shared.env"
    target.write_text(SECRET_LINE + "A=1\n")
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("A=1\n")

    result = run_destroy(
        project, STUB_STACK_BEFORE_DEPLOY="", STUB_PRECHECK_LINK_ENV_LOCAL=str(target)
    )

    assert result.returncode == 1
    assert ABSENT_MESSAGE in result.stdout
    assert "agentcore/.env.local is a symbolic link" in result.stderr
    assert (
        "Delete the AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET line "
        "from agentcore/.env.local by hand." in result.stderr
    )
    assert env_local.is_symlink()
    assert target.read_text() == SECRET_LINE + "A=1\n"
    assert not list(env_local.parent.glob(".env.local.*"))
    assert "Cleanup complete" not in result.stdout
    assert not any(c.startswith(("agentcore remove", "agentcore deploy")) for c in calls(project))


def test_an_interrupt_during_the_stack_check_leaves_no_temporary_file(project: Path) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_destroy(project, STUB_PRECHECK_SIGNAL="INT")

    assert result.returncode == -SIGINT
    assert not any(c.startswith("agentcore") for c in calls(project))
    assert spec.read_bytes() == tracked
    assert not list((project.parent / "tmp").iterdir())


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


# The run dies by the signal that stopped it, so a calling shell sees a
# signal death and stops too.
@pytest.mark.parametrize(
    ("signal", "code"), [("INT", -SIGINT), ("TERM", -SIGTERM), ("HUP", -SIGHUP)]
)
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


# The copy's name is this run's PID plus a random suffix, so on_exit removes
# only this run's copies. A file at the old fixed name, or another run's copy
# whose PID starts with this run's digits, is left as it is.
@pytest.mark.parametrize(
    ("planted", "name", "content"),
    [
        ("old", r"\.env\.local\.strip\.\d+", "OLD=1\n"),
        ("other", r"\.env\.local\.strip\.\d+0\.AbC123", "OTHER=1\n"),
    ],
)
def test_on_exit_leaves_a_strip_copy_name_that_is_not_this_runs(
    project: Path, planted: str, name: str, content: str
) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o600)

    result = run_destroy(project, STUB_LOOKUP_PLANT_STRIP=planted)

    assert result.returncode == 0, result.stdout + result.stderr
    assert env_local.read_text() == "A=1\n"
    left = list(env_local.parent.glob(".env.local.*"))
    assert len(left) == 1, left
    assert re.fullmatch(name, left[0].name)
    assert left[0].read_text() == content


# mktemp creates the copy with mode 0600, under umask 077 as well. The copy
# holds the lines only after awk writes them and until mv moves it, and it
# is 0600 at both points. Its name is the PID prefix plus mktemp's six
# random characters, so a fixed name that a umask alone made 0600 fails.
def test_the_copy_is_0600_while_it_holds_data_under_a_wide_umask(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o600)

    result = run_destroy(project, umask=0o022, STUB_RECORD_STRIP_MODE="1")

    assert result.returncode == 0, result.stdout + result.stderr
    awk_line, mv_line = (project.parent / "strip-modes").read_text().splitlines()
    assert awk_line == "awk 600 4"
    tool, mode, size, copy, pid = mv_line.split()
    assert (tool, mode, size) == ("mv", "600", "4")
    assert re.fullmatch(rf"\.env\.local\.strip\.{pid}\.\w{{6}}", copy)
    assert env_local.read_text() == "A=1\n"
    assert stat.S_IMODE(env_local.stat().st_mode) == 0o600


def test_an_interrupt_during_the_secret_strip_leaves_no_copy(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("AGENTCORE_CREDENTIAL_FLEET_GATEWAY_CLIENT_SECRET=value\nA=1\n")
    env_local.chmod(0o600)

    # The strip's awk has written the copy, and mv has not replaced the file.
    result = run_destroy(project, STUB_INTERRUPT_AFTER="awk:1")

    assert result.returncode == -SIGINT, result.stdout + result.stderr
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


# npm ci installs exactly what the tracked package-lock.json lists and
# never rewrites it, unlike npm install.
def test_configure_installs_the_cdk_dependencies_with_npm_ci(project: Path) -> None:
    result = run_agent(project, "configure")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project) == ["npm ci in agentcore/cdk"]


# agentcore create --skip-install scaffolds agentcore/cdk with no
# package-lock.json, and npm ci refuses to run without one.
def test_configure_without_a_package_lock_installs_with_npm_install(project: Path) -> None:
    lock = project / "agentcore" / "cdk" / "package-lock.json"
    lock.unlink()

    result = run_agent(project, "configure")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project) == ["npm install in agentcore/cdk"]
    assert lock.is_file()


DISCOVERY_URL = "https://cognito-idp.example/.well-known/openid-configuration"

# The system tools agent.sh runs before it installs the CDK dependencies.
# make_temp hides mkdir's errors, so a missing tool does not always print
# "command not found". The no-npm test checks that the run got as far as
# the npm check.
SYSTEM_TOOLS = ("bash", "cat", "dirname", "find", "grep", "jq", "mkdir", "sed", "tr")


def remove_cdk_install(project: Path) -> None:
    shutil.rmtree(project / "agentcore" / "cdk" / "node_modules")


def isolate_path(project: Path) -> str:
    """Return a PATH that holds only the stubs and links to SYSTEM_TOOLS.

    A test that removes a stub needs this, so a real npm in /usr/bin is not
    found in its place.
    """
    isolated = project.parent / "isolated-bin"
    isolated.mkdir()
    for stub in (project.parent / "bin").iterdir():
        (isolated / stub.name).symlink_to(stub)
    for name in SYSTEM_TOOLS:
        tool = shutil.which(name)
        assert tool is not None, f"{name} is not on PATH"
        (isolated / name).symlink_to(tool)
    return str(isolated)


def test_deploy_installs_missing_cdk_dependencies_first(project: Path) -> None:
    ready_to_deploy(project)
    remove_cdk_install(project)

    result = run_agent(project, "deploy", STUB_STACK_STATUS=DISCOVERY_URL)

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    assert logged[0] == "npm ci in agentcore/cdk"
    assert "agentcore deploy" in logged
    assert (project / "agentcore" / "cdk" / "node_modules" / ".package-lock.json").is_file()


def test_deploy_skips_npm_when_cdk_dependencies_are_installed(project: Path) -> None:
    ready_to_deploy(project)

    result = run_agent(project, "deploy", STUB_STACK_STATUS=DISCOVERY_URL)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(call.startswith("npm") for call in calls(project))


def test_deploy_without_a_package_lock_installs_with_npm_install(project: Path) -> None:
    ready_to_deploy(project)
    remove_cdk_install(project)
    lock = project / "agentcore" / "cdk" / "package-lock.json"
    lock.unlink()

    result = run_agent(project, "deploy", STUB_STACK_STATUS=DISCOVERY_URL)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project)[0] == "npm install in agentcore/cdk"
    assert lock.is_file()


def test_a_failed_cdk_install_without_a_package_lock_names_npm_install(
    project: Path,
) -> None:
    ready_to_deploy(project)
    remove_cdk_install(project)
    (project / "agentcore" / "cdk" / "package-lock.json").unlink()

    result = run_agent(project, "deploy", STUB_STACK_STATUS=DISCOVERY_URL, STUB_NPM_EXIT="1")

    assert result.returncode == 1
    assert "npm install failed in agentcore/cdk" in result.stdout
    assert "(cd agentcore/cdk && npm install)" in result.stdout


# A pull that changes package-lock.json leaves it newer than the install,
# which then has the old CDK libraries.
# destroy reads the stack status as a stack that is still deployed, so only
# deploy gets one. destroy gets a stack that exists before its deploy.
@pytest.mark.parametrize(
    ("args", "stub_env"),
    [
        (("deploy",), {"STUB_STACK_STATUS": DISCOVERY_URL}),
        (("destroy", "--yes"), {"STUB_STACK_BEFORE_DEPLOY": "CREATE_COMPLETE"}),
    ],
)
def test_a_package_lock_newer_than_the_install_is_installed_again(
    project: Path, args: tuple[str, ...], stub_env: dict[str, str]
) -> None:
    ready_to_deploy(project)
    cdk = project / "agentcore" / "cdk"
    newer = (cdk / "node_modules" / ".package-lock.json").stat().st_mtime + 10
    os.utime(cdk / "package-lock.json", (newer, newer))

    result = run_agent(project, *args, **stub_env)

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    first_agentcore = next(i for i, call in enumerate(logged) if call.startswith("agentcore"))
    assert logged.index("npm ci in agentcore/cdk") < first_agentcore


# A failed npm ci can leave node_modules without the lockfile that npm
# writes only after a complete install.
def test_a_partial_cdk_install_is_installed_again(project: Path) -> None:
    ready_to_deploy(project)
    (project / "agentcore" / "cdk" / "node_modules" / ".package-lock.json").unlink()

    result = run_agent(project, "deploy", STUB_STACK_STATUS=DISCOVERY_URL)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project)[0] == "npm ci in agentcore/cdk"


@pytest.mark.parametrize("args", [("deploy",), ("destroy", "--yes")])
def test_a_failed_cdk_install_stops_before_the_spec_changes(
    project: Path, args: tuple[str, ...]
) -> None:
    ready_to_deploy(project)
    remove_cdk_install(project)
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_agent(project, *args, STUB_STACK_STATUS=DISCOVERY_URL, STUB_NPM_EXIT="1")

    assert result.returncode == 1
    assert "npm ci failed in agentcore/cdk" in result.stdout
    assert "(cd agentcore/cdk && npm ci)" in result.stdout
    assert not any(call.startswith("agentcore") for call in calls(project))
    assert spec.read_bytes() == tracked
    assert not list((project.parent / "tmp").iterdir())


def test_deploy_without_npm_names_the_install_step(project: Path) -> None:
    ready_to_deploy(project)
    remove_cdk_install(project)
    (project.parent / "bin" / "npm").unlink()
    path = isolate_path(project)
    assert shutil.which("npm", path=path) is None
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_agent(project, "deploy", PATH=path)

    assert result.returncode == 1
    assert "command not found" not in result.stderr, result.stderr
    assert "npm is not installed" in result.stdout
    assert "(cd agentcore/cdk && npm ci)" in result.stdout
    assert calls(project) == []
    assert spec.read_bytes() == tracked


def test_destroy_installs_missing_cdk_dependencies_before_removing(project: Path) -> None:
    remove_cdk_install(project)

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    assert logged.index("npm ci in agentcore/cdk") < logged.index(
        "agentcore remove runtime --name supervisor"
    )


# destroy makes nine temporary files: an output and an errors file for the
# stack check before the deploy, the spec backup, the strip copy, the status
# errors, and an output and an errors file for each of the two AWS lookups
# after the deploy.
@pytest.mark.parametrize("lost", range(1, 10))
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


# A Ctrl+C during a lookup after the restore stops the run, and on_exit
# still removes the temporary files. The run dies by SIGINT with or without
# the restore trap, so the trap reset is tested with a signal to agent.sh
# alone, and the re-raise by the deploy signal tests.
def test_an_interrupt_during_an_aws_lookup_leaves_no_temporary_file(project: Path) -> None:
    result = run_destroy(project, STUB_LOOKUP_SIGNAL="INT")

    assert result.returncode == -SIGINT
    assert "Cleanup complete" not in result.stdout
    assert not list((project.parent / "tmp").iterdir())


# A SIGINT sent to agent.sh alone, while its child exits normally, does not
# stop bash once end_spec_restore resets the INT trap. A trap left in place
# would exit through on_exit and die by SIGINT instead.
def test_an_interrupt_to_the_script_alone_after_the_restore_lets_it_finish(
    project: Path,
) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_destroy(project, STUB_LOOKUP_SIGNAL_SCRIPT="INT")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Cleanup complete" in result.stdout
    assert spec.read_bytes() == tracked
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

    # The stack check before the deploy makes rm calls 1 and 2.
    result = run_destroy(project, STUB_INTERRUPT_AFTER="rm:3")

    assert result.returncode == -SIGINT
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

    assert result.returncode == -SIGINT
    assert spec.read_bytes() == tracked
    assert env_local.read_text() == "A=1\n"
    assert "Could not restore" not in result.stderr
    assert not list(env_local.parent.glob(".env.local.*"))
    assert not list((project.parent / "tmp").iterdir())
