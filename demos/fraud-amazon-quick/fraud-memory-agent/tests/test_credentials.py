"""Offline checks for the Gateway credential settings."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import credentials
from core.credentials import ConfigError, IdentityCredentials

GATEWAY_URL = "https://gateway.example.com/mcp"
PROVIDER = "FraudMemory_default_fraud-gateway"
CLOUD_VARS = ("CREDENTIAL_FRAUD_GATEWAY_NAME", "GATEWAY_URL", "GATEWAY_SCOPES")


def env_without(*names: str) -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in names}


class IdentityCredentialsTests(unittest.TestCase):
    def identity(self, **values: str) -> IdentityCredentials | None:
        with patch.dict(os.environ, env_without(*CLOUD_VARS) | values, clear=True):
            return credentials.identity_credentials()

    def test_neither_variable_selects_the_local_path(self) -> None:
        self.assertIsNone(self.identity())

    def test_both_variables_select_the_cloud_path(self) -> None:
        found = self.identity(
            CREDENTIAL_FRAUD_GATEWAY_NAME=PROVIDER,
            GATEWAY_URL=GATEWAY_URL,
            GATEWAY_SCOPES="neo4j-mcp/invoke other/scope",
        )
        self.assertEqual(
            found,
            IdentityCredentials(GATEWAY_URL, PROVIDER, ("neo4j-mcp/invoke", "other/scope")),
        )

    def test_scopes_default_to_none(self) -> None:
        found = self.identity(CREDENTIAL_FRAUD_GATEWAY_NAME=PROVIDER, GATEWAY_URL=GATEWAY_URL)
        self.assertEqual(found.scopes, ())

    def test_url_without_provider_fails(self) -> None:
        with self.assertRaisesRegex(ConfigError, "CREDENTIAL_FRAUD_GATEWAY_NAME is not set"):
            self.identity(GATEWAY_URL=GATEWAY_URL)

    def test_provider_without_url_fails(self) -> None:
        with self.assertRaisesRegex(ConfigError, "GATEWAY_URL must be set"):
            self.identity(CREDENTIAL_FRAUD_GATEWAY_NAME=PROVIDER)

    def test_plain_http_url_fails(self) -> None:
        with self.assertRaisesRegex(ConfigError, "https"):
            self.identity(
                CREDENTIAL_FRAUD_GATEWAY_NAME=PROVIDER,
                GATEWAY_URL="http://gateway.example.com/mcp",
            )


class CredentialsFileTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(credentials, "_CREDENTIALS", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_is_the_demo_folder_outside_the_zip(self) -> None:
        with patch.dict(os.environ, env_without("MCP_CREDENTIALS_FILE"), clear=True):
            path = credentials.credentials_file()
        agent_root = Path(credentials.__file__).resolve().parents[1]
        self.assertEqual(path, agent_root.parent / ".mcp-credentials.json")
        self.assertNotEqual(path.parent, agent_root)

    def test_override_names_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "creds.json"
            path.write_text('{"gateway_url": "https://g.example.com/mcp"}', encoding="utf-8")
            with patch.dict(os.environ, {"MCP_CREDENTIALS_FILE": str(path)}):
                self.assertEqual(credentials.credentials_file(), path)
                self.assertEqual(
                    credentials.load_credentials()["gateway_url"], "https://g.example.com/mcp"
                )

    def test_missing_file_names_the_copy_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "absent.json")
            with (
                patch.dict(os.environ, {"MCP_CREDENTIALS_FILE": missing}),
                self.assertRaises(FileNotFoundError) as caught,
            ):
                credentials.load_credentials()
        self.assertIn("demos/fraud-amazon-quick/.mcp-credentials.json", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
