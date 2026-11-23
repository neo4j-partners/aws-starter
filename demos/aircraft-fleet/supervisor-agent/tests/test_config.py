"""Tests for the graph settings env parsing in ``core.config``."""

from __future__ import annotations

import pytest

from fleet_supervisor.core.config import GraphSettings


def test_defaults_when_unset() -> None:
    assert GraphSettings.from_env() == GraphSettings()


def test_empty_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    names = (
        "VECTOR_INDEX_NAME",
        "FULLTEXT_INDEX_NAME",
        "SCHEMA_TTL_S",
        "TEXT2CYPHER_TIMEOUT_S",
        "TEXT2CYPHER_MAX_ROWS",
        "TEXT2CYPHER_MAX_TOKENS",
        "EMBED_MODEL_ID",
        "EMBED_DIMENSIONS",
    )
    for name in names:
        monkeypatch.setenv(name, "")
    assert GraphSettings.from_env() == GraphSettings()


def test_values_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEMA_TTL_S", "60")
    monkeypatch.setenv("TEXT2CYPHER_TIMEOUT_S", "7.5")
    monkeypatch.setenv("VECTOR_INDEX_NAME", "otherIndex")
    settings = GraphSettings.from_env()
    assert settings.schema_ttl_s == 60
    assert settings.text2cypher_timeout_s == 7.5
    assert settings.vector_index_name == "otherIndex"


def test_text2cypher_max_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    assert GraphSettings.from_env().text2cypher_max_tokens == 2048
    monkeypatch.setenv("TEXT2CYPHER_MAX_TOKENS", "512")
    assert GraphSettings.from_env().text2cypher_max_tokens == 512


def test_bad_integer_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXT2CYPHER_MAX_ROWS", "lots")
    with pytest.raises(ValueError, match="TEXT2CYPHER_MAX_ROWS must be an integer, got 'lots'"):
        GraphSettings.from_env()


def test_bad_number_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXT2CYPHER_TIMEOUT_S", "soon")
    with pytest.raises(ValueError, match="TEXT2CYPHER_TIMEOUT_S must be a number, got 'soon'"):
        GraphSettings.from_env()


def test_bad_embed_dimensions_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_DIMENSIONS", "big")
    with pytest.raises(ValueError, match="EMBED_DIMENSIONS must be an integer"):
        GraphSettings.from_env()
