"""``fleet-client``: which supervisor each command uses, and the .env it reads."""

import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from fleet_supervisor.client import cli, fleet_client, fleet_env
from fleet_supervisor.client.fleet_env import NO_AGENT_ARN
from fleet_supervisor.client.transport import InvokeResult

ARN = "arn:aws:bedrock-agentcore:us-east-1:0:runtime/fleet"

EnvWriter = Callable[[str], Path]


@pytest.fixture
def invoked(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Record each supervisor call ``ask`` makes, in place of the transport."""
    calls: list[tuple[str, ...]] = []

    def fake_local(prompt: str, _session_id: str | None, _on_event: object) -> InvokeResult:
        calls.append(("local", prompt))
        return InvokeResult(text="ok")

    def fake_deployed(
        prompt: str, agent_arn: str, region: str, _session_id: str | None, _on_event: object
    ) -> InvokeResult:
        calls.append(("cloud", prompt, agent_arn, region))
        return InvokeResult(text="ok")

    monkeypatch.setattr(cli, "invoke_local", fake_local)
    monkeypatch.setattr(cli, "invoke_deployed", fake_deployed)
    return calls


@pytest.fixture
def exec_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record the process ``ui`` would replace itself with, in place of ``os.execv``."""
    calls: list[list[str]] = []
    monkeypatch.setattr(fleet_client.os, "execv", lambda _path, argv: calls.append(argv))
    return calls


def test_ask_is_local_even_when_the_env_sets_an_agent_arn(
    fleet_env_file: EnvWriter, invoked: list[tuple[str, ...]]
) -> None:
    fleet_env_file(f"AGENT_ARN={ARN}\n")

    fleet_client.main(["ask", "Which", "components", "fail?"])

    assert invoked == [("local", "Which components fail?")]


def test_ask_cloud_reads_the_arn_and_region_from_the_env_file(
    fleet_env_file: EnvWriter, invoked: list[tuple[str, ...]]
) -> None:
    fleet_env_file(f"AGENT_ARN={ARN}\nAWS_REGION=us-west-2\n")

    fleet_client.main(["ask", "--cloud", "hi"])

    assert invoked == [("cloud", "hi", ARN, "us-west-2")]


def test_ask_cloud_without_an_agent_arn_says_to_deploy(
    fleet_env_file: EnvWriter, invoked: list[tuple[str, ...]]
) -> None:
    fleet_env_file("AWS_REGION=us-east-1\n")

    with pytest.raises(SystemExit) as exit_info:
        fleet_client.main(["ask", "--cloud", "hi"])

    assert exit_info.value.code == NO_AGENT_ARN
    assert "./agent.sh deploy" in NO_AGENT_ARN
    assert invoked == []


def test_the_old_cli_remote_flag_reads_the_arn_from_the_env_file(
    fleet_env_file: EnvWriter, invoked: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    fleet_env_file(f"AGENT_ARN={ARN}\n")
    monkeypatch.setattr(sys, "argv", ["fleet-supervisor-cli", "--remote", "hi"])
    # The CLI loads the .env when it is imported, as its console script does.
    fleet_env.load_fleet_env()

    cli.main()

    assert invoked == [("cloud", "hi", ARN, "us-east-1")]


def test_ui_is_local_even_when_the_env_sets_cloud_mode(
    fleet_env_file: EnvWriter, exec_calls: list[list[str]]
) -> None:
    fleet_env_file(f"AGENT_ARN={ARN}\nFLEET_SUPERVISOR_MODE=cloud\n")

    fleet_client.main(["ui"])

    assert os.environ["FLEET_SUPERVISOR_MODE"] == "local"
    assert exec_calls == [[sys.executable, str(fleet_client.UI_SERVER)]]


def test_ui_cloud_sets_cloud_mode(fleet_env_file: EnvWriter, exec_calls: list[list[str]]) -> None:
    fleet_env_file(f"AGENT_ARN={ARN}\n")

    fleet_client.main(["ui", "--cloud"])

    assert os.environ["FLEET_SUPERVISOR_MODE"] == "cloud"
    assert len(exec_calls) == 1


def test_ui_cloud_without_an_agent_arn_stops_before_the_server_starts(
    fleet_env_file: EnvWriter, exec_calls: list[list[str]]
) -> None:
    fleet_env_file("")

    with pytest.raises(SystemExit) as exit_info:
        fleet_client.main(["ui", "--cloud"])

    assert exit_info.value.code == NO_AGENT_ARN
    assert exec_calls == []


def test_a_shell_variable_wins_over_the_env_file(
    fleet_env_file: EnvWriter, invoked: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    fleet_env_file(f"AGENT_ARN={ARN}\nAWS_REGION=us-west-2\n")
    monkeypatch.setenv("AWS_REGION", "eu-central-1")

    fleet_client.main(["ask", "--cloud", "hi"])

    assert invoked == [("cloud", "hi", ARN, "eu-central-1")]


def test_the_default_env_file_is_the_shared_aircraft_fleet_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLEET_ENV_FILE")
    aircraft_fleet = Path(__file__).resolve().parents[2]
    ui_server = fleet_client.UI_SERVER

    assert fleet_env.env_file() == aircraft_fleet / ".env"
    assert ui_server == aircraft_fleet / "ui" / "server.py"
    assert ui_server.is_file()
