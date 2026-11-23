"""Gateway credentials for the cloud and local auth paths.

Cloud: ``CREDENTIAL_FRAUD_GATEWAY_NAME`` names the AgentCore Identity OAuth2
credential provider that holds the Gateway client secret. The AgentCore CDK
construct sets it on the Runtime because ``agent.sh deploy`` declares the
``fraud-gateway`` credential. ``GATEWAY_URL`` gives the Gateway endpoint, and
``agentcore/cdk/lib/cdk-stack.ts`` sets it. Either variable selects this path,
and then both must be set. No secret is read from disk.

Local: the credentials file written by ``neo4j-mcp-server/deploy.py``. It
defaults to ``demos/fraud-amazon-quick/.mcp-credentials.json``, resolved from
this package, so the path does not depend on the working directory. That
folder is outside the deployed code zip, so the secret is never packaged.
``MCP_CREDENTIALS_FILE`` overrides the path. The access token is refreshed in
memory only, with no file writes.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# fraud-memory-agent/, the folder that holds main.py and core/. This file is
# core/credentials.py, one level below it.
AGENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CREDENTIALS_FILE = AGENT_ROOT.parent / ".mcp-credentials.json"

# The construct names these variables after the credentials:
# CREDENTIAL_<NAME>_NAME.
GATEWAY_PROVIDER_VAR = "CREDENTIAL_FRAUD_GATEWAY_NAME"
NAMS_PROVIDER_VAR = "CREDENTIAL_NAMS_API_KEY_NAME"

# Loaded once per process, refreshed in memory only.
_CREDENTIALS: dict | None = None


class ConfigError(ValueError):
    """A Runtime setting is missing or invalid."""


@dataclass(frozen=True)
class IdentityCredentials:
    """Cloud path: the Gateway token comes from an AgentCore Identity provider."""

    gateway_url: str
    provider_name: str
    scopes: tuple[str, ...] = ()


def is_https(url: str) -> bool:
    """Report whether the URL uses https, so tokens never travel in clear text."""
    return urlparse(url).scheme == "https"


def identity_credentials() -> IdentityCredentials | None:
    """Return the cloud path settings, or None for the local path."""
    provider_name = os.getenv(GATEWAY_PROVIDER_VAR, "").strip()
    gateway_url = os.getenv("GATEWAY_URL", "").strip()
    if not provider_name and not gateway_url:
        return None
    if not provider_name:
        raise ConfigError(
            f"{GATEWAY_PROVIDER_VAR} is not set. The AgentCore construct sets it when "
            "agentcore.json declares the fraud-gateway credential. "
            "Deploy with ./agent.sh deploy, which declares it."
        )
    if not gateway_url:
        raise ConfigError(f"GATEWAY_URL must be set when {GATEWAY_PROVIDER_VAR} is set")
    if not is_https(gateway_url):
        raise ConfigError("GATEWAY_URL must be an https URL")
    return IdentityCredentials(
        gateway_url=gateway_url,
        provider_name=provider_name,
        scopes=tuple(os.getenv("GATEWAY_SCOPES", "").split()),
    )


def credentials_file() -> Path:
    """Return the local credentials file path."""
    if override := os.getenv("MCP_CREDENTIALS_FILE", "").strip():
        return Path(override).expanduser()
    return DEFAULT_CREDENTIALS_FILE


def load_credentials() -> dict:
    """Load the local credentials file into a process cache."""
    global _CREDENTIALS

    if _CREDENTIALS is None:
        path = credentials_file()
        if not path.exists():
            raise FileNotFoundError(
                f"Credentials file not found: {path}\n"
                "Copy it from the MCP server deployment:\n"
                "  cp neo4j-mcp-server/.mcp-credentials.finance.json "
                "demos/fraud-amazon-quick/.mcp-credentials.json"
            )
        with open(path, encoding="utf-8") as f:
            _CREDENTIALS = json.load(f)
        logger.info("Credentials loaded into memory from %s", path)

    return _CREDENTIALS


def check_token_expiry(credentials: dict) -> bool:
    """Return True if the access token is present and not expiring in 5 min."""
    expires_at_str = credentials.get("token_expires_at")
    if not expires_at_str:
        return False
    try:
        expires_at = datetime.fromisoformat(expires_at_str)
        now = datetime.now(UTC)
        return now < (expires_at - timedelta(minutes=5))
    except (ValueError, TypeError):
        return False


def refresh_token(credentials: dict) -> dict:
    """Refresh the OAuth2 access token via client credentials (in memory)."""
    token_url = credentials.get("token_url")
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    scope = credentials.get("scope")

    if not all([token_url, client_id, client_secret]):
        raise ValueError("Missing token refresh credentials (token_url, client_id, client_secret)")

    logger.info("Refreshing OAuth2 token...")
    response = httpx.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    response.raise_for_status()
    token_data = response.json()

    expires_in = token_data.get("expires_in", 3600)
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

    credentials["access_token"] = token_data["access_token"]
    credentials["token_expires_at"] = expires_at.isoformat()

    logger.info("Token refreshed (in-memory). Expires: %s", expires_at.isoformat())
    return credentials


def get_active_credentials() -> dict:
    """Load credentials and refresh the token if missing or expiring."""
    credentials = load_credentials()
    if not check_token_expiry(credentials):
        credentials = refresh_token(credentials)
    return credentials
