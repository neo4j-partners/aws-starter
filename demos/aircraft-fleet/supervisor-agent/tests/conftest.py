"""Shared test helpers. Tests run offline: no Bedrock and no Neo4j.

This runs before any test module imports ``fleet_supervisor``. It points
``FLEET_ENV_FILE`` at an empty file so the real aircraft-fleet .env is never
loaded. It also clears the fleet graph, graph settings, and memory variables,
so a developer's shell cannot change what the tests see.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

# Import the package before any test module imports boto3, so its truststore
# injection runs first, as it does in the console scripts and the Runtime.
import fleet_supervisor  # noqa: F401

_CLEARED_VARS = (
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
    "NEO4J_PASSWORD_SECRET_ARN",
    "VECTOR_INDEX_NAME",
    "FULLTEXT_INDEX_NAME",
    "SCHEMA_TTL_S",
    "TEXT2CYPHER_TIMEOUT_S",
    "TEXT2CYPHER_MAX_ROWS",
    "TEXT2CYPHER_MAX_TOKENS",
    "EMBED_MODEL_ID",
    "EMBED_DIMENSIONS",
    "MEM_NEO4J_URI",
    "MEM_NEO4J_USERNAME",
    "MEM_NEO4J_PASSWORD",
    "MEM_NEO4J_DATABASE",
    "MEM_NEO4J_PASSWORD_SECRET_ARN",
    "MEMORY_API_KEY",
)

os.environ["FLEET_ENV_FILE"] = os.devnull
for _name in _CLEARED_VARS:
    os.environ.pop(_name, None)


def collect(stream: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drain an async generator into a list."""

    async def _drain() -> list[dict[str, Any]]:
        return [event async for event in stream]

    return asyncio.run(_drain())
