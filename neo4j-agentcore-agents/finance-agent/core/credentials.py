"""Credential loading and in-memory OAuth2 token refresh.

Credentials come from ``.mcp-credentials.json`` at the agent root (one level
above this package, so resolution is stable regardless of the working
directory). The access token is refreshed in memory only — no
file writes — so this works unchanged on AgentCore Runtime where the
filesystem is ephemeral.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Anchor to the agent root (parent of the `core` package), not to the
# current working directory, so credential resolution is stable.
AGENT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = AGENT_ROOT / ".mcp-credentials.json"

# Loaded once per process, refreshed in memory only.
_CREDENTIALS: dict | None = None


def load_credentials() -> dict:
    """Load credentials from ``.mcp-credentials.json`` into a process cache."""
    global _CREDENTIALS

    if _CREDENTIALS is None:
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"Credentials file not found: {CREDENTIALS_FILE}\n"
                "Copy from the MCP server deployment:\n"
                "  cp ../../neo4j-agentcore-mcp-server/.mcp-credentials.json ."
            )
        with open(CREDENTIALS_FILE, encoding="utf-8") as f:
            _CREDENTIALS = json.load(f)
        logger.info("Credentials loaded into memory")

    return _CREDENTIALS


def check_token_expiry(credentials: dict) -> bool:
    """Return True if the access token is present and not expiring in 5 min."""
    expires_at_str = credentials.get("token_expires_at")
    if not expires_at_str:
        return False
    try:
        expires_at = datetime.fromisoformat(expires_at_str)
        now = datetime.now(timezone.utc)
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
        raise ValueError(
            "Missing token refresh credentials "
            "(token_url, client_id, client_secret)"
        )

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
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

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
