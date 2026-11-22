"""Tests for env parsing in ``agent.config``."""

from __future__ import annotations

import pytest

from fleet_graphrag.agent.config import (
    DEFAULT_EFFORT,
    DEFAULT_MAX_TOKENS,
    SYSTEM_PROMPT_TEMPLATE,
    Settings,
)


def test_defaults_when_unset() -> None:
    settings = Settings.from_env()
    assert settings.max_tokens == DEFAULT_MAX_TOKENS
    assert settings.effort == DEFAULT_EFFORT


def test_empty_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MAX_TOKENS", "MODEL_EFFORT", "SCHEMA_TTL_S", "TEXT2CYPHER_TIMEOUT_S"):
        monkeypatch.setenv(name, "")
    settings = Settings.from_env()
    assert settings.max_tokens == DEFAULT_MAX_TOKENS
    assert settings.effort == DEFAULT_EFFORT
    assert settings.schema_ttl_s == Settings().schema_ttl_s
    assert settings.text2cypher_timeout_s == Settings().text2cypher_timeout_s


def test_values_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TOKENS", "8000")
    monkeypatch.setenv("MODEL_EFFORT", "high")
    monkeypatch.setenv("TEXT2CYPHER_TIMEOUT_S", "7.5")
    settings = Settings.from_env()
    assert settings.max_tokens == 8000
    assert settings.effort == "high"
    assert settings.text2cypher_timeout_s == 7.5


def test_bad_integer_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TOKENS", "lots")
    with pytest.raises(ValueError, match="MAX_TOKENS must be an integer, got 'lots'"):
        Settings.from_env()


def test_bad_effort_lists_the_allowed_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_EFFORT", "extreme")
    with pytest.raises(ValueError, match="low, medium, high, xhigh, max"):
        Settings.from_env()


def test_text2cypher_max_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings.from_env().text2cypher_max_tokens == 2048
    monkeypatch.setenv("TEXT2CYPHER_MAX_TOKENS", "512")
    assert Settings.from_env().text2cypher_max_tokens == 512


def test_empty_strings_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    names = (
        "MODEL_ID",
        "AWS_REGION",
        "VECTOR_INDEX_NAME",
        "FULLTEXT_INDEX_NAME",
        "EMBED_MODEL_ID",
        "EMBED_DIMENSIONS",
    )
    for name in names:
        monkeypatch.setenv(name, "")
    assert Settings.from_env() == Settings()


def test_bad_embed_dimensions_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_DIMENSIONS", "big")
    with pytest.raises(ValueError, match="EMBED_DIMENSIONS must be an integer"):
        Settings.from_env()


def test_prompt_says_restored_history_has_no_tool_calls() -> None:
    """Memory restores message text only, so the agent must not read a missing call as none."""
    prompt = SYSTEM_PROMPT_TEMPLATE.format(schema="(schema)")
    assert "does not include tool calls or tool results" in prompt
    assert "does not mean no tool ran" in prompt
    assert "run the tool again" in prompt
