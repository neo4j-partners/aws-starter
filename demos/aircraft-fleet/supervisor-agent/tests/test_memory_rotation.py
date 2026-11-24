"""A memory password rotated while the memory client is connected.

These tests run the real async driver against the fake Bolt server, and the
real Strands session manager on a fake memory client. The settings' auth
manager gives the driver the memory login, so a write Neo4j rejected after
the agent was built succeeds when the session closes, with the login read
again.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace
from typing import Any

import neo4j
import pytest
from neo4j.exceptions import AuthError
from neo4j_agent_memory import MemorySettings
from neo4j_agent_memory.integrations.strands import Neo4jSessionManager
from strands import Agent
from strands.models import Model

from fleet_supervisor import server
from fleet_supervisor.core import memory, secrets
from tests.conftest import collect
from tests.fake_bolt import FakeNeo4j

MEM_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:fleet-memory"
FLEET_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:fleet-graph"


@dataclasses.dataclass
class FakeSecret:
    """The memory secret's password history and how often it was read."""

    passwords: list[str] = dataclasses.field(default_factory=lambda: ["old-pw"])
    reads: int = 0

    def rotate(self, password: str) -> None:
        self.passwords.append(password)


@pytest.fixture
def fleet_secret(monkeypatch: pytest.MonkeyPatch) -> secrets._SecretLogin:
    """The fleet secret, already in the cache. Any read of it fails the test."""
    cached = secrets._SecretLogin("reader", "fleet-pw")
    monkeypatch.setitem(secrets._secrets, (FLEET_SECRET_ARN, "NEO4J_PASSWORD_SECRET_ARN"), cached)
    return cached


@pytest.fixture
def memory_secret(
    monkeypatch: pytest.MonkeyPatch, fake_neo4j: FakeNeo4j, fleet_secret: secrets._SecretLogin
) -> Iterator[FakeSecret]:
    """Point memory at the fake server, with its secret in a fake Secrets Manager."""
    secret = FakeSecret()

    def get_secret_value(SecretId: str) -> dict[str, str]:
        assert SecretId == MEM_SECRET_ARN
        secret.reads += 1
        return {
            "SecretString": json.dumps({"username": "memory", "password": secret.passwords[-1]})
        }

    monkeypatch.setattr(
        secrets.boto3,
        "client",
        lambda service, region_name: SimpleNamespace(get_secret_value=get_secret_value),
    )
    monkeypatch.setenv("MEM_NEO4J_URI", fake_neo4j.uri)
    monkeypatch.setenv("MEM_NEO4J_PASSWORD_SECRET_ARN", MEM_SECRET_ARN)
    monkeypatch.setenv("NEO4J_PASSWORD_SECRET_ARN", FLEET_SECRET_ARN)
    monkeypatch.setattr(memory, "_settings", None)
    monkeypatch.setattr(memory, "_settings_build", None)
    yield secret
    secrets._secrets.clear()


async def write(settings: MemorySettings, message_id: str) -> None:
    """Write one message the way the memory client does, on a new connection."""
    driver = neo4j.AsyncGraphDatabase.driver(
        settings.neo4j.uri,
        auth=settings.neo4j.auth_manager,
        connection_timeout=2,
        max_transaction_retry_time=0,
    )
    try:
        await driver.execute_query("CREATE (m:Message {id: $id})", id=message_id, database_="neo4j")
    finally:
        await driver.close()


def test_the_settings_log_in_with_a_memory_auth_manager(memory_secret: FakeSecret) -> None:
    settings = memory.memory_settings()
    assert isinstance(settings.neo4j.auth_manager, memory.MemoryLoginAuthManager)
    assert isinstance(settings.neo4j.auth_manager, neo4j.auth_management.AsyncAuthManager)
    assert memory_secret.reads == 1


def test_a_reload_reads_only_the_memory_secret(
    memory_secret: FakeSecret, fake_neo4j: FakeNeo4j, fleet_secret: secrets._SecretLogin
) -> None:
    settings = memory.memory_settings()
    memory_secret.rotate("rotated-pw")

    with pytest.raises(AuthError):
        asyncio.run(write(settings, "m1"))
    assert memory.reload_memory_login(settings) is True
    asyncio.run(write(settings, "m1"))

    assert fake_neo4j.logins == ["old-pw", "rotated-pw"]
    assert memory_secret.reads == 2
    assert secrets._secrets[(FLEET_SECRET_ARN, "NEO4J_PASSWORD_SECRET_ARN")] is fleet_secret


def test_a_reload_of_an_unchanged_password_says_so(
    memory_secret: FakeSecret, fake_neo4j: FakeNeo4j
) -> None:
    settings = memory.memory_settings()
    with pytest.raises(AuthError):
        asyncio.run(write(settings, "m1"))
    assert memory.reload_memory_login(settings) is False
    with pytest.raises(AuthError):
        asyncio.run(write(settings, "m1"))
    assert fake_neo4j.logins == ["old-pw", "old-pw"]
    assert memory_secret.reads == 2


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


class DriverMemoryClient:
    """A memory client that writes each message on the settings' driver login.

    Each write opens a new connection, so the fake server checks its login.
    ``attempts`` lists the message id of every write, and ``written`` the
    ids that the server accepted.
    """

    is_connected = True
    is_nams = False

    def __init__(self, settings: MemorySettings) -> None:
        self.attempts: list[str] = []
        self.written: list[str] = []
        self.short_term = SimpleNamespace(
            get_conversation=self._get_conversation,
            add_message=lambda *args, **kwargs: self._add_message(settings, *args, **kwargs),
        )

    async def _get_conversation(self, session_id: str, **kwargs: Any) -> Any:
        return SimpleNamespace(messages=[])

    async def _add_message(
        self, settings: MemorySettings, session_id: str, role: str, text: str, **kwargs: Any
    ) -> None:
        message_id = str(kwargs["message_id"])
        self.attempts.append(message_id)
        await write(settings, message_id)
        self.written.append(message_id)


@pytest.fixture
def real_session(
    monkeypatch: pytest.MonkeyPatch, memory_secret: FakeSecret
) -> list[DriverMemoryClient]:
    """Run server.invoke with a real agent and a real session manager on the fake server.

    Returns the memory clients the requests used.
    """
    clients: list[DriverMemoryClient] = []

    def build_session(session_id, user_id, settings, background_hook):
        client = DriverMemoryClient(settings)
        clients.append(client)
        manager = Neo4jSessionManager(
            session_id, memory_client=client, user_id=user_id, extract_entities=False
        )
        return SimpleNamespace(manager=manager, settings=settings, close=manager.close)

    def build_agent(model, schema, session_manager=None):
        return Agent(model=FixedModel(), session_manager=session_manager, callback_handler=None)

    monkeypatch.setattr(server, "get_model", lambda: object())
    monkeypatch.setattr(server, "get_graph_schema", lambda: "SCHEMA")
    monkeypatch.setattr(server, "memory_settings", memory.memory_settings)
    monkeypatch.setattr(server, "build_session_manager", build_session)
    monkeypatch.setattr(server, "build_supervisor", build_agent)
    return clients


def test_a_late_write_after_a_rotation_is_written_at_close_under_its_id(
    real_session: list[DriverMemoryClient],
    memory_secret: FakeSecret,
    fake_neo4j: FakeNeo4j,
    fleet_secret: secrets._SecretLogin,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The settings read the old password. It rotates before the turn ends.
    memory.memory_settings()
    memory_secret.rotate("rotated-pw")

    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))

    assert events[-1] == {"type": "complete"}
    [client] = real_session
    first, retry, reply = client.attempts
    # The end-of-turn write failed, and the close wrote it under the same id.
    assert retry == first and reply != first
    assert client.written == [first, reply]
    assert fake_neo4j.logins == ["old-pw", "rotated-pw", "rotated-pw"]
    assert memory_secret.reads == 2
    assert secrets._secrets[(FLEET_SECRET_ARN, "NEO4J_PASSWORD_SECRET_ARN")] is fleet_secret
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("rejected the memory login on a late write" in r.getMessage() for r in warnings)
    assert "Request failed" not in caplog.text
    assert "Error while closing the memory session manager" not in caplog.text


def test_a_late_write_with_a_still_wrong_password_fails_after_one_more_try(
    real_session: list[DriverMemoryClient],
    memory_secret: FakeSecret,
    fake_neo4j: FakeNeo4j,
    caplog: pytest.LogCaptureFixture,
) -> None:
    events = collect(server.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))

    # The answer already streamed, so the request completes. The close
    # tries each message once more, then drops it and logs the failure.
    assert events[-1] == {"type": "complete"}
    [client] = real_session
    first, retry, reply = client.attempts
    assert retry == first and reply != first
    assert client.written == []
    assert fake_neo4j.logins == ["old-pw", "old-pw", "old-pw"]
    # One read for the settings and one for the reload, which found no change.
    assert memory_secret.reads == 2
    assert "the password has not changed" in caplog.text
    assert "Error while closing the memory session manager" in caplog.text
