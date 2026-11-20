"""Tests for the memory settings and the per-request session manager.

Nothing here connects to Neo4j or Bedrock. A manager connects only when an
agent that owns it is built.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from neo4j_agent_memory import ExtractorType
from neo4j_agent_memory.llm.adapters.bedrock import (
    BedrockEmbeddingProvider,
    BedrockProvider,
)

from fleet_graphrag.agent import memory
from fleet_graphrag.agent.config import ConfigError


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    memory.memory_settings.cache_clear()
    yield
    memory.memory_settings.cache_clear()


@pytest.fixture
def mem_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_URI", "neo4j+s://memory.example.io")
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "local-only")


@pytest.mark.usefixtures("mem_env")
def test_settings_come_from_mem_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_USERNAME", "mem_user")
    monkeypatch.setenv("MEM_NEO4J_DATABASE", "memory")
    built = memory.memory_settings()
    assert built.backend == "bolt"
    assert built.neo4j.uri == "neo4j+s://memory.example.io"
    assert built.neo4j.username == "mem_user"
    assert built.neo4j.database == "memory"
    assert built.neo4j.password.get_secret_value() == "local-only"


@pytest.mark.usefixtures("mem_env")
def test_username_and_database_default_to_neo4j(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_USERNAME", "")
    built = memory.memory_settings()
    assert (built.neo4j.username, built.neo4j.database) == ("neo4j", "neo4j")


@pytest.mark.usefixtures("mem_env")
def test_extraction_and_embeddings_are_set_in_code() -> None:
    built = memory.memory_settings()
    assert isinstance(built.embedding, BedrockEmbeddingProvider)
    assert built.embedding.model == "bedrock/amazon.titan-embed-text-v2:0"
    assert built.embedding.dimensions == 1024
    assert isinstance(built.llm, BedrockProvider)
    assert built.llm.model == "bedrock/global.anthropic.claude-sonnet-4-6"
    assert built.extraction.extractor_type is ExtractorType.LLM


@pytest.mark.usefixtures("mem_env")
def test_hosted_backend_key_does_not_switch_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_API_KEY", "not-used")
    assert memory.memory_settings().backend == "bolt"


@pytest.mark.usefixtures("mem_env")
def test_settings_are_built_once() -> None:
    assert memory.memory_settings() is memory.memory_settings()


def test_missing_uri_is_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_PASSWORD", "local-only")
    with pytest.raises(ConfigError, match="MEM_NEO4J_URI is not set"):
        memory.memory_settings()


def test_missing_password_is_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM_NEO4J_URI", "neo4j+s://memory.example.io")
    with pytest.raises(ConfigError, match="MEM_NEO4J_PASSWORD_SECRET_ARN"):
        memory.memory_settings()


def test_secret_arn_wins_over_the_local_password(
    monkeypatch: pytest.MonkeyPatch, mem_env: None
) -> None:
    arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mem-AbCdEf"
    monkeypatch.setenv("MEM_NEO4J_PASSWORD_SECRET_ARN", arn)
    read: list[str] = []

    def fake_read(secret_arn: str, secret_arn_var: str) -> str:
        read.append(secret_arn_var)
        return "from-secret"

    monkeypatch.setattr("fleet_graphrag.agent.secrets._read_secret", fake_read)
    built = memory.memory_settings()
    assert built.neo4j.password.get_secret_value() == "from-secret"
    assert read == ["MEM_NEO4J_PASSWORD_SECRET_ARN"]


@pytest.mark.usefixtures("mem_env")
def test_session_manager_options() -> None:
    manager = memory.session_manager("s-1", "pilot-7")
    try:
        assert manager.session_id == "s-1"
        assert manager._user_id == "pilot-7"
        assert manager._retrieval_config.min_score == 0.75
        assert manager._extract_entities is True
        assert manager._record_tool_calls is False
    finally:
        manager.close()
