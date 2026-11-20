"""Load the Gateway credentials file.

``.mcp-credentials.json`` sits at the agent root (one level above this
package), so the path does not depend on the working directory. The Strands
``MCPClient`` fetches and refreshes the OAuth token itself, so this module
only reads the file.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

AGENT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = AGENT_ROOT / ".mcp-credentials.json"


def load_credentials(path: Path = CREDENTIALS_FILE) -> dict:
    """Read the credentials file and check the keys the MCP client needs."""
    if not path.exists():
        raise FileNotFoundError(
            f"Credentials file not found: {path}\n"
            "Copy it from the MCP server deployment:\n"
            "  cp ../../../neo4j-mcp-server/.mcp-credentials.fleet.json .mcp-credentials.json"
        )
    credentials = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in ("gateway_url", "client_id", "client_secret") if not credentials.get(k)]
    if missing:
        raise ValueError(f"Credentials file is missing: {', '.join(missing)}")
    logger.info("Loaded Gateway credentials from %s", path.name)
    return credentials
