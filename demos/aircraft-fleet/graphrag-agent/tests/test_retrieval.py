"""Tests for the database-free parts of ``agent.retrieval``."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
from neo4j_graphrag.types import RetrieverResultItem

from agent import retrieval


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Is A320-200 EGT/N1 OK?", "is a320 200 egt n1 ok"),
        ('(NOT "hot") AND', "not hot and"),
        ("field:value ~fuzzy* [x TO y] {a} ^2 \\", "field value fuzzy x to y a 2"),
        ("?!-/", ""),
    ],
)
def test_fulltext_query_strips_lucene_syntax(text: str, expected: str) -> None:
    assert retrieval.fulltext_query(text) == expected


def test_format_hit_includes_provenance() -> None:
    item = RetrieverResultItem(
        content="Check EGT margin.",
        metadata={
            "score": 0.91234,
            "document_id": "AMM-A320-2024-001",
            "aircraft_type": "A320-200",
            "title": "A320 AMM",
            "chunk_index": 7,
            "entities": ["Fault: EGT Overtemp", "OperatingLimit: EGT - A320-200"],
        },
    )
    assert retrieval._format_hit(item) == (
        "[Source: AMM-A320-2024-001 | A320-200 | chunk 7 | score 0.912]\n"
        "Entities: Fault: EGT Overtemp, OperatingLimit: EGT - A320-200\n"
        "Check EGT margin."
    )


def test_format_hit_without_document_or_entities() -> None:
    item = RetrieverResultItem(
        content="Orphan chunk.",
        metadata={"score": None, "chunk_index": 0, "entities": []},
    )
    assert retrieval._format_hit(item) == (
        "[Source: unknown document | chunk 0]\nOrphan chunk."
    )


def test_vector_search_with_no_tokens_skips_the_database(monkeypatch) -> None:
    def fail() -> None:
        raise AssertionError("retriever must not be built")

    monkeypatch.setattr(retrieval, "_hybrid_retriever", fail)
    assert retrieval.vector_search("?!") == "No relevant document chunks found."


def test_schema_cache_honors_ttl(monkeypatch) -> None:
    clock = [1000.0]
    fetches: list[int] = []

    def fake_get_schema(driver: object, database: str) -> str:
        fetches.append(1)
        return f"schema v{len(fetches)}"

    monkeypatch.setattr(retrieval, "_schema_cache", None)
    monkeypatch.setattr(retrieval, "get_driver", object)
    monkeypatch.setattr(retrieval, "get_schema", fake_get_schema)
    monkeypatch.setattr(retrieval.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        retrieval, "settings", dataclasses.replace(retrieval.settings, schema_ttl_s=60)
    )

    assert retrieval.get_graph_schema() == "schema v1"
    clock[0] += 59
    assert retrieval.get_graph_schema() == "schema v1"
    clock[0] += 2
    assert retrieval.get_graph_schema() == "schema v2"
    assert len(fetches) == 2


def test_graph_query_passes_current_schema(monkeypatch) -> None:
    seen: dict = {}

    class FakeRetriever:
        def search(self, query_text: str, prompt_params: dict) -> SimpleNamespace:
            seen.update(query_text=query_text, prompt_params=dict(prompt_params))
            return SimpleNamespace(items=[SimpleNamespace(content="<Record n=42>")], metadata={})

    monkeypatch.setattr(retrieval, "_text2cypher_retriever", FakeRetriever)
    monkeypatch.setattr(retrieval, "get_graph_schema", lambda: "fresh schema")
    assert retrieval.graph_query("how many aircraft?") == "<Record n=42>"
    assert seen == {
        "query_text": "how many aircraft?",
        "prompt_params": {"schema": "fresh schema"},
    }


def test_graph_query_notes_truncation(monkeypatch) -> None:
    class FakeRetriever:
        def search(self, **_kwargs: object) -> SimpleNamespace:
            items = [SimpleNamespace(content=f"<Record n={i}>") for i in range(2)]
            return SimpleNamespace(items=items, metadata={"truncated": True})

    monkeypatch.setattr(retrieval, "_text2cypher_retriever", FakeRetriever)
    monkeypatch.setattr(retrieval, "get_graph_schema", lambda: "schema")
    out = retrieval.graph_query("list everything")
    assert out.startswith("<Record n=0>\n<Record n=1>\n")
    assert "first 2 rows" in out


def test_text2cypher_llm_caps_output_tokens(monkeypatch) -> None:
    captured: dict = {}

    def fake_llm(**kwargs):
        captured.update(kwargs)
        return "llm"

    monkeypatch.setattr(retrieval, "BedrockLLM", fake_llm)
    monkeypatch.setattr(retrieval, "BoundedText2CypherRetriever", lambda *a, **kw: kw)
    monkeypatch.setattr(retrieval, "get_driver", lambda: "driver")
    monkeypatch.setattr(retrieval, "get_graph_schema", lambda: "schema")
    retrieval._text2cypher_retriever.cache_clear()
    try:
        retrieval._text2cypher_retriever()
    finally:
        retrieval._text2cypher_retriever.cache_clear()
    assert captured["model_params"] == {
        "maxTokens": retrieval.settings.text2cypher_max_tokens
    }
