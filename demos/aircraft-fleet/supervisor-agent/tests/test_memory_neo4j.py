"""The shared memory client against a real Neo4j, in a throwaway database.

Skipped unless MEM_TEST_NEO4J_URI and MEM_TEST_NEO4J_PASSWORD are set. Point
them at a local Neo4j Enterprise server, never at Aura. The test creates its
own database and drops it at the end. It calls Bedrock for embeddings, so it
needs AWS credentials.

    MEM_TEST_NEO4J_URI=bolt://127.0.0.1:37687 \\
    MEM_TEST_NEO4J_PASSWORD=... uv run pytest tests/test_memory_neo4j.py
"""

import os
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from neo4j import GraphDatabase
from strands import Agent
from strands.models import Model

from fleet_supervisor import server
from fleet_supervisor.core import memory, secrets

TEST_URI = os.environ.get("MEM_TEST_NEO4J_URI", "")
TEST_PASSWORD = os.environ.get("MEM_TEST_NEO4J_PASSWORD", "")
# No Bedrock model has this ID, so every extraction fails.
MISSING_MODEL = "bedrock/fleet-test.no-such-model-v0"
SETTLE_SECONDS = 120.0

pytestmark = pytest.mark.skipif(
    not (TEST_URI and TEST_PASSWORD),
    reason="MEM_TEST_NEO4J_URI and MEM_TEST_NEO4J_PASSWORD are not set",
)


class FixedModel(Model):
    """Answers every prompt with fixed text."""

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> Any:
        return {}

    def structured_output(self, *args: Any, **kwargs: Any):
        raise NotImplementedError

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockDelta": {"delta": {"text": "Noted."}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}


@pytest.fixture
def database() -> Iterator[str]:
    """Create a throwaway database and drop it afterwards."""
    name = f"fleettest{uuid.uuid4().hex[:12]}"
    with GraphDatabase.driver(TEST_URI, auth=("neo4j", TEST_PASSWORD)) as driver:
        driver.execute_query(f"CREATE DATABASE {name} WAIT", database_="system")
        try:
            yield name
        finally:
            driver.execute_query(f"DROP DATABASE {name} IF EXISTS WAIT", database_="system")


@pytest.fixture
def local_memory(monkeypatch: pytest.MonkeyPatch, database: str) -> Iterator[None]:
    """Point memory at the throwaway database, with an extraction model that fails."""
    monkeypatch.setenv("MEM_NEO4J_URI", TEST_URI)
    monkeypatch.setenv("MEM_NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("MEM_NEO4J_DATABASE", database)
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", TEST_PASSWORD)
    monkeypatch.delenv("MEM_NEO4J_PASSWORD_SECRET_ARN", raising=False)
    monkeypatch.setattr(memory, "EXTRACTION_MODEL", MISSING_MODEL)
    monkeypatch.setattr(memory, "_settings", None)
    monkeypatch.setattr(memory, "_settings_build", None)
    monkeypatch.setattr(memory, "_shared", None)
    monkeypatch.setattr(memory, "_shared_open", None)
    monkeypatch.setattr(memory, "_retired", set())
    monkeypatch.setattr(memory, "_closers", set())
    monkeypatch.setattr(memory, "_shutting_down", False)
    secrets._read_secret.cache_clear()
    try:
        yield
    finally:
        memory.close_shared_memory()
        secrets._read_secret.cache_clear()


def _wait_until_idle() -> bool:
    deadline = time.monotonic() + SETTLE_SECONDS
    while time.monotonic() < deadline:
        if server.app.get_async_task_info()["active_count"] == 0:
            return True
        time.sleep(0.2)
    return False


def test_a_failed_extraction_still_completes_its_task(local_memory, monkeypatch) -> None:
    started: list[str] = []
    finished: list[str] = []
    lock = threading.Lock()

    def recording_hook(name: str):
        with lock:
            started.append(name)
        done = server.track_background_task(name)

        def recording_done() -> None:
            with lock:
                finished.append(name)
            done()

        return recording_done

    session_id = f"s-{uuid.uuid4().hex[:8]}"
    first = memory.build_session_manager(
        session_id, "tester", memory.memory_settings(), recording_hook
    )
    try:
        Agent(model=FixedModel(), session_manager=first.manager, callback_handler=None)(
            "Aircraft N123 had a hydraulic leak."
        )
    finally:
        first.close()

    assert _wait_until_idle(), server.app.get_async_task_info()
    assert started
    assert all(name == f"extract:{session_id}" for name in started)
    assert sorted(finished) == sorted(started)

    # A second request on the same client restores the first one's turn.
    second = memory.build_session_manager(
        session_id, "tester", memory.memory_settings(), recording_hook
    )
    try:
        agent = Agent(model=FixedModel(), session_manager=second.manager, callback_handler=None)
        texts = [block.get("text") for message in agent.messages for block in message["content"]]
        assert "Aircraft N123 had a hydraulic leak." in texts
    finally:
        second.close()
    assert memory._shared is not None
    shared = memory._shared.memory

    memory.close_shared_memory()

    assert shared.closed
    assert _wait_until_idle(), server.app.get_async_task_info()
