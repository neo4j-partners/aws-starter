"""Tests for agent.sh with stub ``agentcore``, ``aws``, ``npm``, and ``uv`` commands.

Each test copies agent.sh and the tracked agentcore.json into a temporary
folder and puts stub scripts first on PATH, so nothing reaches AWS. The stubs
log every call to calls.log and act on STUB_* environment variables. The uv
stub runs the helper scripts agent.sh feeds to ``uv run --quiet python -``
with this test run's Python, which has python-dotenv.
"""

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from signal import SIGHUP, SIGINT, SIGTERM

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "111122223333"
RUNTIME_NAME = "fraud_memory_agent"
RUNTIME_ID = "FraudMemory_default_fraud_memory_agent-AbCdE12345"
LOG_PREFIX = f"/aws/bedrock-agentcore/runtimes/{RUNTIME_ID}-"
LOG_GROUP = f"{LOG_PREFIX}DEFAULT"
STACK = "AgentCore-FraudMemory-default"
GATEWAY_PROVIDER = "FraudMemory_default_fraud-gateway"
NAMS_PROVIDER = "FraudMemory_default_nams-api-key"
RUNTIME_TYPE = "AWS::BedrockAgentCore::Runtime"
# The logical ID the synthesized stack gives the Runtime.
RUNTIME_LOGICAL_ID = "ApplicationRuntimeFraudMemoryAgentRuntime1B54FC56"
RUNTIME_ARN = f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:runtime/{RUNTIME_ID}"
DEPLOY_CALL = "agentcore deploy"
DESTROY_DEPLOY_CALL = "agentcore deploy --target default --yes"

GATEWAY_VAR = "AGENTCORE_CREDENTIAL_FRAUD_GATEWAY_CLIENT_SECRET"
NAMS_VAR = "AGENTCORE_CREDENTIAL_NAMS_API_KEY"
GATEWAY_COMMENT = (
    "# OAuth client secret for credential provider 'fraud-gateway' (set before deploy)"
)
NAMS_COMMENT = "# API key for credential provider 'nams-api-key' (set before deploy)"
SECRET_LINES = f"{GATEWAY_VAR}=value\n{NAMS_VAR}=value\n"
NAMS_KEY = "nams-key-from-env-file"
CLIENT_SECRET = "gateway-client-secret"

# A helper that prints its own PID's agent.sh ancestor. A $(...) subshell or a
# pipeline may sit between a stub and agent.sh, so it climbs to the outermost
# agent.sh.
AGENT_PID = r"""
agent_pid() {
    local owner=$PPID parent
    while parent=$(ps -o ppid= -p "$owner" | tr -d ' ') \
        && ps -o command= -p "$parent" | grep -qF /agent.sh; do
        owner=$parent
    done
    echo "$owner"
}
"""

STUB_AGENTCORE = (
    r"""#!/bin/bash
echo "agentcore $*" >> "$STUB_LOG"
"""
    + AGENT_PID
    + r"""
case "$1" in
    status) printf '%s\n' "$STUB_STATUS_JSON" ;;
    add)
        # `add credentials <type> --name <name> ...`. The CLI reads the
        # secret on stdin, declares the credential in agentcore.json, and
        # writes the encrypted secret to .env.local under a comment line.
        cat > "${STUB_LOG%/*}/stdin-$3"
        if [ -n "${STUB_ADD_EXIT:-}" ]; then exit "$STUB_ADD_EXIT"; fi
        jq --arg n "$5" '.credentials += [{"name": $n}]' \
            agentcore/agentcore.json > agentcore/agentcore.json.stub
        mv agentcore/agentcore.json.stub agentcore/agentcore.json
        case "$3" in
            oauth)
                printf '%s\n' "# OAuth client secret for credential provider '$5' (set before deploy)" \
                    "AGENTCORE_CREDENTIAL_FRAUD_GATEWAY_CLIENT_SECRET=encrypted" >> agentcore/.env.local
                ;;
            api-key)
                printf '%s\n' "# API key for credential provider '$5' (set before deploy)" \
                    "AGENTCORE_CREDENTIAL_NAMS_API_KEY=encrypted" >> agentcore/.env.local
                ;;
        esac
        ;;
    remove)
        jq --arg n "$4" 'del(.runtimes[] | select(.name == $n))' \
            agentcore/agentcore.json > agentcore/agentcore.json.stub
        mv agentcore/agentcore.json.stub agentcore/agentcore.json
        ;;
    deploy)
        # Record what the CDK process would see.
        {
            echo "credentials=$(jq -c '[.credentials[].name]' agentcore/agentcore.json)"
            echo "GATEWAY_URL=${GATEWAY_URL:-}"
            echo "GATEWAY_SCOPES=${GATEWAY_SCOPES:-}"
            echo "MEMORY_ENDPOINT=${MEMORY_ENDPOINT:-}"
            echo "MEMORY_API_KEY=${MEMORY_API_KEY+set}"
        } >> "${STUB_LOG%/*}/deploy-env"
        if [ -n "${STUB_DEPLOY_TARGETS:-}" ]; then
            printf '%s\n' "$STUB_DEPLOY_TARGETS" > agentcore/aws-targets.json
        fi
        if [ -n "${STUB_DEPLOY_LOCK_SPEC:-}" ]; then chmod 0444 agentcore/agentcore.json; fi
        # Replace .env.local with a link after agent.sh checked it.
        if [ -n "${STUB_DEPLOY_LINK_ENV_LOCAL:-}" ]; then
            rm -f agentcore/.env.local
            ln -s "$STUB_DEPLOY_LINK_ENV_LOCAL" agentcore/.env.local
        fi
        if [ -n "${STUB_DEPLOY_SIGNAL:-}" ]; then kill -s "$STUB_DEPLOY_SIGNAL" "$PPID"; fi
        exit "${STUB_DEPLOY_EXIT:-0}"
        ;;
    invoke)
        [ -z "${STUB_INVOKE_OUTPUT:-}" ] || printf '%s\n' "$STUB_INVOKE_OUTPUT"
        # Ctrl+C reaches the whole foreground group, so the stub dies too.
        if [ -n "${STUB_INVOKE_SIGNAL:-}" ]; then kill -s "$STUB_INVOKE_SIGNAL" "$(agent_pid)" "$$"; fi
        exit "${STUB_INVOKE_EXIT:-0}"
        ;;
    logs) ;;
    *) exit 99 ;;
esac
"""
)

STUB_AWS = (
    r"""#!/bin/bash
echo "aws $*" >> "$STUB_LOG"
"""
    + AGENT_PID
    + r"""
case "$1 $2" in
    "sts get-caller-identity")
        if [ -n "${STUB_STS_ERROR:-}" ]; then echo "$STUB_STS_ERROR" >&2; exit 254; fi
        echo "${STUB_CALLER_ACCOUNT:-111122223333}"
        ;;
    "cloudformation describe-stack-resources")
        # Prints STUB_STACK_RESOURCES, or fails with STUB_STACK_RESOURCES_ERROR.
        if [ -n "${STUB_STACK_RESOURCES_ERROR:-}" ]; then echo "$STUB_STACK_RESOURCES_ERROR" >&2; exit 254; fi
        printf '%s\n' "$STUB_STACK_RESOURCES"
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
        if [ -n "${STUB_LOOKUP_SIGNAL:-}" ]; then kill -s "$STUB_LOOKUP_SIGNAL" "$PPID" "$$"; fi
        owner=$(agent_pid)
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
        if [ -n "${STUB_AWS_ERROR:-}" ]; then echo "$STUB_AWS_ERROR" >&2; exit 254; fi
        if [ -n "${STUB_STACK_STATUS:-}" ]; then echo "$STUB_STACK_STATUS"; exit 0; fi
        echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id x does not exist" >&2
        exit 254
        ;;
    # describe-log-groups lists the STUB_LOG_GROUPS names that start with
    # the prefix in $4. delete-log-group fails for a name in
    # STUB_LOG_DELETE_FAIL and reports a name in STUB_LOG_MISSING as not
    # found.
    "logs describe-log-groups")
        if [ -n "${STUB_LOGS_LIST_ERROR:-}" ]; then echo "$STUB_LOGS_LIST_ERROR" >&2; exit 254; fi
        for name in ${STUB_LOG_GROUPS:-}; do
            if [[ "$name" == "$4"* ]]; then echo "$name"; fi
        done
        ;;
    "logs delete-log-group")
        case " ${STUB_LOG_DELETE_FAIL:-} " in
            *" $4 "*) echo "An error occurred (AccessDeniedException) when calling the DeleteLogGroup operation" >&2; exit 254 ;;
        esac
        case " ${STUB_LOG_MISSING:-} " in
            *" $4 "*) echo "An error occurred (ResourceNotFoundException) when calling the DeleteLogGroup operation" >&2; exit 254 ;;
        esac
        ;;
    "bedrock-agentcore-control get-oauth2-credential-provider")
        if [ -n "${STUB_GATEWAY_PROVIDER_EXISTS:-}" ]; then echo '{}'; exit 0; fi
        echo "An error occurred (ResourceNotFoundException) when calling the GetOauth2CredentialProvider operation: CredentialProvider not found" >&2
        exit 254
        ;;
    "bedrock-agentcore-control get-api-key-credential-provider")
        if [ -n "${STUB_NAMS_PROVIDER_EXISTS:-}" ]; then echo '{}'; exit 0; fi
        echo "An error occurred (ResourceNotFoundException) when calling the GetApiKeyCredentialProvider operation: CredentialProvider not found" >&2
        exit 254
        ;;
    *) exit 99 ;;
esac
"""
)

# rm, cp, mv, and awk pass through to the real command.
# STUB_INTERRUPT_AFTER=cmd:N sends SIGINT to agent.sh right after the Nth
# call of cmd, the same as a Ctrl+C, or STUB_INTERRUPT_SIGNAL instead.
# STUB_RECORD_STRIP_MODE records the strip copy's mode and size in bytes
# while it holds the lines: awk's after awk writes them to its standard
# output, which is the copy, and mv's before mv moves the copy. mv also
# records the copy's name and agent.sh's PID.
STUB_PASSTHROUGH = (
    r"""#!/bin/bash
name="${0##*/}"
real=/bin/"$name"
[ -x "$real" ] || real=/usr/bin/"$name"
"""
    + AGENT_PID
    + r"""
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
)

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
# without package-lock.json.
STUB_NPM = r"""#!/bin/bash
echo "npm $* in ${PWD##*/fraud-memory-agent/}" >> "$STUB_LOG"
if [ -n "${STUB_NPM_EXIT:-}" ]; then echo "npm ERR! stub failure" >&2; exit "$STUB_NPM_EXIT"; fi
if [ "$1" = ci ] && [ ! -f package-lock.json ]; then
    echo "npm ERR! The npm ci command can only install with an existing package-lock.json" >&2
    exit 1
fi
mkdir -p node_modules
echo "{}" > node_modules/.package-lock.json
"""

# uv runs agent.sh's `uv run --quiet python -` helpers with STUB_PYTHON and
# does nothing else. It logs nothing, so call order checks see only AWS,
# AgentCore, and npm.
STUB_UV = r"""#!/bin/bash
if [ "$1" = run ] && [ "$2" = --quiet ] && [ "$3" = python ]; then
    shift 3
    exec "$STUB_PYTHON" "$@"
fi
exit 0
"""

# Stands in for .venv/bin/python, which runs the verify script.
STUB_VENV_PYTHON = r"""#!/bin/bash
echo "python $*" >> "$STUB_LOG"
exit "${STUB_VERIFY_EXIT:-0}"
"""

CLEAN_STATUS = json.dumps(
    {
        "resources": [
            {"resourceType": "runtime", "name": RUNTIME_NAME, "deploymentState": "local-only"}
        ]
    }
)

DEPLOYED_STATUS = json.dumps(
    {
        "resources": [
            {
                "resourceType": "runtime",
                "name": RUNTIME_NAME,
                "deploymentState": "deployed",
                "arn": RUNTIME_ARN,
            }
        ]
    }
)


def _stack_resources(*resources: tuple[object, object, object]) -> str:
    """The describe-stack-resources output for (type, logical ID, physical ID) triples."""
    return json.dumps(
        {
            "StackResources": [
                {"ResourceType": kind, "LogicalResourceId": logical, "PhysicalResourceId": physical}
                for kind, logical, physical in resources
            ]
        }
    )


# The stack as the deploy leaves it: the Runtime, its role, and a resource
# of another type.
DEPLOYED_RESOURCES = _stack_resources(
    (RUNTIME_TYPE, RUNTIME_LOGICAL_ID, RUNTIME_ARN),
    ("AWS::IAM::Role", "ApplicationRuntimeFraudMemoryAgentRuntimeRole1A2B3C4D", "role"),
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "fraud-memory-agent"
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
        ("uv", STUB_UV),
    ):
        write_executable(bin_dir / name, body)
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


def write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


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
        "STUB_PYTHON": sys.executable,
        "STUB_STATUS_JSON": CLEAN_STATUS,
        "STUB_STACK_RESOURCES": DEPLOYED_RESOURCES,
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
    return logged[logged.index(DESTROY_DEPLOY_CALL) + 1 :]


def test_clean_destroy_checks_aws_by_name_and_succeeds(project: Path) -> None:
    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Cleanup complete" in result.stdout
    assert not list((project.parent / "tmp").iterdir())
    logged = calls(project)
    assert any(f"describe-stacks --region us-west-2 --stack-name {STACK}" in c for c in logged)
    assert any(
        f"get-oauth2-credential-provider --region us-west-2 --name {GATEWAY_PROVIDER}" in c
        for c in logged
    )
    assert any(
        f"get-api-key-credential-provider --region us-west-2 --name {NAMS_PROVIDER}" in c
        for c in logged
    )
    # The account is checked before the first agentcore call and again
    # after the deploy, before the lookups.
    sts = "aws sts get-caller-identity --query Account --output text --region us-west-2"
    assert logged[0] == sts
    deploy = logged.index(DESTROY_DEPLOY_CALL)
    assert sts in logged[deploy:]


def test_destroy_asks_first_and_names_both_providers(project: Path) -> None:
    result = run_agent(project, "destroy", stdin="y\n", STUB_STACK_BEFORE_DEPLOY="CREATE_COMPLETE")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "This deletes the fraud_memory_agent Runtime, the fraud-gateway and nams-api-key "
        "credential providers, and the stack in target 'default'." in result.stdout
    )
    assert "Cleanup complete" in result.stdout


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
    assert DESTROY_DEPLOY_CALL in calls(project)
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
    result = run_destroy(project, STUB_STATUS_JSON=json.dumps({"project": "FraudMemory"}))

    assert result.returncode == 1
    assert "Could not read the agentcore status output" in result.stdout
    assert "Cleanup complete" not in result.stdout


def test_a_stack_left_in_aws_fails_even_when_status_reads_clean(project: Path) -> None:
    result = run_destroy(project, STUB_STACK_STATUS="DELETE_FAILED")

    assert result.returncode == 1
    assert f"stack {STACK}: DELETE_FAILED" in result.stdout
    assert "Cleanup complete" not in result.stdout


def test_a_gateway_provider_left_in_aws_fails_and_names_the_delete_command(
    project: Path,
) -> None:
    result = run_destroy(project, STUB_GATEWAY_PROVIDER_EXISTS="1")

    assert result.returncode == 1
    assert f"credential provider {GATEWAY_PROVIDER}" in result.stdout
    assert (
        "aws bedrock-agentcore-control delete-oauth2-credential-provider --region us-west-2 "
        f"--name {GATEWAY_PROVIDER}"
    ) in result.stdout
    assert NAMS_PROVIDER not in result.stdout


def test_a_nams_provider_left_in_aws_fails_and_names_the_delete_command(project: Path) -> None:
    result = run_destroy(project, STUB_NAMS_PROVIDER_EXISTS="1")

    assert result.returncode == 1
    assert f"credential provider {NAMS_PROVIDER}" in result.stdout
    assert (
        "aws bedrock-agentcore-control delete-api-key-credential-provider --region us-west-2 "
        f"--name {NAMS_PROVIDER}"
    ) in result.stdout
    assert GATEWAY_PROVIDER not in result.stdout
    assert "Cleanup complete" not in result.stdout


ABSENT_MESSAGE = f"Stack {STACK} does not exist in us-west-2, so there is nothing to remove."
BY_HAND = f"Delete the {GATEWAY_VAR} and {NAMS_VAR} lines from agentcore/.env.local by hand."


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
    assert any("get-api-key-credential-provider" in c for c in logged)
    assert spec.read_bytes() == tracked
    assert not list((project.parent / "tmp").iterdir())


# An interrupted deploy can leave the secret lines in .env.local with no
# stack deployed. The restore after a deploy removes them, and so does this.
def test_an_absent_stack_still_strips_left_secret_lines(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text(SECRET_LINES + "A=1\n")
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
    result = run_destroy(project, STUB_STACK_BEFORE_DEPLOY="", STUB_NAMS_PROVIDER_EXISTS="1")

    assert result.returncode == 1
    assert ABSENT_MESSAGE in result.stdout
    assert f"credential provider {NAMS_PROVIDER}" in result.stdout
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
    assert f"Could not check stack {STACK} in us-west-2 with CloudFormation:" in result.stdout
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
    target.write_text(SECRET_LINES + "A=1\n")
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("A=1\n")

    result = run_destroy(
        project, STUB_STACK_BEFORE_DEPLOY="", STUB_PRECHECK_LINK_ENV_LOCAL=str(target)
    )

    assert result.returncode == 1
    assert ABSENT_MESSAGE in result.stdout
    assert "agentcore/.env.local is a symbolic link" in result.stderr
    assert BY_HAND in result.stderr
    assert env_local.is_symlink()
    assert target.read_text() == SECRET_LINES + "A=1\n"
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


def test_destroy_needs_no_local_secrets_and_restores_the_spec(project: Path) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    assert not (project.parent / ".mcp-credentials.json").exists()
    assert not (project.parent / ".env").exists()

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    assert not any(c.startswith("agentcore add") for c in logged)
    assert f"agentcore remove runtime --name {RUNTIME_NAME}" in logged
    assert DESTROY_DEPLOY_CALL in logged
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


def test_destroy_strips_left_secret_lines_and_keeps_the_file_mode(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text(
        f"{GATEWAY_COMMENT}\n{GATEWAY_VAR}=encrypted-value\n"
        f"{NAMS_COMMENT}\n{NAMS_VAR}=encrypted-value\n"
        "OTHER_SETTING=kept\n"
    )
    env_local.chmod(0o600)

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert env_local.read_text() == "OTHER_SETTING=kept\n"
    assert stat.S_IMODE(env_local.stat().st_mode) == 0o600
    assert not list(env_local.parent.glob(".env.local.*"))


@pytest.mark.parametrize("var", [GATEWAY_VAR, NAMS_VAR])
def test_destroy_strips_only_the_exact_secret_variables(project: Path, var: str) -> None:
    env_local = project / "agentcore" / ".env.local"
    kept = f"OLD_{var}=other\n# {var}= is set by deploy\n{var}_OLD=other\n"
    # The CLI reads these forms too, so each one is removed.
    removed = (
        f"{var}=value\n"
        f"export {var}=value\n"
        f"  {var}=value\n"
        f"\texport\t{var} = value\n"
        # The CLI's \s also matches a vertical tab and a form feed.
        f"\x0b{var}=value\n"
        f"export\x0c{var}\x0b=value\n"
    )
    env_local.write_text(kept + removed)

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert env_local.read_text() == kept


# The CLI writes .env.local with mode 0600, so the rewrite does the same.
def test_destroy_narrows_a_wider_file_mode_to_0600(project: Path) -> None:
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text(SECRET_LINES + "A=1\n")
    env_local.chmod(0o644)

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert env_local.read_text() == "A=1\n"
    assert stat.S_IMODE(env_local.stat().st_mode) == 0o600


# mv would replace the link with a regular file and leave the secrets in the
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
    target.write_text(SECRET_LINES + "A=1\n")
    env_local = project / "agentcore" / ".env.local"
    env_local.symlink_to(target)

    result = run_agent(project, *args, stdin=stdin)

    assert result.returncode == 1
    assert "agentcore/.env.local is a symbolic link" in result.stdout
    assert "Continue?" not in result.stdout
    assert env_local.is_symlink()
    assert target.read_text() == SECRET_LINES + "A=1\n"
    assert spec.read_bytes() == tracked
    assert not any("deploy" in call or "remove" in call or "add" in call for call in calls(project))


# The start check passed, then .env.local became a link. mv would replace
# the link and leave the secrets in its target, so the strip refuses.
def test_a_link_made_after_the_start_check_is_not_replaced(project: Path) -> None:
    target = project.parent / "shared.env"
    target.write_text(SECRET_LINES + "A=1\n")
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("A=1\n")

    result = run_destroy(project, STUB_DEPLOY_LINK_ENV_LOCAL=str(target))

    assert result.returncode == 1
    assert "agentcore/.env.local is a symbolic link" in result.stderr
    # The restore was the last try, so the lines are left to delete by hand.
    assert BY_HAND in result.stderr
    assert env_local.is_symlink()
    assert target.read_text() == SECRET_LINES + "A=1\n"
    assert not list(env_local.parent.glob(".env.local.*"))


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
    env_local.write_text(SECRET_LINES + "A=1\n")
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
    env_local.write_text(SECRET_LINES + "A=1\n")
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
    env_local.write_text(SECRET_LINES + "A=1\n")
    env_local.chmod(0o600)

    # The strip's awk has written the copy, and mv has not replaced the file.
    result = run_destroy(project, STUB_INTERRUPT_AFTER="awk:1")

    assert result.returncode == -SIGINT, result.stdout + result.stderr
    assert env_local.read_text() == "A=1\n"
    assert not list(env_local.parent.glob(".env.local.*"))
    assert not list((project.parent / "tmp").iterdir())


# --- deploy ---

DISCOVERY_URL = "https://cognito-idp.example/.well-known/openid-configuration"
GATEWAY_URL = "https://gateway.example/mcp"

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


def ready_to_deploy(project: Path, env_file: str = f"MEMORY_API_KEY={NAMS_KEY}\n") -> None:
    """Add what deploy reads: a venv, ../.env, and ../.mcp-credentials.json."""
    (project / ".venv" / "bin").mkdir(parents=True)
    write_executable(project / ".venv" / "bin" / "python", STUB_VENV_PYTHON)
    (project.parent / ".env").write_text(env_file)
    (project.parent / ".mcp-credentials.json").write_text(
        json.dumps(
            {
                "gateway_url": GATEWAY_URL,
                "client_id": "id",
                "client_secret": CLIENT_SECRET,
                "scope": "fraud/invoke",
                "stack_name": "neo4j-mcp-server-finance",
            }
        )
    )


def run_deploy(project: Path, *args: str, **stub_env: str) -> subprocess.CompletedProcess[str]:
    """Deploy with the Cognito discovery URL as the MCP stack's output."""
    stub_env = {"STUB_STACK_STATUS": DISCOVERY_URL, **stub_env}
    return run_agent(project, "deploy", *args, **stub_env)


def deploy_env(project: Path) -> dict[str, str]:
    lines = (project.parent / "deploy-env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_deploy_declares_both_credentials_and_restores_the_spec(project: Path) -> None:
    ready_to_deploy(project)
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text("A=1\n")

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    assert (
        "agentcore add credentials oauth --name fraud-gateway --client-id id "
        f"--discovery-url {DISCOVERY_URL} --scopes fraud/invoke --client-secret -"
    ) in logged
    assert "agentcore add credentials api-key --name nams-api-key --api-key -" in logged
    assert logged[-1] == DEPLOY_CALL
    seen = deploy_env(project)
    assert seen["credentials"] == '["fraud-gateway","nams-api-key"]'
    assert seen["GATEWAY_URL"] == GATEWAY_URL
    assert seen["GATEWAY_SCOPES"] == "fraud/invoke"
    # The tracked spec is back, and the CLI's secret lines are gone.
    assert spec.read_bytes() == tracked
    assert env_local.read_text() == "A=1\n"
    assert not list(env_local.parent.glob(".env.local.*"))
    assert not list((project.parent / "tmp").iterdir())
    assert "the smoke test was skipped" in result.stdout


# The secrets reach the CLI on stdin only, never in argv or the output.
def test_deploy_sends_the_secrets_on_stdin_only(project: Path) -> None:
    ready_to_deploy(project)

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (project.parent / "stdin-oauth").read_text().strip() == CLIENT_SECRET
    assert (project.parent / "stdin-api-key").read_text() == NAMS_KEY
    log = (project.parent / "calls.log").read_text()
    for secret in (CLIENT_SECRET, NAMS_KEY):
        assert secret not in log
        assert secret not in result.stdout + result.stderr


def test_a_shell_memory_api_key_wins_and_stays_out_of_the_deploy(project: Path) -> None:
    ready_to_deploy(project)

    result = run_deploy(project, "--skip-smoke", MEMORY_API_KEY="shell-key")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (project.parent / "stdin-api-key").read_text() == "shell-key"
    assert deploy_env(project)["MEMORY_API_KEY"] == ""


def test_deploy_copies_memory_settings_but_not_the_key(project: Path) -> None:
    ready_to_deploy(
        project,
        env_file=f"MEMORY_API_KEY={NAMS_KEY}\nMEMORY_ENDPOINT=https://nams.example\n",
    )

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 0, result.stdout + result.stderr
    seen = deploy_env(project)
    assert seen["MEMORY_ENDPOINT"] == "https://nams.example"
    assert seen["MEMORY_API_KEY"] == ""


@pytest.mark.parametrize("env_file", ["", "MEMORY_API_KEY=\n", "MEMORY_API_KEY=   \n"])
def test_a_missing_nams_key_stops_before_the_deploy(project: Path, env_file: str) -> None:
    ready_to_deploy(project, env_file=env_file)
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    env_local = project / "agentcore" / ".env.local"

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 1
    assert "MEMORY_API_KEY is not set" in result.stdout
    logged = calls(project)
    assert DEPLOY_CALL not in logged
    assert not any(c.startswith("agentcore add credentials api-key") for c in logged)
    # The Gateway credential was added first. The restore undoes it.
    assert spec.read_bytes() == tracked
    assert GATEWAY_VAR not in env_local.read_text()


def test_a_missing_shared_env_stops_before_any_change(project: Path) -> None:
    ready_to_deploy(project)
    (project.parent / ".env").unlink()

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 1
    assert "../.env not found" in result.stdout or ".env not found" in result.stdout
    assert calls(project) == []


def test_a_missing_credentials_file_stops_before_any_change(project: Path) -> None:
    ready_to_deploy(project)
    (project.parent / ".mcp-credentials.json").unlink()

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 1
    assert ".mcp-credentials.json not found" in result.stdout
    assert calls(project) == []


def test_mcp_credentials_file_overrides_the_credentials_path(project: Path) -> None:
    ready_to_deploy(project)
    other = project.parent / "other-credentials.json"
    (project.parent / ".mcp-credentials.json").rename(other)

    result = run_deploy(project, "--skip-smoke", MCP_CREDENTIALS_FILE=str(other))

    assert result.returncode == 0, result.stdout + result.stderr
    assert deploy_env(project)["GATEWAY_URL"] == GATEWAY_URL


@pytest.mark.parametrize("credential", ["fraud-gateway", "nams-api-key"])
def test_a_spec_that_already_declares_a_credential_is_refused(
    project: Path, credential: str
) -> None:
    ready_to_deploy(project)
    spec = project / "agentcore" / "agentcore.json"
    data = json.loads(spec.read_text())
    data["credentials"] = [{"name": credential}]
    spec.write_text(json.dumps(data))
    leftover = spec.read_bytes()

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 1
    assert f"already declares the {credential} credential" in result.stdout
    assert "git checkout -- agentcore/agentcore.json" in result.stdout
    assert DEPLOY_CALL not in calls(project)
    assert spec.read_bytes() == leftover


@pytest.mark.parametrize(
    "path",
    [".env", ".env.local", ".mcp-credentials.json", ".mcp.json", "server/.env", "key.pem"],
)
def test_a_secret_file_in_the_zip_folder_stops_the_deploy(project: Path, path: str) -> None:
    ready_to_deploy(project)
    secret = project / path
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("x")

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 1
    assert "secret files are inside" in result.stdout
    assert f"./{path}" in result.stdout
    assert calls(project) == []


def test_a_link_to_a_secret_file_stops_the_deploy(project: Path) -> None:
    ready_to_deploy(project)
    (project / "notes.txt").symlink_to(project.parent / ".env")
    (project / "linked").symlink_to(project.parent, target_is_directory=False)

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 1
    assert "./linked/.env" in result.stdout
    assert calls(project) == []


def test_a_venv_folder_without_the_dot_stops_the_deploy(project: Path) -> None:
    ready_to_deploy(project)
    (project / "venv").mkdir()

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 1
    assert "./venv" in result.stdout
    assert calls(project) == []


def test_files_the_zip_skips_do_not_stop_the_deploy(project: Path) -> None:
    ready_to_deploy(project)
    (project / ".venv" / ".env").write_text("x")
    (project / "agentcore" / ".env.local").write_text("A=1\n")

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 0, result.stdout + result.stderr


def test_an_unknown_deploy_option_exits_2(project: Path) -> None:
    result = run_agent(project, "deploy", "--force")

    assert result.returncode == 2
    assert "Unknown deploy option: --force" in result.stdout
    assert calls(project) == []


def test_deploy_runs_the_smoke_test_against_the_deployed_arn(project: Path) -> None:
    ready_to_deploy(project)

    result = run_deploy(project, STUB_STATUS_JSON=DEPLOYED_STATUS)

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    assert logged[-1] == f"python scripts/verify_agentcore_runtime.py --runtime-arn {RUNTIME_ARN}"
    assert "agentcore status --json --target default" in logged
    assert "Deployment verified and ready for traffic." in result.stdout


def test_a_failed_smoke_test_fails_the_deploy(project: Path) -> None:
    ready_to_deploy(project)

    result = run_deploy(project, STUB_STATUS_JSON=DEPLOYED_STATUS, STUB_VERIFY_EXIT="1")

    assert result.returncode == 1
    assert "it was not verified as healthy" in result.stdout
    assert "./agent.sh verify" in result.stdout


def test_a_failed_deploy_skips_the_smoke_test_and_restores(project: Path) -> None:
    ready_to_deploy(project)
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    env_local = project / "agentcore" / ".env.local"

    result = run_deploy(project, STUB_DEPLOY_EXIT="3")

    assert result.returncode == 3
    assert not any(c.startswith("python") for c in calls(project))
    assert spec.read_bytes() == tracked
    assert env_local.read_text() == ""


def test_deploy_installs_missing_cdk_dependencies_first(project: Path) -> None:
    ready_to_deploy(project)
    remove_cdk_install(project)

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    assert logged[0] == "npm ci in agentcore/cdk"
    assert DEPLOY_CALL in logged
    assert (project / "agentcore" / "cdk" / "node_modules" / ".package-lock.json").is_file()


def test_deploy_skips_npm_when_cdk_dependencies_are_installed(project: Path) -> None:
    ready_to_deploy(project)

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(call.startswith("npm") for call in calls(project))


# A pull that changes package-lock.json leaves it newer than the install,
# which then has the old CDK libraries.
@pytest.mark.parametrize(
    ("args", "stub_env"),
    [
        (("deploy", "--skip-smoke"), {"STUB_STACK_STATUS": DISCOVERY_URL}),
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

    result = run_deploy(project, "--skip-smoke")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project)[0] == "npm ci in agentcore/cdk"


@pytest.mark.parametrize("args", [("deploy", "--skip-smoke"), ("destroy", "--yes")])
def test_a_failed_cdk_install_stops_before_the_spec_changes(
    project: Path, args: tuple[str, ...]
) -> None:
    ready_to_deploy(project)
    remove_cdk_install(project)
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_agent(
        project,
        *args,
        STUB_STACK_STATUS=DISCOVERY_URL,
        STUB_STACK_BEFORE_DEPLOY="CREATE_COMPLETE",
        STUB_NPM_EXIT="1",
    )

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

    result = run_deploy(project, "--skip-smoke", PATH=path)

    assert result.returncode == 1
    assert "command not found" not in result.stderr, result.stderr
    assert "npm is not installed" in result.stdout
    assert "(cd agentcore/cdk && npm ci)" in result.stdout
    assert calls(project) == []
    assert spec.read_bytes() == tracked


def test_a_missing_spec_points_to_git_checkout(project: Path) -> None:
    (project / "agentcore" / "agentcore.json").unlink()

    result = run_agent(project, "deploy")

    assert result.returncode == 1
    assert "git checkout -- agentcore/agentcore.json" in result.stdout
    assert calls(project) == []


def test_destroy_installs_missing_cdk_dependencies_before_removing(project: Path) -> None:
    remove_cdk_install(project)

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    assert logged.index("npm ci in agentcore/cdk") < logged.index(
        f"agentcore remove runtime --name {RUNTIME_NAME}"
    )


# destroy makes eleven temporary files before the log group cleanup: an
# output and an errors file for the stack check before the deploy, the spec
# backup, the strip copy, the status errors, and an output and an errors
# file for each of the three AWS lookups after the deploy. The log group
# cleanup makes the twelfth.
@pytest.mark.parametrize("lost", range(1, 13))
def test_a_temporary_file_whose_name_was_lost_is_still_removed(project: Path, lost: int) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()
    env_local = project / "agentcore" / ".env.local"
    env_local.write_text(SECRET_LINES + "A=1\n")

    result = run_destroy(project, STUB_MKTEMP_LOSE=str(lost))

    assert result.returncode != 0
    assert (project.parent / "mktemp-calls").read_text() == f"{lost}\n"
    assert spec.read_bytes() == tracked
    assert not list(env_local.parent.glob(".env.local.*"))
    assert not list((project.parent / "tmp").iterdir())


# A Ctrl+C during a lookup after the restore stops the run, and on_exit
# still removes the temporary files.
def test_an_interrupt_during_an_aws_lookup_leaves_no_temporary_file(project: Path) -> None:
    result = run_destroy(project, STUB_LOOKUP_SIGNAL="INT")

    assert result.returncode == -SIGINT
    assert "Cleanup complete" not in result.stdout
    assert not list((project.parent / "tmp").iterdir())


# A SIGINT sent to agent.sh alone, while its child exits normally, does not
# stop bash once end_spec_restore resets the INT trap.
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

    # The stack check before the deploy makes rm calls 1 and 2. The restore
    # then removes any strip copy with rm 3 and the spec backup with rm 4.
    result = run_destroy(project, STUB_INTERRUPT_AFTER="rm:4")

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
    env_local.write_text(SECRET_LINES + "A=1\n")

    # cp 1 backs up the spec and cp 2 restores it, so the signal lands
    # mid-restore and only the EXIT trap ignoring it lets the restore finish.
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
    env_local.write_text(SECRET_LINES + "A=1\n")

    result = run_destroy(project, STUB_DEPLOY_SIGNAL="INT", STUB_INTERRUPT_AFTER="cp:2")

    assert result.returncode == -SIGINT
    assert spec.read_bytes() == tracked
    assert env_local.read_text() == "A=1\n"
    assert "Could not restore" not in result.stderr
    assert not list(env_local.parent.glob(".env.local.*"))
    assert not list((project.parent / "tmp").iterdir())


# --- log groups ---


def logs_calls(project: Path) -> list[str]:
    return [c for c in calls(project) if c.startswith("aws logs ")]


def test_destroy_removes_only_the_runtime_log_groups(project: Path) -> None:
    # Another Runtime's ID starts with the same characters, but its group
    # does not start with the prefix, which ends with the dash after the ID.
    other = f"/aws/bedrock-agentcore/runtimes/{RUNTIME_ID}6-DEFAULT"

    result = run_destroy(project, STUB_LOG_GROUPS=f"{LOG_GROUP} {other}")

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Removed: log group {LOG_GROUP}" in result.stdout
    assert "Cleanup complete. Nothing is deployed in target 'default'." in result.stdout
    assert logs_calls(project) == [
        f"aws logs describe-log-groups --log-group-name-prefix {LOG_PREFIX} --region us-west-2 "
        "--query logGroups[].[logGroupName] --output text",
        f"aws logs delete-log-group --log-group-name {LOG_GROUP} --region us-west-2",
    ]
    assert not list((project.parent / "tmp").iterdir())


def test_no_runtime_log_groups_are_reported_as_not_found(project: Path) -> None:
    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Not found: log groups under {LOG_PREFIX} in us-west-2" in result.stdout
    assert not any(c.startswith("aws logs delete-log-group") for c in calls(project))


def test_a_log_group_gone_before_its_delete_is_not_an_error(project: Path) -> None:
    result = run_destroy(project, STUB_LOG_GROUPS=LOG_GROUP, STUB_LOG_MISSING=LOG_GROUP)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Not found: log group {LOG_GROUP}" in result.stdout


def test_a_failed_log_group_delete_names_the_group_and_fails(project: Path) -> None:
    second = f"{LOG_PREFIX}other"

    result = run_destroy(
        project, STUB_LOG_GROUPS=f"{LOG_GROUP} {second}", STUB_LOG_DELETE_FAIL=LOG_GROUP
    )

    assert result.returncode == 1
    assert "AccessDeniedException" in result.stderr
    assert f"Could not delete these log groups in us-west-2:\x1b[0m\n  {LOG_GROUP}\n" in (
        result.stdout
    )
    assert f"Removed: log group {second}" in result.stdout
    assert "Cleanup complete" not in result.stdout
    assert not list((project.parent / "tmp").iterdir())


def test_a_failed_log_group_listing_fails(project: Path) -> None:
    result = run_destroy(
        project,
        STUB_LOGS_LIST_ERROR="An error occurred (ExpiredToken) when calling DescribeLogGroups",
    )

    assert result.returncode == 1
    assert f"Could not list the log groups under {LOG_PREFIX} in us-west-2." in result.stdout
    assert "ExpiredToken" in result.stderr
    assert "Cleanup complete" not in result.stdout


def test_destroy_reads_the_runtime_id_from_the_stack_before_the_deploy(project: Path) -> None:
    result = run_destroy(project, STUB_LOG_GROUPS=LOG_GROUP)

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    read = (
        f"aws cloudformation describe-stack-resources --stack-name {STACK} "
        "--region us-west-2 --output json"
    )
    assert logged.index(read) < logged.index(f"agentcore remove runtime --name {RUNTIME_NAME}")
    assert f"Removed: log group {LOG_GROUP}" in result.stdout


def test_a_bare_runtime_id_as_the_physical_id_is_used(project: Path) -> None:
    resources = _stack_resources((RUNTIME_TYPE, RUNTIME_LOGICAL_ID, RUNTIME_ID))

    result = run_destroy(project, STUB_LOG_GROUPS=LOG_GROUP, STUB_STACK_RESOURCES=resources)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Removed: log group {LOG_GROUP}" in result.stdout


@pytest.mark.parametrize(
    "resources",
    [
        _stack_resources(("AWS::IAM::Role", "Role", "role")),
        _stack_resources((RUNTIME_TYPE, "ApplicationRuntimeOtherRuntime1B54FC56", RUNTIME_ARN)),
        _stack_resources(("AWS::IAM::Role", RUNTIME_LOGICAL_ID, RUNTIME_ARN)),
        _stack_resources(
            (RUNTIME_TYPE, RUNTIME_LOGICAL_ID, RUNTIME_ARN),
            (RUNTIME_TYPE, "ApplicationRuntimeFraudMemoryAgentRuntime12345678", RUNTIME_ARN),
        ),
        _stack_resources((RUNTIME_TYPE, RUNTIME_LOGICAL_ID, None)),
        _stack_resources((RUNTIME_TYPE, RUNTIME_LOGICAL_ID, "")),
        _stack_resources((RUNTIME_TYPE, RUNTIME_LOGICAL_ID, RUNTIME_NAME)),
        _stack_resources((RUNTIME_TYPE, RUNTIME_LOGICAL_ID, f"{RUNTIME_ARN}*")),
        _stack_resources(
            (RUNTIME_TYPE, RUNTIME_LOGICAL_ID, f"arn:aws:iam::{ACCOUNT}:runtime/{RUNTIME_ID}")
        ),
        "not json",
        json.dumps({"Stacks": []}),
    ],
)
def test_destroy_without_a_runtime_id_skips_the_log_groups(project: Path, resources: str) -> None:
    result = run_destroy(project, STUB_LOG_GROUPS=LOG_GROUP, STUB_STACK_RESOURCES=resources)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No Runtime ID was found in the stack" in result.stdout
    assert "Cleanup complete. Nothing is deployed in target 'default'." in result.stdout
    assert logs_calls(project) == []


@pytest.mark.parametrize(
    "stub_env",
    [
        {"STUB_DEPLOY_EXIT": "3"},
        {"STUB_STACK_STATUS": "DELETE_FAILED"},
        {"STUB_STACK_BEFORE_DEPLOY": ""},
    ],
)
def test_the_log_groups_stay_unless_the_teardown_finishes(
    project: Path, stub_env: dict[str, str]
) -> None:
    run_destroy(project, STUB_LOG_GROUPS=LOG_GROUP, **stub_env)

    assert logs_calls(project) == []


def test_a_cancelled_destroy_keeps_the_log_groups(project: Path) -> None:
    result = run_agent(
        project,
        "destroy",
        stdin="n\n",
        STUB_STACK_BEFORE_DEPLOY="CREATE_COMPLETE",
        STUB_LOG_GROUPS=LOG_GROUP,
    )

    assert result.returncode == 1
    assert "Cancelled. Nothing was changed." in result.stdout
    assert logs_calls(project) == []


# --- invoke-cloud, verify, logs ---


def invoke_call(prompt: str, user_id: str = "demo-user") -> str:
    payload = json.dumps({"prompt": prompt, "user_id": user_id}, separators=(",", ":"))
    return f"agentcore invoke --runtime {RUNTIME_NAME} --payload {payload}"


def test_a_successful_response_is_printed_and_exits_0(project: Path) -> None:
    output = 'data: {"type": "chunk", "data": "Two chains found."}\ndata: {"type": "complete"}'

    result = run_agent(project, "invoke-cloud", "Find chains", STUB_INVOKE_OUTPUT=output)

    assert result.returncode == 0, result.stdout + result.stderr
    assert 'data: {"type": "chunk", "data": "Two chains found."}' in result.stdout
    assert calls(project) == [invoke_call("Find chains")]


def test_fraud_user_id_sets_the_user(project: Path) -> None:
    result = run_agent(project, "invoke-cloud", "Find chains", FRAUD_USER_ID="analyst-1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project) == [invoke_call("Find chains", "analyst-1")]


def test_quotes_in_the_prompt_are_escaped(project: Path) -> None:
    prompt = 'Who sent "big" amounts\\?'

    result = run_agent(project, "invoke-cloud", prompt)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project) == [invoke_call(prompt)]


@pytest.mark.parametrize(
    "output",
    [
        'data: {"error": "NAMS GET -> 424: external_database_error", "error_type": "MemoryError"}',
        '{"error": "external_database_error"}',
        '  data:{"error": "external_database_error"}',
        # Color codes, as with FORCE_COLOR.
        '\x1b[1mdata: {"error": "external_database_error"}\x1b[0m',
    ],
)
def test_an_error_event_is_printed_and_exits_1(project: Path, output: str) -> None:
    result = run_agent(project, "invoke-cloud", "Find chains", STUB_INVOKE_OUTPUT=output)

    assert result.returncode == 1
    assert "external_database_error" in result.stdout
    assert "The agent returned an error event" in result.stdout


def test_the_word_error_inside_an_answer_is_not_an_error_event(project: Path) -> None:
    output = 'data: {"type": "chunk", "data": "{\\"error\\": 1} is a JSON example."}'

    result = run_agent(project, "invoke-cloud", "Find chains", STUB_INVOKE_OUTPUT=output)

    assert result.returncode == 0, result.stdout


def test_a_failed_cli_call_keeps_its_exit_code(project: Path) -> None:
    result = run_agent(
        project,
        "invoke-cloud",
        "Find chains",
        STUB_INVOKE_OUTPUT="Invocation failed",
        STUB_INVOKE_EXIT="3",
    )

    assert result.returncode == 3
    assert "Invocation failed" in result.stdout
    assert "The agent returned an error event" not in result.stdout


def test_no_prompt_sends_the_default_question(project: Path) -> None:
    result = run_agent(project, "invoke-cloud")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "highest risk scores" in calls(project)[0]


@pytest.mark.parametrize(
    "stub_env",
    [{}, {"STUB_INVOKE_EXIT": "3"}, {"STUB_INVOKE_OUTPUT": 'data: {"error": "x"}'}],
)
def test_the_response_file_is_removed_on_every_exit(
    project: Path, stub_env: dict[str, str]
) -> None:
    run_agent(project, "invoke-cloud", "Find chains", **stub_env)

    assert not list((project.parent / "tmp").iterdir())


def test_ctrl_c_during_invoke_removes_the_response_file(project: Path) -> None:
    result = run_agent(project, "invoke-cloud", "Find chains", STUB_INVOKE_SIGNAL="INT")

    assert result.returncode == -SIGINT
    assert not list((project.parent / "tmp").iterdir())


def test_verify_uses_agent_arn_when_set(project: Path) -> None:
    ready_to_deploy(project)

    result = run_agent(project, "verify", AGENT_ARN=RUNTIME_ARN)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project) == [
        f"python scripts/verify_agentcore_runtime.py --runtime-arn {RUNTIME_ARN}"
    ]


def test_verify_without_a_deployed_runtime_fails(project: Path) -> None:
    ready_to_deploy(project)

    result = run_agent(project, "verify")

    assert result.returncode == 1
    assert "could not find the deployed runtime ARN" in result.stdout
    assert not any(c.startswith("python") for c in calls(project))


def test_logs_reads_the_runtime_logs(project: Path) -> None:
    result = run_agent(project, "logs", "2h")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project) == [f"agentcore logs runtime --name {RUNTIME_NAME} --since 2h"]


def test_logs_defaults_to_30_minutes(project: Path) -> None:
    run_agent(project, "logs")

    assert calls(project) == [f"agentcore logs runtime --name {RUNTIME_NAME} --since 30m"]


@pytest.mark.parametrize("command", ["configure", "reset-config"])
def test_removed_commands_are_unknown(project: Path, command: str) -> None:
    result = run_agent(project, command)

    assert result.returncode == 1
    assert f"Unknown command: {command}" in result.stdout


# --- stop ---


def listen(argv: list[str]) -> tuple[subprocess.Popen[bytes], int]:
    """Start a process that listens on a free port, with argv as its command line."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    script = (
        "import socket, sys, time\n"
        "s = socket.socket()\n"
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        f"s.bind(('127.0.0.1', {port}))\n"
        "s.listen()\n"
        "print('ready', flush=True)\n"
        "time.sleep(60)\n"
    )
    process = subprocess.Popen([sys.executable, "-c", script, *argv], stdout=subprocess.PIPE)
    assert process.stdout is not None
    assert process.stdout.readline() == b"ready\n"
    return process, port


def test_stop_kills_only_a_fraud_server_on_the_port(project: Path) -> None:
    server, port = listen(["fraud-server"])
    try:
        result = run_agent(project, "stop", PORT=str(port))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "Stopped." in result.stdout
        assert server.wait(timeout=10) == -SIGTERM
    finally:
        server.kill()
        server.wait()


def test_stop_leaves_another_process_on_the_port(project: Path) -> None:
    other, port = listen(["something-else"])
    try:
        result = run_agent(project, "stop", PORT=str(port))

        assert result.returncode == 0, result.stdout + result.stderr
        assert f"No fraud-server process is listening on port {port}" in result.stdout
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()
