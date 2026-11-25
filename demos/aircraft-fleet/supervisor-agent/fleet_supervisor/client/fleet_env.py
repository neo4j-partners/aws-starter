"""The shared aircraft-fleet .env for the local clients.

The file sits next to supervisor-agent/, three levels above this package.
``FLEET_ENV_FILE`` names a different file, and the tests point it at an empty
one. Variables already set in the shell win over the file.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

NO_AGENT_ARN = (
    "ERROR: AGENT_ARN is not set. Deploy the supervisor with ./agent.sh deploy, "
    "or set AGENT_ARN in the shared .env."
)


def env_file() -> Path:
    """The shared aircraft-fleet .env, or the file ``FLEET_ENV_FILE`` names."""
    if override := os.environ.get("FLEET_ENV_FILE"):
        return Path(override)
    return Path(__file__).resolve().parents[3] / ".env"


def load_fleet_env() -> None:
    """Load the shared .env without replacing variables that are already set."""
    load_dotenv(env_file())


def require_agent_arn() -> str:
    """Return ``AGENT_ARN``, or exit with a message that says how to set it."""
    if agent_arn := os.environ.get("AGENT_ARN"):
        return agent_arn
    sys.exit(NO_AGENT_ARN)
