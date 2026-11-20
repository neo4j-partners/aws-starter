"""The Text2Cypher retriever must refuse to run write queries.

neo4j-graphrag runs ``EXPLAIN`` with READ routing first and rejects any plan
whose query type is not read-only. This test pins that behavior so a library
upgrade that drops it fails here.
"""

from __future__ import annotations

from types import SimpleNamespace

import neo4j
import pytest
from neo4j_graphrag.exceptions import Text2CypherRetrievalError
from neo4j_graphrag.llm import LLMResponse
from neo4j_graphrag.retrievers import Text2CypherRetriever


class FakeLLM:
    def __init__(self, cypher: str) -> None:
        self.cypher = cypher

    def invoke(self, *_args: object, **_kwargs: object) -> LLMResponse:
        return LLMResponse(content=self.cypher)


def _retriever(monkeypatch, cypher: str, query_type: str) -> tuple[Text2CypherRetriever, list]:
    driver = neo4j.GraphDatabase.driver("bolt://localhost:1", auth=("u", "p"))
    calls: list[tuple[str, object]] = []

    def fake_execute_query(query_: str, **kwargs: object):
        if query_ == "CALL dbms.components()":
            # Version probe the retriever runs once at construction.
            return [{"versions": ["2026.10.0"], "edition": "enterprise"}], None, []
        calls.append((query_, kwargs.get("routing_")))
        return [], SimpleNamespace(query_type=query_type), []

    monkeypatch.setattr(driver, "execute_query", fake_execute_query)
    monkeypatch.setattr(driver, "verify_connectivity", lambda: None)
    retriever = Text2CypherRetriever(driver, llm=FakeLLM(cypher), neo4j_schema="(:Aircraft)")
    return retriever, calls


def test_write_query_is_refused(monkeypatch) -> None:
    retriever, calls = _retriever(monkeypatch, "MATCH (a:Aircraft) DETACH DELETE a", "w")
    with pytest.raises(Text2CypherRetrievalError, match="non-read-only"):
        retriever.search(query_text="delete every aircraft")
    assert calls == [("EXPLAIN MATCH (a:Aircraft) DETACH DELETE a", neo4j.RoutingControl.READ)]


def test_read_query_runs_with_read_routing(monkeypatch) -> None:
    retriever, calls = _retriever(monkeypatch, "MATCH (a:Aircraft) RETURN count(a)", "r")
    retriever.search(query_text="how many aircraft")
    assert [routing for _, routing in calls] == [neo4j.RoutingControl.READ] * 2
    assert calls[1][0] == "MATCH (a:Aircraft) RETURN count(a)"
