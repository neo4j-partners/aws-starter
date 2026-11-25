"""Shared test helpers. Tests run offline: no Bedrock and no Neo4j.

This runs before any test module imports ``fleet_supervisor``. It points
``FLEET_ENV_FILE`` at an empty file so the real aircraft-fleet .env is never
loaded. It also clears the fleet graph, graph settings, memory, and
supervisor mode variables, so a developer's shell cannot change what the tests
see.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

# Import the package before any test module imports boto3, so its truststore
# injection runs first, as it does in the console scripts and the Runtime.
import fleet_supervisor  # noqa: F401
from tests.fake_bolt import FakeNeo4j

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
    "AGENT_ARN",
    "FLEET_SUPERVISOR_MODE",
)

os.environ["FLEET_ENV_FILE"] = os.devnull
for _name in _CLEARED_VARS:
    os.environ.pop(_name, None)


def collect(stream: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drain an async generator into a list."""

    async def _drain() -> list[dict[str, Any]]:
        return [event async for event in stream]

    return asyncio.run(_drain())


@pytest.fixture
def fleet_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Path]:
    """Return a function that writes a shared .env and points ``FLEET_ENV_FILE`` at it.

    Loading the file sets variables outside monkeypatch, so the variables it
    may set are recorded first and restored after the test.
    """
    for name in ("AGENT_ARN", "AWS_REGION", "AGENT_PORT", "FLEET_SUPERVISOR_MODE"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)

    def write(text: str) -> Path:
        path = tmp_path / ".env"
        path.write_text(text)
        monkeypatch.setenv("FLEET_ENV_FILE", str(path))
        return path

    return write


@pytest.fixture
def fake_neo4j() -> Iterator[FakeNeo4j]:
    """A fake Neo4j on a local port that accepts only the password ``rotated-pw``."""
    with FakeNeo4j(password="rotated-pw") as server:
        yield server
