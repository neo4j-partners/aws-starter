"""Gateway connection settings for the cloud and local auth paths.

Cloud: ``GATEWAY_CREDENTIAL_PROVIDER`` names the AgentCore Identity OAuth2
credential provider that holds the Gateway client secret. ``GATEWAY_URL``
gives the Gateway endpoint. No secret is read from disk.

Local: the credentials file written by ``neo4j-mcp-server/deploy.py``. It
defaults to ``demos/aircraft-fleet/.mcp-credentials.json``, resolved from this
package, so the path does not depend on the working directory. That folder is
outside the deployed code zip, so the secret is never packaged.
``MCP_CREDENTIALS_FILE`` overrides the path.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# supervisor-agent/, the folder that holds main.py and fleet_supervisor/.
# This file is fleet_supervisor/core/credentials.py, two levels below it.
AGENT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CREDENTIALS_FILE = AGENT_ROOT.parent / ".mcp-credentials.json"

REQUIRED_FILE_KEYS = ("gateway_url", "token_url", "client_id", "client_secret")


@dataclass(frozen=True)
class IdentityCredentials:
    """Cloud path: the token comes from an AgentCore Identity provider."""

    gateway_url: str
    provider_name: str
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClientCredentials:
    """Local path: the OAuth client_credentials grant against ``token_url``."""

    gateway_url: str
    token_url: str
    client_id: str
    # repr=False keeps the secret out of logs and tracebacks.
    client_secret: str = field(repr=False)
    scope: str | None = None


GatewayCredentials = IdentityCredentials | ClientCredentials


def load_credentials() -> GatewayCredentials:
    """Pick the auth path from the environment and load its settings."""
    if provider_name := os.getenv("GATEWAY_CREDENTIAL_PROVIDER", "").strip():
        gateway_url = os.getenv("GATEWAY_URL", "").strip()
        if not gateway_url:
            raise ValueError("GATEWAY_URL must be set when GATEWAY_CREDENTIAL_PROVIDER is set")
        logger.info("Using AgentCore Identity provider %s for the Gateway", provider_name)
        return IdentityCredentials(
            gateway_url=gateway_url,
            provider_name=provider_name,
            scopes=tuple(os.getenv("GATEWAY_SCOPES", "").split()),
        )
    return load_credentials_file(credentials_file())


def credentials_file() -> Path:
    """Return the local credentials file path."""
    if override := os.getenv("MCP_CREDENTIALS_FILE", "").strip():
        return Path(override).expanduser()
    return DEFAULT_CREDENTIALS_FILE


def load_credentials_file(path: Path) -> ClientCredentials:
    """Read the local credentials file and check the keys the client needs."""
    if not path.exists():
        raise FileNotFoundError(
            f"Credentials file not found: {path}\n"
            "Copy it from the MCP server deployment:\n"
            "  cp neo4j-mcp-server/.mcp-credentials.fleet.json "
            "demos/aircraft-fleet/.mcp-credentials.json"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_FILE_KEYS if not data.get(key)]
    if missing:
        raise ValueError(f"Credentials file is missing: {', '.join(missing)}")
    if urlparse(data["token_url"]).scheme != "https":
        raise ValueError("Credentials file token_url must be an https URL")
    logger.info("Loaded Gateway credentials from %s", path)
    return ClientCredentials(
        gateway_url=data["gateway_url"],
        token_url=data["token_url"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scope=data.get("scope") or None,
    )
