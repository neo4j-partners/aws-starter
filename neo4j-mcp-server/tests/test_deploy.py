"""Tests for deploy.py helpers. AWS calls go to fakes, so nothing reaches AWS."""

import subprocess
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

import deploy


def test_warns_when_the_runtime_holds_a_plaintext_password(
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment = {"NEO4J_USERNAME": "reader", "NEO4J_PASSWORD": "s3cret"}

    assert deploy.warn_if_plaintext_password(environment) is True

    err = capsys.readouterr().err
    assert "WARN" in err
    assert "./deploy.py" in err
    assert "s3cret" not in err


def test_no_warning_when_the_runtime_uses_the_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment = {"NEO4J_PASSWORD_SECRET_ARN": "arn:aws:secretsmanager:x"}

    assert deploy.warn_if_plaintext_password(environment) is False
    assert capsys.readouterr().err == ""


# --- cleanup: the runtime's CloudWatch log groups ----------------------------

RUNTIME_ID = "neo4j_mcp_server_fleet-AbCdE12345"
LOG_PREFIX = f"/aws/bedrock-agentcore/runtimes/{RUNTIME_ID}-"
LOG_GROUP = f"{LOG_PREFIX}DEFAULT"
# Another runtime's ID starts with the same characters, but its group does not
# start with the prefix, which ends with the dash after the ID.
OTHER_GROUP = "/aws/bedrock-agentcore/runtimes/neo4j_mcp_server_fleet-AbCdE123456-DEFAULT"


def client_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class FakePaginator:
    def __init__(self, logs: "FakeLogs") -> None:
        self.logs = logs

    def paginate(self, logGroupNamePrefix: str) -> Iterator[dict[str, list[dict[str, str]]]]:
        self.logs.prefixes.append(logGroupNamePrefix)
        if self.logs.list_error is not None:
            raise self.logs.list_error
        for name in self.logs.groups:
            if name.startswith(logGroupNamePrefix):
                yield {"logGroups": [{"logGroupName": name}]}


class FakeLogs:
    def __init__(self, groups: list[str], failures: dict[str, str] | None = None) -> None:
        self.groups = groups
        self.failures = failures or {}
        self.list_error: ClientError | None = None
        self.prefixes: list[str] = []
        self.deleted: list[str] = []

    def get_paginator(self, operation: str) -> FakePaginator:
        assert operation == "describe_log_groups"
        return FakePaginator(self)

    def delete_log_group(self, logGroupName: str) -> None:
        if logGroupName in self.failures:
            raise client_error(self.failures[logGroupName], "DeleteLogGroup")
        self.deleted.append(logGroupName)


class FakeSecrets:
    def __init__(self) -> None:
        self.checked: list[str] = []

    def describe_secret(self, SecretId: str) -> None:
        self.checked.append(SecretId)
        raise client_error("ResourceNotFoundException", "DescribeSecret")


class FakeControl:
    """By default the runtime is gone: get_agent_runtime raises ResourceNotFoundException."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.checked: list[str] = []
        self.get_error: Exception | None = client_error(
            "ResourceNotFoundException", "GetAgentRuntime"
        )

    def delete_agent_runtime(self, agentRuntimeId: str) -> None:
        self.deleted.append(agentRuntimeId)

    def get_agent_runtime(self, agentRuntimeId: str) -> dict[str, str]:
        self.checked.append(agentRuntimeId)
        if self.get_error is not None:
            raise self.get_error
        return {"agentRuntimeId": agentRuntimeId, "status": "DELETING"}


class FakeAws:
    def __init__(self, logs: FakeLogs) -> None:
        self.region = "us-east-1"
        self.control = FakeControl()
        self.clients = {
            "logs": logs,
            "secretsmanager": FakeSecrets(),
            "bedrock-agentcore-control": self.control,
        }

    def client(self, service: str) -> object:
        return self.clients[service]


CFG = SimpleNamespace(stack_name="neo4j-mcp-server-fleet", ecr_repo_name="neo4j-mcp-server")


@pytest.fixture
def cleanup_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Stub every AWS step of cmd_cleanup except the log group step.

    Tests change the returned settings: the answer to the first question,
    whether the stack exists, the runtime ID, and whether cdk destroy works.
    """
    settings: dict[str, object] = {
        "reply": "y",
        "stack_exists": True,
        "runtime_id": RUNTIME_ID,
        "cdk_exit": 0,
    }
    monkeypatch.setattr("builtins.input", lambda _prompt: settings["reply"])
    monkeypatch.setattr(deploy, "stack_exists", lambda _aws, _cfg: settings["stack_exists"])
    monkeypatch.setattr(deploy, "_delete_agent_runtime", lambda _aws, _cfg: settings["runtime_id"])
    monkeypatch.setattr(deploy, "setup_cdk_deps", lambda: None)
    monkeypatch.setattr(deploy, "_cdk_env", lambda _cfg: {})
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], settings["cdk_exit"]),
    )
    monkeypatch.setattr(deploy, "_retry_stack_delete", lambda _aws, _cfg: False)
    monkeypatch.setattr(deploy, "ecr_repo_exists", lambda _aws, _cfg: False)
    return settings


@pytest.mark.usefixtures("cleanup_env")
def test_cleanup_removes_only_the_runtime_log_groups(capsys: pytest.CaptureFixture[str]) -> None:
    logs = FakeLogs([LOG_GROUP, OTHER_GROUP])

    aws = FakeAws(logs)

    deploy.cmd_cleanup(aws, CFG)

    assert aws.control.checked == [RUNTIME_ID]
    assert logs.prefixes == [LOG_PREFIX]
    assert logs.deleted == [LOG_GROUP]
    err = capsys.readouterr().err
    assert f"Removed: log group {LOG_GROUP}" in err
    assert "Cleanup complete" in err


@pytest.mark.usefixtures("cleanup_env")
def test_cleanup_reports_no_log_groups_as_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    logs = FakeLogs([OTHER_GROUP])

    deploy.cmd_cleanup(FakeAws(logs), CFG)

    assert logs.deleted == []
    err = capsys.readouterr().err
    assert f"Not found: log groups under {LOG_PREFIX} in us-east-1" in err
    assert "Cleanup complete" in err


@pytest.mark.usefixtures("cleanup_env")
def test_a_log_group_gone_before_its_delete_is_not_an_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logs = FakeLogs([LOG_GROUP], failures={LOG_GROUP: "ResourceNotFoundException"})

    deploy.cmd_cleanup(FakeAws(logs), CFG)

    err = capsys.readouterr().err
    assert f"Not found: log group {LOG_GROUP}" in err
    assert "Cleanup complete" in err


@pytest.mark.usefixtures("cleanup_env")
def test_a_failed_log_group_delete_finishes_cleanup_then_fails_and_names_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    second = f"{LOG_PREFIX}other"
    logs = FakeLogs([LOG_GROUP, second], failures={LOG_GROUP: "AccessDeniedException"})
    aws = FakeAws(logs)

    with pytest.raises(deploy.DeployError, match="log group delete failed"):
        deploy.cmd_cleanup(aws, CFG)

    # The other group and the later secret step still ran.
    assert logs.deleted == [second]
    assert aws.clients["secretsmanager"].checked == ["neo4j-mcp-server-fleet/neo4j-password"]
    err = capsys.readouterr().err
    assert f"Could not delete these log groups in us-east-1:\nERROR   {LOG_GROUP}\n" in err
    assert "Cleanup complete" not in err


@pytest.mark.usefixtures("cleanup_env")
def test_a_failed_log_group_listing_fails_cleanup(capsys: pytest.CaptureFixture[str]) -> None:
    logs = FakeLogs([LOG_GROUP])
    logs.list_error = client_error("ExpiredTokenException", "DescribeLogGroups")

    with pytest.raises(deploy.DeployError, match="log group delete failed"):
        deploy.cmd_cleanup(FakeAws(logs), CFG)

    err = capsys.readouterr().err
    assert f"Could not list the log groups under {LOG_PREFIX}" in err
    assert f"ERROR   {LOG_PREFIX}*" in err


@pytest.mark.parametrize(
    ("get_error", "message"),
    [
        (None, f"Runtime {RUNTIME_ID} still exists, so its log groups stay in place"),
        (
            client_error("AccessDeniedException", "GetAgentRuntime"),
            f"Could not check whether runtime {RUNTIME_ID} is gone",
        ),
        (
            EndpointConnectionError(endpoint_url="https://example.invalid"),
            f"Could not check whether runtime {RUNTIME_ID} is gone",
        ),
    ],
)
@pytest.mark.usefixtures("cleanup_env")
def test_the_log_groups_stay_unless_the_runtime_is_confirmed_gone(
    capsys: pytest.CaptureFixture[str], get_error: Exception | None, message: str
) -> None:
    logs = FakeLogs([LOG_GROUP])
    aws = FakeAws(logs)
    aws.control.get_error = get_error

    with pytest.raises(deploy.DeployError, match="log group delete failed"):
        deploy.cmd_cleanup(aws, CFG)

    assert aws.control.checked == [RUNTIME_ID]
    assert logs.prefixes == []
    assert logs.deleted == []
    # The secret step after it still ran.
    assert aws.clients["secretsmanager"].checked == ["neo4j-mcp-server-fleet/neo4j-password"]
    err = capsys.readouterr().err
    assert message in err
    assert f"ERROR   {LOG_PREFIX}*" in err
    assert "Cleanup complete" not in err


@pytest.mark.parametrize("runtime_id", ["", "neo4j_mcp_server_fleet", f"{RUNTIME_ID}*"])
def test_cleanup_without_a_valid_runtime_id_skips_the_log_groups(
    cleanup_env: dict[str, object], runtime_id: str
) -> None:
    cleanup_env["runtime_id"] = runtime_id
    logs = FakeLogs([LOG_GROUP])

    deploy.cmd_cleanup(FakeAws(logs), CFG)

    assert logs.prefixes == []
    assert logs.deleted == []


def test_cleanup_keeps_the_log_groups_when_the_stack_delete_fails(
    cleanup_env: dict[str, object],
) -> None:
    cleanup_env["cdk_exit"] = 1
    logs = FakeLogs([LOG_GROUP])

    with pytest.raises(deploy.DeployError, match="stack delete failed"):
        deploy.cmd_cleanup(FakeAws(logs), CFG)

    assert logs.prefixes == []


@pytest.mark.parametrize(("setting", "value"), [("reply", "n"), ("stack_exists", False)])
def test_cleanup_keeps_the_log_groups_when_cancelled_or_the_stack_is_absent(
    cleanup_env: dict[str, object], setting: str, value: object
) -> None:
    cleanup_env[setting] = value
    logs = FakeLogs([LOG_GROUP])

    deploy.cmd_cleanup(FakeAws(logs), CFG)

    assert logs.prefixes == []


def test_delete_agent_runtime_returns_the_id_it_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    control = FakeControl()
    aws = SimpleNamespace(client=lambda _service: control)
    monkeypatch.setattr(deploy, "_find_runtime_id", lambda _aws, _cfg: RUNTIME_ID)

    assert deploy._delete_agent_runtime(aws, CFG) == RUNTIME_ID
    assert control.deleted == [RUNTIME_ID]
