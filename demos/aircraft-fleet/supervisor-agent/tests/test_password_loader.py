"""Tests for the Secrets Manager password loader in ``fleet_supervisor.core.secrets``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from fleet_supervisor.core import secrets
from fleet_supervisor.core.config import ConfigError
from fleet_supervisor.core.secrets import password_from

ARN = "arn:aws:secretsmanager:us-west-2:123456789012:secret:aircraft-fleet/neo4j-AbCdEf"
ARN_VAR = "TEST_PASSWORD_SECRET_ARN"
PASSWORD_VAR = "TEST_PASSWORD"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ARN_VAR, raising=False)
    monkeypatch.delenv(PASSWORD_VAR, raising=False)
    secrets._read_secret.cache_clear()


def _fake_secrets_manager(
    monkeypatch: pytest.MonkeyPatch,
    secret_string: str | None = '{"username": "neo4j", "password": "s3cret"}',
    error: Exception | None = None,
) -> list[dict]:
    """Patch ``boto3.client`` and record every client and call."""
    calls: list[dict] = []

    def get_secret_value(SecretId: str) -> dict:
        calls.append({"secret_id": SecretId})
        if error is not None:
            raise error
        return {} if secret_string is None else {"SecretString": secret_string}

    def fake_client(service: str, region_name: str) -> SimpleNamespace:
        calls.append({"service": service, "region": region_name})
        return SimpleNamespace(get_secret_value=get_secret_value)

    monkeypatch.setattr(secrets.boto3, "client", fake_client)
    return calls


def test_falls_back_to_password_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PASSWORD_VAR, "local-pw")
    assert password_from(ARN_VAR, PASSWORD_VAR) == "local-pw"


def test_neither_set_names_both_vars() -> None:
    with pytest.raises(ConfigError, match=f"{ARN_VAR}.*{PASSWORD_VAR}"):
        password_from(ARN_VAR, PASSWORD_VAR)


def test_secret_arn_wins_and_uses_arn_region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ARN_VAR, ARN)
    monkeypatch.setenv(PASSWORD_VAR, "local-pw")
    calls = _fake_secrets_manager(monkeypatch)
    assert password_from(ARN_VAR, PASSWORD_VAR) == "s3cret"
    assert calls == [
        {"service": "secretsmanager", "region": "us-west-2"},
        {"secret_id": ARN},
    ]


def test_secret_is_read_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ARN_VAR, ARN)
    calls = _fake_secrets_manager(monkeypatch)
    password_from(ARN_VAR, PASSWORD_VAR)
    password_from(ARN_VAR, PASSWORD_VAR)
    assert [c for c in calls if "secret_id" in c] == [{"secret_id": ARN}]


def test_password_key_only_is_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ARN_VAR, ARN)
    _fake_secrets_manager(monkeypatch, '{"password": "only-key"}')
    assert password_from(ARN_VAR, PASSWORD_VAR) == "only-key"


@pytest.mark.parametrize(
    "secret_string",
    [
        "plain-leaked-value",
        "{not json leaked-value",
        '["leaked-value"]',
        '"leaked-value"',
        '{"username": "leaked-value"}',
        '{"password": ""}',
        '{"password": 12345}',
    ],
)
def test_rejects_anything_but_json_password(
    monkeypatch: pytest.MonkeyPatch, secret_string: str
) -> None:
    monkeypatch.setenv(ARN_VAR, ARN)
    _fake_secrets_manager(monkeypatch, secret_string)
    with pytest.raises(ConfigError, match=f"{ARN_VAR} must be a JSON object") as info:
        password_from(ARN_VAR, PASSWORD_VAR)
    assert "leaked-value" not in str(info.value)
    assert "12345" not in str(info.value)


def test_secret_without_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ARN_VAR, ARN)
    _fake_secrets_manager(monkeypatch, None)
    with pytest.raises(ConfigError, match="no SecretString"):
        password_from(ARN_VAR, PASSWORD_VAR)


@pytest.mark.parametrize(
    "value",
    ["not-an-arn", "arn:aws:s3:::bucket", "arn:aws:secretsmanager::123:secret:x"],
)
def test_bad_arn(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(ARN_VAR, value)
    with pytest.raises(ConfigError, match="not a Secrets Manager secret ARN"):
        password_from(ARN_VAR, PASSWORD_VAR)


ROLE = "arn:aws:sts::123456789012:assumed-role/supervisor-runtime/session"


@pytest.mark.parametrize(
    ("error", "failure"),
    [
        (
            ClientError(
                {
                    "Error": {
                        "Code": "AccessDeniedException",
                        "Message": f"User: {ROLE} is not authorized on {ARN}",
                    }
                },
                "GetSecretValue",
            ),
            "AccessDeniedException",
        ),
        (NoCredentialsError(), "NoCredentialsError"),
    ],
)
def test_aws_errors_become_config_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    failure: str,
) -> None:
    monkeypatch.setenv(ARN_VAR, ARN)
    _fake_secrets_manager(monkeypatch, error=error)
    with pytest.raises(ConfigError) as raised:
        password_from(ARN_VAR, PASSWORD_VAR)
    message = str(raised.value)
    assert message == f"Could not read the secret in {ARN_VAR} ({failure})."
    assert ROLE not in message
    assert ARN not in message
    # The log names only the failure, and nothing chains the botocore error
    # into a traceback that logger.exception or a startup failure prints.
    assert f"Could not read the secret in {ARN_VAR} ({failure})" in caplog.text
    assert ROLE not in caplog.text
    assert ARN not in caplog.text
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


def test_failure_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ARN_VAR, ARN)
    _fake_secrets_manager(monkeypatch, error=NoCredentialsError())
    with pytest.raises(ConfigError):
        password_from(ARN_VAR, PASSWORD_VAR)
    _fake_secrets_manager(monkeypatch)
    assert password_from(ARN_VAR, PASSWORD_VAR) == "s3cret"


def test_forget_secrets_reads_the_secret_again(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ARN_VAR, ARN)
    calls = _fake_secrets_manager(monkeypatch)
    password_from(ARN_VAR, PASSWORD_VAR)
    secrets.forget_secrets()
    password_from(ARN_VAR, PASSWORD_VAR)
    assert [c for c in calls if "secret_id" in c] == [{"secret_id": ARN}, {"secret_id": ARN}]
