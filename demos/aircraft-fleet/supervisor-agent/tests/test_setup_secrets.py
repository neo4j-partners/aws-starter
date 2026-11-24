"""Tests for ``fleet_supervisor.setup_secrets``. Secrets Manager is stubbed with botocore's Stubber."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber

from fleet_supervisor import setup_secrets
from fleet_supervisor.setup_secrets import FLEET_SECRET, MEMORY_SECRET

REGION = "us-east-1"
FLEET_ARN = f"arn:aws:secretsmanager:{REGION}:123456789012:secret:fleet/neo4j-reader-AbC123"
MEMORY_ARN = f"arn:aws:secretsmanager:{REGION}:123456789012:secret:fleet/memory-neo4j-XyZ789"

READER_USER = "reader-user-7f3a"
READER_PASSWORD = "reader-pw-9c1e"
MEMORY_USER = "memory-user-2b8d"
MEMORY_PASSWORD = "memory-pw-4e6f"
ADMIN_PASSWORD = "admin-pw-5a0c"

ENV_TEXT = f"""\
NEO4J_URI=neo4j+s://fleet1234.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD={ADMIN_PASSWORD}
NEO4J_READER_USERNAME={READER_USER}
NEO4J_READER_PASSWORD={READER_PASSWORD}
MEM_NEO4J_URI=neo4j+s://memory12.databases.neo4j.io
MEM_NEO4J_USERNAME={MEMORY_USER}
MEM_NEO4J_PASSWORD={MEMORY_PASSWORD}
AWS_REGION={REGION}
"""

FLEET_VALUE = json.dumps({"username": READER_USER, "password": READER_PASSWORD})
MEMORY_VALUE = json.dumps({"username": MEMORY_USER, "password": MEMORY_PASSWORD})

# Every username and password above. None may appear in the output.
VALUES = (READER_USER, READER_PASSWORD, MEMORY_USER, MEMORY_PASSWORD, ADMIN_PASSWORD)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in setup_secrets.SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("FLEET_ENV_FILE", raising=False)


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / ".env"
    path.write_text(ENV_TEXT)
    return path


@pytest.fixture
def stubber(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stubber]:
    """A stubbed Secrets Manager client that ``main`` gets from ``boto3.client``."""
    client = boto3.client(
        "secretsmanager",
        region_name=REGION,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    regions: list[str] = []

    def fake_client(service: str, region_name: str):
        assert service == "secretsmanager"
        regions.append(region_name)
        return client

    monkeypatch.setattr(setup_secrets.boto3, "client", fake_client)
    with Stubber(client) as stub:
        stub.regions = regions
        yield stub
        stub.assert_no_pending_responses()


def _not_found(stub: Stubber, name: str) -> None:
    stub.add_client_error(
        "describe_secret",
        service_error_code="ResourceNotFoundException",
        http_status_code=400,
        expected_params={"SecretId": name},
    )


def _exists(stub: Stubber, name: str, arn: str, current: str) -> None:
    stub.add_response("describe_secret", {"ARN": arn, "Name": name}, {"SecretId": name})
    stub.add_response(
        "get_secret_value", {"ARN": arn, "Name": name, "SecretString": current}, {"SecretId": arn}
    )


def _created(stub: Stubber, spec: setup_secrets.SecretSpec, arn: str, value: str) -> None:
    stub.add_response(
        "create_secret",
        {"ARN": arn, "Name": spec.name},
        {
            "Name": spec.name,
            "Description": spec.description,
            "SecretString": value,
        },
    )


def _updated(stub: Stubber, arn: str, value: str) -> None:
    stub.add_response(
        "put_secret_value",
        {"ARN": arn},
        {"SecretId": arn, "SecretString": value},
    )


def _assert_no_values(output: str) -> None:
    leaked = [value for value in VALUES if value in output]
    assert leaked == []


def test_creates_missing_secrets_and_prints_arn_lines(
    stubber: Stubber, env_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _not_found(stubber, FLEET_SECRET.name)
    _not_found(stubber, MEMORY_SECRET.name)
    _created(stubber, FLEET_SECRET, FLEET_ARN, FLEET_VALUE)
    _created(stubber, MEMORY_SECRET, MEMORY_ARN, MEMORY_VALUE)

    assert setup_secrets.main(["--env-file", str(env_file)]) == 0

    out, err = capsys.readouterr()
    assert (
        "fleet/neo4j-reader: created (from NEO4J_READER_USERNAME and NEO4J_READER_PASSWORD)" in out
    )
    assert "fleet/memory-neo4j: created (from MEM_NEO4J_USERNAME and MEM_NEO4J_PASSWORD)" in out
    assert out.splitlines()[-2:] == [
        f"NEO4J_PASSWORD_SECRET_ARN={FLEET_ARN}",
        f"MEM_NEO4J_PASSWORD_SECRET_ARN={MEMORY_ARN}",
    ]
    assert stubber.regions == [REGION]
    _assert_no_values(out + err)


def test_puts_a_new_version_when_the_value_changed(
    stubber: Stubber, env_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = json.dumps({"username": READER_USER, "password": "old-pw-1d2e"})
    _exists(stubber, FLEET_SECRET.name, FLEET_ARN, old)
    _exists(stubber, MEMORY_SECRET.name, MEMORY_ARN, MEMORY_VALUE)
    _updated(stubber, FLEET_ARN, FLEET_VALUE)

    assert setup_secrets.main(["--env-file", str(env_file)]) == 0

    out, err = capsys.readouterr()
    assert "fleet/neo4j-reader: updated with a new version" in out
    assert "fleet/memory-neo4j: unchanged" in out
    assert f"NEO4J_PASSWORD_SECRET_ARN={FLEET_ARN}" in out
    _assert_no_values(out + err + "old-pw-1d2e")


def test_leaves_an_unchanged_secret_alone_whatever_its_key_order(
    stubber: Stubber, env_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reordered = json.dumps({"password": READER_PASSWORD, "username": READER_USER})
    _exists(stubber, FLEET_SECRET.name, FLEET_ARN, reordered)
    _exists(stubber, MEMORY_SECRET.name, MEMORY_ARN, MEMORY_VALUE)

    assert setup_secrets.main(["--env-file", str(env_file)]) == 0

    out, err = capsys.readouterr()
    assert "fleet/neo4j-reader: unchanged" in out
    assert "fleet/memory-neo4j: unchanged" in out
    assert f"MEM_NEO4J_PASSWORD_SECRET_ARN={MEMORY_ARN}" in out
    _assert_no_values(out + err)


def test_a_secret_string_that_is_not_json_gets_a_new_version(
    stubber: Stubber, env_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _exists(stubber, FLEET_SECRET.name, FLEET_ARN, "plain-text")
    _exists(stubber, MEMORY_SECRET.name, MEMORY_ARN, MEMORY_VALUE)
    _updated(stubber, FLEET_ARN, FLEET_VALUE)

    assert setup_secrets.main(["--env-file", str(env_file)]) == 0
    assert "fleet/neo4j-reader: updated with a new version" in capsys.readouterr().out


def test_dry_run_reads_but_writes_nothing(
    stubber: Stubber, env_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _not_found(stubber, FLEET_SECRET.name)
    _exists(stubber, MEMORY_SECRET.name, MEMORY_ARN, json.dumps({"username": "x", "password": "y"}))

    # The Stubber fails on any call that was not queued, so no create or put ran.
    assert setup_secrets.main(["--env-file", str(env_file), "--dry-run"]) == 0

    out, err = capsys.readouterr()
    assert "Region: us-east-1 (dry run)" in out
    assert "fleet/neo4j-reader: would create" in out
    assert "fleet/memory-neo4j: would update" in out
    assert "After a run without --dry-run, set these lines" in out
    assert "# NEO4J_PASSWORD_SECRET_ARN= is known once fleet/neo4j-reader exists" in out
    assert f"MEM_NEO4J_PASSWORD_SECRET_ARN={MEMORY_ARN}" in out
    _assert_no_values(out + err)


def test_missing_settings_are_all_named_and_nothing_is_called(
    stubber: Stubber, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".env"
    path.write_text(f"NEO4J_PASSWORD={ADMIN_PASSWORD}\nNEO4J_READER_PASSWORD=\n")

    assert setup_secrets.main(["--env-file", str(path)]) == 1

    out, err = capsys.readouterr()
    assert "Set NEO4J_READER_USERNAME, NEO4J_READER_PASSWORD, MEM_NEO4J_PASSWORD" in err
    _assert_no_values(out + err)


def test_memory_username_defaults_to_neo4j(
    stubber: Stubber, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".env"
    path.write_text(ENV_TEXT.replace(f"MEM_NEO4J_USERNAME={MEMORY_USER}\n", ""))
    _exists(stubber, FLEET_SECRET.name, FLEET_ARN, FLEET_VALUE)
    _not_found(stubber, MEMORY_SECRET.name)
    default_value = json.dumps({"username": "neo4j", "password": MEMORY_PASSWORD})
    _created(stubber, MEMORY_SECRET, MEMORY_ARN, default_value)

    assert setup_secrets.main(["--env-file", str(path)]) == 0
    out = capsys.readouterr().out
    assert "fleet/memory-neo4j: created (from the default username and MEM_NEO4J_PASSWORD)" in out


def test_shell_value_wins_and_region_comes_from_settings(
    stubber: Stubber, env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEO4J_READER_PASSWORD", "shell-pw-8b7a")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    shell_value = json.dumps({"username": READER_USER, "password": "shell-pw-8b7a"})
    _exists(stubber, FLEET_SECRET.name, FLEET_ARN, shell_value)
    _exists(stubber, MEMORY_SECRET.name, MEMORY_ARN, MEMORY_VALUE)

    assert setup_secrets.main(["--env-file", str(env_file), "--dry-run"]) == 0
    assert stubber.regions == ["us-west-2"]


def test_region_defaults_to_us_east_1(stubber: Stubber, tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(ENV_TEXT.replace(f"AWS_REGION={REGION}\n", ""))
    _exists(stubber, FLEET_SECRET.name, FLEET_ARN, FLEET_VALUE)
    _exists(stubber, MEMORY_SECRET.name, MEMORY_ARN, MEMORY_VALUE)

    assert setup_secrets.main(["--env-file", str(path), "--dry-run"]) == 0
    assert stubber.regions == ["us-east-1"]


def test_fleet_env_file_names_the_default_file(
    monkeypatch: pytest.MonkeyPatch, env_file: Path
) -> None:
    monkeypatch.setenv("FLEET_ENV_FILE", str(env_file))
    assert setup_secrets.default_env_file() == env_file


def test_default_env_file_is_the_shared_aircraft_fleet_env() -> None:
    expected = Path(setup_secrets.__file__).resolve().parents[2] / ".env"
    assert setup_secrets.default_env_file() == expected
    assert expected.parent.name == "aircraft-fleet"


def test_missing_env_file_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert setup_secrets.main(["--env-file", str(tmp_path / "absent.env")]) == 1
    assert "absent.env not found" in capsys.readouterr().err


def test_secret_scheduled_for_deletion_stops_before_any_write(
    stubber: Stubber, env_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stubber.add_response(
        "describe_secret",
        {"ARN": FLEET_ARN, "Name": FLEET_SECRET.name, "DeletedDate": "2026-11-20T00:00:00Z"},
        {"SecretId": FLEET_SECRET.name},
    )

    assert setup_secrets.main(["--env-file", str(env_file)]) == 1
    assert "fleet/neo4j-reader is scheduled for deletion" in capsys.readouterr().err


def test_aws_error_prints_only_the_code(
    stubber: Stubber, env_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stubber.add_client_error(
        "describe_secret",
        service_error_code="AccessDeniedException",
        service_message=f"User arn:aws:sts::123456789012:assumed-role/x is not authorized {FLEET_ARN}",
        http_status_code=400,
        expected_params={"SecretId": FLEET_SECRET.name},
    )

    assert setup_secrets.main(["--env-file", str(env_file)]) == 1

    out, err = capsys.readouterr()
    assert "ERROR: Secrets Manager call failed (AccessDeniedException)." in err
    assert "123456789012" not in out + err
    _assert_no_values(out + err)
