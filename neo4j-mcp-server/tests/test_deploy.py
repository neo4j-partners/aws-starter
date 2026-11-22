"""Tests for deploy.py helpers that need no AWS access."""

import pytest

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
