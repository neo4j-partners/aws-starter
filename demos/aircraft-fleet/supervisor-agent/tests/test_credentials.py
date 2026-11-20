"""Reading .mcp-credentials.json."""

import json

import pytest

from core.credentials import load_credentials


def write(tmp_path, data: dict):
    path = tmp_path / ".mcp-credentials.json"
    path.write_text(json.dumps(data))
    return path


def test_loads_valid_file(tmp_path):
    data = {"gateway_url": "https://g", "client_id": "id", "client_secret": "s"}
    assert load_credentials(write(tmp_path, data)) == data


def test_missing_file_names_the_copy_command(tmp_path):
    with pytest.raises(FileNotFoundError, match="mcp-credentials.fleet.json"):
        load_credentials(tmp_path / "absent.json")


def test_missing_keys_are_listed(tmp_path):
    path = write(tmp_path, {"gateway_url": "https://g", "client_id": ""})
    with pytest.raises(ValueError, match="client_id, client_secret"):
        load_credentials(path)
