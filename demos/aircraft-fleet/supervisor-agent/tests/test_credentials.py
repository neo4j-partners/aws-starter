"""Choosing the auth path and reading the local credentials file."""

import json

import pytest

import core.credentials as credentials_module
from core.credentials import (
    DEFAULT_CREDENTIALS_FILE,
    ClientCredentials,
    IdentityCredentials,
    credentials_file,
    load_credentials,
    load_credentials_file,
)

VALID = {
    "gateway_url": "https://g/mcp",
    "token_url": "https://auth.example/oauth2/token",
    "client_id": "id",
    "client_secret": "s3cret",
    "scope": "fleet/read",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "GATEWAY_CREDENTIAL_PROVIDER",
        "GATEWAY_URL",
        "GATEWAY_SCOPES",
        "MCP_CREDENTIALS_FILE",
    ):
        monkeypatch.delenv(name, raising=False)


def write(tmp_path, data: dict):
    path = tmp_path / ".mcp-credentials.json"
    path.write_text(json.dumps(data))
    return path


def test_default_file_is_outside_the_code_zip():
    # The code zip is supervisor-agent/; the default file sits one level up.
    agent_root = credentials_module.AGENT_ROOT
    assert DEFAULT_CREDENTIALS_FILE.parent == agent_root.parent
    assert agent_root not in DEFAULT_CREDENTIALS_FILE.parents


def test_env_overrides_file_path(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_CREDENTIALS_FILE", str(tmp_path / "x.json"))
    assert credentials_file() == tmp_path / "x.json"


def test_loads_valid_file(tmp_path):
    loaded = load_credentials_file(write(tmp_path, VALID))
    assert loaded == ClientCredentials(**VALID)


def test_secret_is_not_in_repr(tmp_path):
    assert "s3cret" not in repr(load_credentials_file(write(tmp_path, VALID)))


def test_missing_file_names_the_copy_command(tmp_path):
    with pytest.raises(FileNotFoundError, match="mcp-credentials.fleet.json"):
        load_credentials_file(tmp_path / "absent.json")


def test_missing_keys_are_listed(tmp_path):
    path = write(tmp_path, {"gateway_url": "https://g", "client_id": ""})
    with pytest.raises(ValueError, match="token_url, client_id, client_secret"):
        load_credentials_file(path)


def test_token_url_must_be_https(tmp_path):
    path = write(tmp_path, {**VALID, "token_url": "http://auth.example/token"})
    with pytest.raises(ValueError, match="https"):
        load_credentials_file(path)


def test_local_path_reads_the_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_CREDENTIALS_FILE", str(write(tmp_path, VALID)))
    assert isinstance(load_credentials(), ClientCredentials)


def test_provider_env_selects_identity(monkeypatch):
    monkeypatch.setenv("GATEWAY_CREDENTIAL_PROVIDER", "fleet-gateway")
    monkeypatch.setenv("GATEWAY_URL", "https://g/mcp")
    monkeypatch.setenv("GATEWAY_SCOPES", "a/b c/d")
    assert load_credentials() == IdentityCredentials(
        "https://g/mcp", "fleet-gateway", ("a/b", "c/d")
    )


def test_identity_needs_gateway_url(monkeypatch):
    monkeypatch.setenv("GATEWAY_CREDENTIAL_PROVIDER", "fleet-gateway")
    with pytest.raises(ValueError, match="GATEWAY_URL"):
        load_credentials()
