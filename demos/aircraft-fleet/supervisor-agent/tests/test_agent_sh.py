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
        if [ -n "$STUB_DEPLOY_SIGNAL" ]; then kill -s "$STUB_DEPLOY_SIGNAL" "$PPID"; fi
        exit "${STUB_DEPLOY_EXIT:-0}"
        ;;
    *) exit 99 ;;
esac
"""

STUB_AWS = r"""#!/bin/bash
echo "aws $*" >> "$STUB_LOG"
case "$1 $2" in
    "cloudformation describe-stacks")
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
    (root / "agentcore" / "aws-targets.json").write_text(
        json.dumps([{"name": "default", "region": "us-west-2"}])
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("agentcore", STUB_AGENTCORE), ("aws", STUB_AWS)):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return root


def run_destroy(project: Path, **stub_env: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{project.parent / 'bin'}:{os.environ['PATH']}",
        "HOME": os.environ["HOME"],
        "STUB_LOG": str(project.parent / "calls.log"),
        "STUB_STATUS_JSON": CLEAN_STATUS,
        **stub_env,
    }
    return subprocess.run(
        ["bash", str(project / "agent.sh"), "destroy", "--yes"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def calls(project: Path) -> list[str]:
    return (project.parent / "calls.log").read_text().splitlines()


def test_clean_destroy_checks_aws_by_name_and_succeeds(project: Path) -> None:
    result = run_destroy(project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Cleanup complete" in result.stdout
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
