"""Tests for the supervisor memory settings and session manager factory."""

from __future__ import annotations

import pytest
from neo4j_agent_memory.config.settings import ExtractorType
from neo4j_agent_memory.integrations.strands import Neo4jSessionManager

from fleet_supervisor.core import memory, secrets
from fleet_supervisor.core.config import ConfigError

MEM_VARS = (
    "MEM_NEO4J_URI",
    "MEM_NEO4J_USERNAME",
    "MEM_NEO4J_PASSWORD",
    "MEM_NEO4J_PASSWORD_SECRET_ARN",
    "MEM_NEO4J_DATABASE",
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    for name in MEM_VARS:
        monkeypatch.delenv(name, raising=False)
    memory.memory_settings.cache_clear()
    secrets._read_secret.cache_clear()
    yield
    memory.memory_settings.cache_clear()


@pytest.fixture
def memory_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_URI", "bolt://127.0.0.1:37687")
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "local-pw")


def test_memory_is_off_without_a_uri() -> None:
    assert memory.memory_settings() is None
    assert memory.build_session_manager("s1", "u1") is None


def test_uri_without_a_password_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_URI", "bolt://127.0.0.1:37687")
    with pytest.raises(ConfigError, match="MEM_NEO4J_PASSWORD_SECRET_ARN.*MEM_NEO4J_PASSWORD"):
        memory.memory_settings()


def test_settings_come_from_the_mem_vars(monkeypatch: pytest.MonkeyPatch, memory_on) -> None:
    monkeypatch.setenv("MEM_NEO4J_USERNAME", "mem_user")
    monkeypatch.setenv("MEM_NEO4J_DATABASE", "memdb")
    settings = memory.memory_settings()
    assert settings.backend == "bolt"
    assert settings.neo4j.uri == "bolt://127.0.0.1:37687"
    assert settings.neo4j.username == "mem_user"
    assert settings.neo4j.database == "memdb"
    assert settings.neo4j.password.get_secret_value() == "local-pw"
    assert settings.extraction.extractor_type is ExtractorType.LLM


def test_username_and_database_default_to_neo4j(memory_on) -> None:
    settings = memory.memory_settings()
    assert (settings.neo4j.username, settings.neo4j.database) == ("neo4j", "neo4j")


def test_nam_env_file_is_not_read(monkeypatch: pytest.MonkeyPatch, tmp_path, memory_on) -> None:
    (tmp_path / ".env").write_text("NAM_NEO4J__URI=bolt://from-dotenv:7687\n")
    monkeypatch.chdir(tmp_path)
    assert memory.memory_settings().neo4j.uri == "bolt://127.0.0.1:37687"


def test_settings_are_built_once(memory_on) -> None:
    assert memory.memory_settings() is memory.memory_settings()


def test_session_manager_uses_settings_and_retrieval_config(memory_on) -> None:
    manager = memory.build_session_manager("s1", "u1")
    try:
        assert isinstance(manager, Neo4jSessionManager)
        assert manager.session_id == "s1"
        assert manager._user_id == "u1"
        assert manager._retrieval_config.min_score == memory.RETRIEVAL_MIN_SCORE
    finally:
        # Never connected, so close only stops the unused bridge.
        manager.close()


def test_each_request_gets_its_own_manager(memory_on) -> None:
    first = memory.build_session_manager("s1", "u1")
    second = memory.build_session_manager("s1", "u1")
    try:
        assert first is not second
    finally:
        first.close()
        second.close()
