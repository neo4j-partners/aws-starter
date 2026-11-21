"""Tests for ``agent.sh destroy`` and ``deploy`` with stub ``agentcore``, ``aws``, ``uv``,
``npm``, and ``mktemp``.

Each test copies agent.sh and the tracked agentcore.json into a temporary
folder. PATH holds only the stub folder, which also links the SYSTEM_TOOLS
the script runs, so no real agentcore, aws, or npm can run and nothing
reaches AWS. The stubs log every call
to calls.log and act on STUB_* environment variables. Each run gets its own
process group, so STUB_INTERRUPT can send SIGINT to it, as Ctrl+C does.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[1]
STACK = "AgentCore-AircraftFleet-default"
ACCOUNT = "111122223333"

# Every status call prints a banner on stderr, as the real CLI can when an
# update is available. It must not break the JSON on stdout.
STUB_AGENTCORE = r"""#!/bin/bash
echo "agentcore $*" >> "$STUB_LOG"
case "$1" in
    status)
        if [ "$STUB_INTERRUPT" = status ]; then kill -INT 0; sleep 5; fi
        echo "Update available" >&2
        printf '%s\n' "$STUB_STATUS_JSON"
        exit "${STUB_STATUS_EXIT:-0}"
        ;;
    remove)
        "$STUB_PYTHON" - "$4" <<'EOF'
import json
import sys
from pathlib import Path

spec = Path("agentcore/agentcore.json")
data = json.loads(spec.read_text())
data["runtimes"] = [r for r in data["runtimes"] if r["name"] != sys.argv[1]]
spec.write_text(json.dumps(data))
EOF
        ;;
    deploy) exit "${STUB_DEPLOY_EXIT:-0}" ;;
    *) exit 99 ;;
esac
"""

STUB_AWS = r"""#!/bin/bash
echo "aws $*" >> "$STUB_LOG"
if [ "$1 $2" = "sts get-caller-identity" ]; then
    if [ -n "$STUB_STS_ERROR" ]; then echo "$STUB_STS_ERROR" >&2; exit 254; fi
    if [ -n "$STUB_CALLER_ACCOUNT_AFTER_DEPLOY" ] && grep -q "^agentcore deploy" "$STUB_LOG"; then
        echo "$STUB_CALLER_ACCOUNT_AFTER_DEPLOY"
        exit 0
    fi
    echo "${STUB_CALLER_ACCOUNT:-111122223333}"
    exit 0
fi
if [ "$1 $2" != "cloudformation describe-stacks" ]; then exit 99; fi
if [ "$STUB_INTERRUPT" = describe-stacks ]; then kill -INT 0; sleep 5; fi
if [ -n "$STUB_AWS_ERROR" ]; then echo "$STUB_AWS_ERROR" >&2; exit 254; fi
if [ -n "$STUB_AWS_WARNING" ]; then echo "$STUB_AWS_WARNING" >&2; fi
if [ -n "$STUB_STACK_STATUS" ]; then echo "$STUB_STACK_STATUS"; exit 0; fi
echo "An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id x does not exist" >&2
exit 254
"""

# agent.sh runs its JSON helpers with `uv run --quiet python`. The stub runs
# them with the test's interpreter, so no project environment is built.
# STUB_UV_WARNING stands in for a uv warning on stderr.
STUB_UV = r"""#!/bin/bash
if [ "$1 $2 $3" != "run --quiet python" ]; then exit 99; fi
if [ -n "$STUB_UV_WARNING" ]; then echo "$STUB_UV_WARNING" >&2; fi
shift 3
exec "$STUB_PYTHON" "$@"
"""

# The system tools that agent.sh and the stubs run. Each test's PATH holds
# only these links and the stubs, so a real agentcore, aws, uv, or npm
# installed in /usr/bin cannot be found in place of a stub, or in place of
# a stub a test removes.
SYSTEM_TOOLS = (
    "bash",
    "cat",
    "cp",
    "dirname",
    "find",
    "grep",
    "head",
    "mkdir",
    "readlink",
    "rm",
    "sleep",
    "tail",
)

# A time well before any test runs, for files that must look older.
STALE_TIME = 1_000_000_000

# npm logs its arguments and working folder. `npm ci` and `npm install`
# write node_modules/.package-lock.json, as a complete real install does,
# unless STUB_NPM_EXIT makes them fail.
STUB_NPM = r"""#!/bin/bash
echo "npm $* in ${PWD##*/graphrag-agent/}" >> "$STUB_LOG"
if [ -n "$STUB_NPM_EXIT" ]; then echo "npm ERR! stub failure" >&2; exit "$STUB_NPM_EXIT"; fi
mkdir -p node_modules
echo "{}" > node_modules/.package-lock.json
"""

# macOS /usr/bin/mktemp ignores TMPDIR here, so without this stub a test of
# temp file cleanup would pass on code that leaks.
STUB_MKTEMP = r"""#!/bin/bash
exec /usr/bin/mktemp "$@" "$STUB_TMP/tmp.XXXXXX"
"""


def _status(resources: object = None, region: object = "us-east-1") -> str:
    body: dict[str, object] = {"region": region}
    body["resources"] = (
        [{"resourceType": "runtime", "name": "graphrag_agent", "deploymentState": "local-only"}]
        if resources is None
        else resources
    )
    return json.dumps(body)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "graphrag-agent"
    (root / "agentcore").mkdir(parents=True)
    shutil.copy2(AGENT_ROOT / "agent.sh", root / "agent.sh")
    shutil.copy2(AGENT_ROOT / "agentcore" / "agentcore.json", root / "agentcore" / "agentcore.json")
    # The first deploy writes this file. Git ignores it, so the test writes its own.
    targets = [{"name": "default", "account": ACCOUNT, "region": "us-east-1"}]
    (root / "agentcore" / "aws-targets.json").write_text(json.dumps(targets))
    # The checkout that deployed has a complete CDK install, made after the
    # committed package-lock.json was last changed.
    modules = root / "agentcore" / "cdk" / "node_modules"
    modules.mkdir(parents=True)
    lock = root / "agentcore" / "cdk" / "package-lock.json"
    lock.write_text("{}")
    (modules / ".package-lock.json").write_text("{}")
    os.utime(lock, (STALE_TIME, STALE_TIME))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "agentcore": STUB_AGENTCORE,
        "aws": STUB_AWS,
        "uv": STUB_UV,
        "mktemp": STUB_MKTEMP,
        "npm": STUB_NPM,
    }
    for name, body in stubs.items():
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    for name in SYSTEM_TOOLS:
        tool = shutil.which(name, path="/usr/bin:/bin")
        assert tool is not None, f"{name} is not in /usr/bin or /bin"
        (bin_dir / name).symlink_to(tool)
    (tmp_path / "tmp").mkdir()
    return root


def assert_tools_found(result: subprocess.CompletedProcess[str]) -> None:
    # A tool missing from SYSTEM_TOOLS can fail inside a branch that a test
    # does not check, so look for the shell's error on every run.
    assert "command not found" not in result.stderr, result.stderr


def run_destroy(
    project: Path, *args: str, stdin: str = "", **stub_env: str
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": str(project.parent / "bin"),
        "HOME": os.environ["HOME"],
        "STUB_LOG": str(project.parent / "calls.log"),
        "STUB_PYTHON": sys.executable,
        "STUB_TMP": str(project.parent / "tmp"),
        "STUB_STATUS_JSON": _status(),
        **stub_env,
    }
    result = subprocess.run(
        ["bash", str(project / "agent.sh"), "destroy", *(args or ("--yes",))],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
        start_new_session=True,
    )
    assert_tools_found(result)
    return result


def calls(project: Path) -> list[str]:
    log = project.parent / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def leftover_temp_files(project: Path) -> list[str]:
    return sorted(p.name for p in (project.parent / "tmp").iterdir())


@pytest.mark.parametrize("stack_status", ["", "DELETE_COMPLETE"])
def test_clean_destroy_checks_cloudformation_and_succeeds(project: Path, stack_status: str) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_destroy(project, STUB_STACK_STATUS=stack_status)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Cleanup complete. Stack {STACK} does not exist in us-east-1." in result.stdout
    logged = calls(project)
    assert "agentcore remove runtime --name graphrag_agent" in logged
    assert "agentcore deploy --target default --yes" in logged
    assert any(
        c.startswith(f"aws cloudformation describe-stacks --stack-name {STACK} --region us-east-1")
        for c in logged
    )
    assert spec.read_bytes() == tracked
    assert leftover_temp_files(project) == []


def test_a_stack_left_in_aws_fails_even_when_status_reads_clean(project: Path) -> None:
    result = run_destroy(project, STUB_STACK_STATUS="DELETE_FAILED")

    assert result.returncode == 1
    assert f"stack {STACK}: DELETE_FAILED" in result.stdout
    assert "Cleanup complete" not in result.stdout


def test_a_resource_status_still_reports_fails(project: Path) -> None:
    deployed = [
        {"resourceType": "runtime", "name": "graphrag_agent", "deploymentState": "deployed"}
    ]

    result = run_destroy(project, STUB_STATUS_JSON=_status(deployed))

    assert result.returncode == 1
    assert "runtime graphrag_agent: deployed" in result.stdout
    assert "Cleanup complete" not in result.stdout


@pytest.mark.parametrize(
    "status_json",
    [
        json.dumps({"region": "us-east-1"}),
        json.dumps({"region": "us-east-1", "resources": {"runtime": "graphrag_agent"}}),
        _status(region=None),
        "not json",
    ],
)
def test_unreadable_status_output_fails(project: Path, status_json: str) -> None:
    result = run_destroy(project, STUB_STATUS_JSON=status_json)

    assert result.returncode == 1
    assert "Could not read the agentcore status output" in result.stdout
    assert "Cleanup complete" not in result.stdout
    assert not any(c.startswith("aws cloudformation") for c in calls(project))


def test_failed_status_call_fails_and_removes_its_temp_file(project: Path) -> None:
    result = run_destroy(project, STUB_STATUS_EXIT="1", STUB_STATUS_JSON="")

    assert result.returncode == 1
    assert "Could not check what remains deployed" in result.stdout
    assert "Update available" in result.stdout
    assert leftover_temp_files(project) == []


@pytest.mark.parametrize("step", ["status", "describe-stacks"])
def test_ctrl_c_during_the_report_removes_the_temp_files(project: Path, step: str) -> None:
    result = run_destroy(project, STUB_INTERRUPT=step)

    assert result.returncode != 0
    assert "Cleanup complete" not in result.stdout
    assert leftover_temp_files(project) == []


def test_an_aws_error_other_than_not_found_fails(project: Path) -> None:
    result = run_destroy(
        project,
        STUB_AWS_ERROR="An error occurred (ExpiredToken) when calling the DescribeStacks operation",
    )

    assert result.returncode == 1
    assert f"Could not check stack {STACK} in us-east-1 with CloudFormation." in result.stdout
    assert "ExpiredToken" in result.stderr
    assert "Cleanup complete" not in result.stdout


def test_aws_stderr_on_success_is_not_read_as_the_stack_status(project: Path) -> None:
    result = run_destroy(
        project, STUB_STACK_STATUS="DELETE_COMPLETE", STUB_AWS_WARNING="Warning: CLI upgrade"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Cleanup complete. Stack {STACK} does not exist in us-east-1." in result.stdout
    assert "Warning: CLI upgrade" in result.stderr
    assert leftover_temp_files(project) == []


def test_uv_stderr_is_not_read_as_the_region(project: Path) -> None:
    result = run_destroy(project, STUB_UV_WARNING="warning: VIRTUAL_ENV does not match")

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Cleanup complete. Stack {STACK} does not exist in us-east-1." in result.stdout
    assert any(
        c.startswith(f"aws cloudformation describe-stacks --stack-name {STACK} --region us-east-1")
        for c in calls(project)
    )
    assert leftover_temp_files(project) == []


def test_credentials_for_another_account_fail_before_the_stack_check(project: Path) -> None:
    # The credentials change between the first check and the report.
    result = run_destroy(project, STUB_CALLER_ACCOUNT_AFTER_DEPLOY="999988887777")

    assert result.returncode == 1
    assert "agentcore deploy --target default --yes" in calls(project)
    assert f"account 999988887777, but target 'default' is in account {ACCOUNT}" in result.stdout
    assert "Cleanup complete" not in result.stdout
    assert not any(c.startswith("aws cloudformation") for c in calls(project))


@pytest.mark.parametrize("args", [("--yes",), ("",)])
def test_credentials_for_another_account_fail_before_any_agentcore_call(
    project: Path, args: tuple[str, ...]
) -> None:
    targets = [{"name": "default", "account": ACCOUNT, "region": "eu-west-1"}]
    (project / "agentcore" / "aws-targets.json").write_text(json.dumps(targets))

    result = run_destroy(project, *args, stdin="y\n", STUB_CALLER_ACCOUNT="999988887777")

    assert result.returncode == 1
    assert f"account 999988887777, but target 'default' is in account {ACCOUNT}" in result.stdout
    assert "Continue?" not in result.stdout
    logged = calls(project)
    assert not any(c.startswith("agentcore ") for c in logged)
    # Before deploy, the region comes from aws-targets.json.
    assert logged == [
        "aws sts get-caller-identity --query Account --output text --region eu-west-1"
    ]


def test_a_failed_identity_check_fails(project: Path) -> None:
    result = run_destroy(project, STUB_STS_ERROR="An error occurred (ExpiredToken)")

    assert result.returncode == 1
    assert "Could not check the active AWS account with STS." in result.stdout
    assert "ExpiredToken" in result.stderr
    assert "Cleanup complete" not in result.stdout


def _targets(account: object = ACCOUNT, region: object = "us-east-1") -> str:
    return json.dumps([{"name": "default", "account": account, "region": region}])


@pytest.mark.parametrize(
    "targets",
    [
        "[]",
        "not json",
        # An account must be a string of 12 digits.
        _targets(""),
        _targets("12345"),
        _targets("1111 2222 3333"),
        _targets(111122223333),
        # A region must be a non-empty string with no whitespace.
        _targets(region=""),
        _targets(region=None),
        _targets(region="us east-1"),
    ],
)
def test_an_unknown_target_account_fails(project: Path, targets: str) -> None:
    (project / "agentcore" / "aws-targets.json").write_text(targets)

    result = run_destroy(project)

    assert result.returncode == 1
    assert "Could not read the account for target 'default'" in result.stdout
    assert "Cleanup complete" not in result.stdout


@pytest.mark.parametrize("args", [("--yes",), ("",)])
def test_a_missing_targets_file_fails_before_any_call(project: Path, args: tuple[str, ...]) -> None:
    (project / "agentcore" / "aws-targets.json").unlink()

    result = run_destroy(project, *args, stdin="y\n")

    assert result.returncode == 1
    assert (
        "No deployment is recorded in this checkout: agentcore/aws-targets.json is missing. "
        "Run destroy from the checkout that deployed."
    ) in result.stdout
    assert "Could not read the account" not in result.stdout
    assert "Continue?" not in result.stdout
    assert calls(project) == []


def test_a_dangling_targets_link_has_its_own_message(project: Path) -> None:
    path = project / "agentcore" / "aws-targets.json"
    path.unlink()
    path.symlink_to(project.parent / "gone" / "aws-targets.json")

    result = run_destroy(project)

    assert result.returncode == 1
    assert "agentcore/aws-targets.json is a broken symlink to " in result.stdout
    assert "No deployment is recorded" not in result.stdout
    assert calls(project) == []


def test_missing_aws_cli_fails(project: Path) -> None:
    (project.parent / "bin" / "aws").unlink()

    result = run_destroy(project)

    assert result.returncode == 1
    assert "The aws CLI is not installed." in result.stderr
    assert "Cleanup complete" not in result.stdout


def test_failed_deploy_restores_the_spec_and_skips_the_report(project: Path) -> None:
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_destroy(project, STUB_DEPLOY_EXIT="3")

    assert result.returncode == 3
    assert spec.read_bytes() == tracked
    assert leftover_temp_files(project) == []
    assert not any(c.startswith("agentcore status") for c in calls(project))


@pytest.mark.parametrize("answer", ["", "n\n", "maybe\n"])
def test_destroy_without_yes_cancels_unless_confirmed(project: Path, answer: str) -> None:
    result = run_destroy(project, "", stdin=answer)

    assert result.returncode == 1
    assert "Cancelled. Nothing was changed." in result.stdout
    assert not any(c.startswith("agentcore ") for c in calls(project))


def test_destroy_runs_when_confirmed(project: Path) -> None:
    result = run_destroy(project, "", stdin="y\n")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "agentcore deploy --target default --yes" in calls(project)


def remove_cdk_install(project: Path) -> None:
    # Git ignores node_modules, so a fresh clone has no CDK install.
    shutil.rmtree(project / "agentcore" / "cdk" / "node_modules")


def run_deploy(project: Path, **stub_env: str) -> subprocess.CompletedProcess[str]:
    # deploy needs the shared ../.env and an installed .venv.
    (project.parent / ".env").write_text("NEO4J_URI=bolt://localhost:27687\n")
    (project / ".venv").mkdir(exist_ok=True)
    env = {
        "PATH": str(project.parent / "bin"),
        "HOME": os.environ["HOME"],
        "STUB_LOG": str(project.parent / "calls.log"),
        "STUB_PYTHON": sys.executable,
        "STUB_TMP": str(project.parent / "tmp"),
        **stub_env,
    }
    result = subprocess.run(
        ["bash", str(project / "agent.sh"), "deploy"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert_tools_found(result)
    return result


def test_deploy_installs_missing_cdk_dependencies_first(project: Path) -> None:
    remove_cdk_install(project)

    result = run_deploy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    assert logged == ["npm ci in agentcore/cdk", "agentcore deploy --target default"]
    assert (project / "agentcore" / "cdk" / "node_modules" / ".package-lock.json").is_file()


def test_deploy_skips_npm_when_cdk_dependencies_are_installed(project: Path) -> None:
    result = run_deploy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project) == ["agentcore deploy --target default"]


def test_a_partial_cdk_install_is_installed_again(project: Path) -> None:
    # A failed npm ci can leave node_modules without the lockfile that npm
    # writes only after a complete install.
    (project / "agentcore" / "cdk" / "node_modules" / ".package-lock.json").unlink()

    result = run_deploy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project) == ["npm ci in agentcore/cdk", "agentcore deploy --target default"]


def test_a_newer_package_lock_is_installed_again(project: Path) -> None:
    # A git pull that changes package-lock.json leaves the old install in
    # place. The lock is then newer than npm's marker from that install.
    marker = project / "agentcore" / "cdk" / "node_modules" / ".package-lock.json"
    os.utime(marker, (STALE_TIME, STALE_TIME))
    os.utime(project / "agentcore" / "cdk" / "package-lock.json")

    result = run_deploy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project) == ["npm ci in agentcore/cdk", "agentcore deploy --target default"]


def test_a_failed_cdk_install_stops_before_deploy(project: Path) -> None:
    remove_cdk_install(project)

    result = run_deploy(project, STUB_NPM_EXIT="1")

    assert result.returncode == 1
    assert "(cd agentcore/cdk && npm ci)" in result.stdout
    assert calls(project) == ["npm ci in agentcore/cdk"]


def test_a_cdk_project_without_a_lockfile_uses_npm_install(project: Path) -> None:
    # npm ci needs package-lock.json. A project made by
    # `agentcore create --skip-install` has none.
    remove_cdk_install(project)
    (project / "agentcore" / "cdk" / "package-lock.json").unlink()

    result = run_deploy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(project) == ["npm install in agentcore/cdk", "agentcore deploy --target default"]


def test_a_failed_install_without_a_lockfile_names_npm_install(project: Path) -> None:
    remove_cdk_install(project)
    (project / "agentcore" / "cdk" / "package-lock.json").unlink()

    result = run_deploy(project, STUB_NPM_EXIT="1")

    assert result.returncode == 1
    assert "(cd agentcore/cdk && npm install)" in result.stdout
    assert "npm ci" not in result.stdout
    assert calls(project) == ["npm install in agentcore/cdk"]


def test_deploy_without_npm_names_the_install_step(project: Path) -> None:
    remove_cdk_install(project)
    (project.parent / "bin" / "npm").unlink()
    assert shutil.which("npm", path=str(project.parent / "bin")) is None

    result = run_deploy(project)

    assert result.returncode == 1
    assert "npm is not installed" in result.stdout
    assert "(cd agentcore/cdk && npm ci)" in result.stdout
    assert calls(project) == []


def test_destroy_installs_missing_cdk_dependencies_before_removing(project: Path) -> None:
    remove_cdk_install(project)

    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(project)
    assert "npm ci in agentcore/cdk" in logged
    assert logged.index("npm ci in agentcore/cdk") < logged.index(
        "agentcore remove runtime --name graphrag_agent"
    )


def test_a_failed_cdk_install_stops_destroy_before_any_change(project: Path) -> None:
    remove_cdk_install(project)
    spec = project / "agentcore" / "agentcore.json"
    tracked = spec.read_bytes()

    result = run_destroy(project, STUB_NPM_EXIT="1")

    assert result.returncode == 1
    assert "(cd agentcore/cdk && npm ci)" in result.stdout
    assert not any(c.startswith("agentcore remove") for c in calls(project))
    assert not any(c.startswith("agentcore deploy") for c in calls(project))
    assert spec.read_bytes() == tracked
