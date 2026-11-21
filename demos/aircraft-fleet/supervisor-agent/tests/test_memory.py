"""Tests for the supervisor memory settings and session manager factory."""

from __future__ import annotations

import pytest
from neo4j.exceptions import AuthError
from neo4j_agent_memory.config.settings import ExtractorType
from neo4j_agent_memory.core.exceptions import ConnectionError as MemoryConnectionError
from neo4j_agent_memory.integrations.strands import Neo4jSessionManager
from neo4j_agent_memory.llm.adapters.bedrock import BedrockEmbeddingProvider, BedrockProvider

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
    monkeypatch.setattr(memory, "_settings", None)
    secrets._read_secret.cache_clear()


@pytest.fixture
def memory_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_URI", "bolt://127.0.0.1:37687")
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "local-pw")


def test_missing_uri_raises() -> None:
    with pytest.raises(ConfigError, match="MEM_NEO4J_URI is not set"):
        memory.memory_settings()


def test_missing_uri_failure_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError):
        memory.memory_settings()
    monkeypatch.setenv("MEM_NEO4J_URI", "bolt://127.0.0.1:37687")
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "local-pw")
    assert memory.memory_settings().neo4j.uri == "bolt://127.0.0.1:37687"


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


def test_bedrock_providers_are_explicit(memory_on) -> None:
    settings = memory.memory_settings()
    assert isinstance(settings.embedding, BedrockEmbeddingProvider)
    assert settings.embedding.model == memory.EMBEDDING_MODEL
    assert settings.embedding.dimensions == memory.EMBEDDING_DIMENSIONS == 1024
    assert settings.embedding._aws_region == memory.AWS_REGION
    assert isinstance(settings.llm, BedrockProvider)
    assert settings.llm._aws_region == memory.AWS_REGION


def test_memory_api_key_does_not_switch_backends(
    monkeypatch: pytest.MonkeyPatch, memory_on
) -> None:
    monkeypatch.setenv("MEMORY_API_KEY", "not-used")
    assert memory.memory_settings().backend == "bolt"


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
    manager = memory.build_session_manager("s1", "u1", memory.memory_settings())
    try:
        assert isinstance(manager, Neo4jSessionManager)
        assert manager.session_id == "s1"
        assert manager._user_id == "u1"
        assert manager._retrieval_config.min_score == memory.RETRIEVAL_MIN_SCORE
        assert manager._extract_entities is True
        assert manager._record_tool_calls is False
    finally:
        # Never connected, so close only stops the unused bridge.
        manager.close()


def test_each_request_gets_its_own_manager(memory_on) -> None:
    first = memory.build_session_manager("s1", "u1", memory.memory_settings())
    second = memory.build_session_manager("s1", "u1", memory.memory_settings())
    try:
        assert first is not second
    finally:
        first.close()
        second.close()


def test_forget_memory_settings_reads_the_password_again(
    monkeypatch: pytest.MonkeyPatch, memory_on
) -> None:
    failed = memory.memory_settings()
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "rotated-pw")
    assert memory.memory_settings().neo4j.password.get_secret_value() == "local-pw"
    memory.forget_memory_settings(failed)
    assert memory.memory_settings().neo4j.password.get_secret_value() == "rotated-pw"


def test_a_late_failure_with_the_old_password_keeps_the_new_settings(
    monkeypatch: pytest.MonkeyPatch, memory_on
) -> None:
    # Two requests fail with the old password. The first drops it and the
    # next build reads the new one. The second must not drop that.
    failed = memory.memory_settings()
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "rotated-pw")
    memory.forget_memory_settings(failed)
    rebuilt = memory.memory_settings()
    forgotten: list[bool] = []
    monkeypatch.setattr(memory, "forget_secrets", lambda: forgotten.append(True))

    memory.forget_memory_settings(failed)

    assert memory.memory_settings() is rebuilt
    assert forgotten == []


def test_a_failure_after_another_request_dropped_the_settings_does_nothing(
    monkeypatch: pytest.MonkeyPatch, memory_on
) -> None:
    failed = memory.memory_settings()
    memory.forget_memory_settings(failed)
    forgotten: list[bool] = []
    monkeypatch.setattr(memory, "forget_secrets", lambda: forgotten.append(True))

    memory.forget_memory_settings(failed)

    assert forgotten == []


def test_password_rejected_finds_an_auth_error_in_the_cause_chain() -> None:
    connection = MemoryConnectionError("Authentication failed")
    connection.__cause__ = AuthError("unauthorized")
    error = RuntimeError("Failed to initialize session")
    error.__cause__ = connection
    assert memory.password_rejected(error)


def test_password_rejected_follows_an_implicit_context() -> None:
    error = RuntimeError("raised while handling the auth error")
    error.__context__ = AuthError("unauthorized")
    assert memory.password_rejected(error)


def test_other_connection_errors_are_not_a_rejected_password() -> None:
    error = MemoryConnectionError("Neo4j service unavailable")
    assert not memory.password_rejected(error)
