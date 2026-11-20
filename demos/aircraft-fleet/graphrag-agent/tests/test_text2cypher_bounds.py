"""Bounds on generated Cypher: query timeout, row cap, and the upstream contract.

``BoundedText2CypherRetriever.get_search_results`` is copied from
neo4j-graphrag. The signature test fails when upstream changes that method,
which is the signal to re-copy it.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import neo4j
from neo4j_graphrag.llm import LLMResponse
from neo4j_graphrag.retrievers import Text2CypherRetriever

from agent.text2cypher import BoundedText2CypherRetriever


class FakeLLM:
    def invoke(self, *_args: object, **_kwargs: object) -> LLMResponse:
        return LLMResponse(content="MATCH (a:Aircraft) RETURN a.tail_number AS tail")


class FakeResult:
    def __init__(self, n: int) -> None:
        self.rows = [neo4j.Record({"tail": f"N{i}"}) for i in range(n)]

    def fetch(self, n: int) -> list[neo4j.Record]:
        return self.rows[:n]


def _retriever(monkeypatch, rows: int, max_rows: int = 3):
    driver = neo4j.GraphDatabase.driver("bolt://localhost:1", auth=("u", "p"))
    calls: list[dict] = []

    def fake_execute_query(query_, **kwargs):
        if query_ == "CALL dbms.components()":
            return [{"versions": ["2026.10.0"], "edition": "enterprise"}], None, []
        calls.append({"query": query_, **kwargs})
        if query_.text.startswith("EXPLAIN"):
            return [], SimpleNamespace(query_type="r"), []
        return kwargs["result_transformer_"](FakeResult(rows))

    monkeypatch.setattr(driver, "execute_query", fake_execute_query)
    retriever = BoundedText2CypherRetriever(
        driver, llm=FakeLLM(), neo4j_schema="(:Aircraft)", timeout_s=7.5, max_rows=max_rows
    )
    return retriever, calls


def test_upstream_signature_unchanged() -> None:
    upstream = inspect.signature(Text2CypherRetriever.get_search_results)
    assert list(upstream.parameters) == ["self", "query_text", "prompt_params"]
    ours = inspect.signature(BoundedText2CypherRetriever.get_search_results)
    assert list(ours.parameters) == list(upstream.parameters)


def test_explain_and_query_both_carry_the_timeout(monkeypatch) -> None:
    retriever, calls = _retriever(monkeypatch, rows=1)
    retriever.search(query_text="list tails")
    assert [c["query"].timeout for c in calls] == [7.5, 7.5]
    assert all(c["routing_"] is neo4j.RoutingControl.READ for c in calls)


def test_rows_over_the_cap_are_truncated(monkeypatch) -> None:
    retriever, _ = _retriever(monkeypatch, rows=10)
    result = retriever.search(query_text="list tails")
    assert len(result.items) == 3
    assert result.metadata["truncated"] is True


def test_rows_at_the_cap_are_not_truncated(monkeypatch) -> None:
    retriever, _ = _retriever(monkeypatch, rows=3)
    result = retriever.search(query_text="list tails")
    assert len(result.items) == 3
    assert result.metadata["truncated"] is False


def test_schema_prompt_param_is_used(monkeypatch) -> None:
    retriever, _ = _retriever(monkeypatch, rows=1)
    seen: list[str] = []
    monkeypatch.setattr(
        retriever.llm, "invoke", lambda prompt, *a, **k: seen.append(prompt) or FakeLLM().invoke()
    )
    retriever.search(query_text="q", prompt_params={"schema": "FRESH-SCHEMA"})
    assert "FRESH-SCHEMA" in seen[0]
