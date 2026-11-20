"""Give the tests their own environment.

This runs before any test module imports ``fleet_graphrag``. It
points ``FLEET_ENV_FILE`` at an empty file so the real aircraft-fleet .env is
never loaded. It also clears the variables the agent reads, so a developer's
shell cannot change what the tests see.
"""

from __future__ import annotations

import os

_AGENT_VARS = (
    "MODEL_ID",
    "MAX_TOKENS",
    "MODEL_EFFORT",
    "AWS_REGION",
    "VECTOR_INDEX_NAME",
    "FULLTEXT_INDEX_NAME",
    "SCHEMA_TTL_S",
    "TEXT2CYPHER_TIMEOUT_S",
    "TEXT2CYPHER_MAX_ROWS",
    "TEXT2CYPHER_MAX_TOKENS",
    "EMBED_MODEL_ID",
    "EMBED_DIMENSIONS",
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
    "NEO4J_PASSWORD_SECRET_ARN",
    "MEM_NEO4J_URI",
    "MEM_NEO4J_USERNAME",
    "MEM_NEO4J_PASSWORD",
    "MEM_NEO4J_DATABASE",
    "MEM_NEO4J_PASSWORD_SECRET_ARN",
    "MEMORY_API_KEY",
)

os.environ["FLEET_ENV_FILE"] = os.devnull
for _name in _AGENT_VARS:
    os.environ.pop(_name, None)
