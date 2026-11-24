"""debug_extract_chunks splits a manual the way the pipeline does."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from neo4j_graphrag.components import entity_relation_extractor
from neo4j_graphrag.components.types import TextChunk

from populate_aircraft_db import pipeline

MANUALS_DIR = Path(__file__).resolve().parent.parent / "manuals"


@dataclass
class FakeLLM:
    supports_structured_output: bool = False


@dataclass
class FakeGraph:
    nodes: list[Any] = field(default_factory=list)
    relationships: list[Any] = field(default_factory=list)


class FakeExtractor:
    """Record the chunks it is asked to extract, with no model call."""

    chunks: list[TextChunk] = []

    def __init__(self, **kwargs: object) -> None:
        pass

    async def extract_for_chunk(self, schema: object, examples: str, chunk: TextChunk) -> FakeGraph:
        FakeExtractor.chunks.append(chunk)
        return FakeGraph()


@pytest.fixture
def extracted(monkeypatch: pytest.MonkeyPatch) -> list[TextChunk]:
    FakeExtractor.chunks = []
    monkeypatch.setattr(pipeline, "_create_extraction_llm", lambda **kwargs: FakeLLM())
    monkeypatch.setattr(entity_relation_extractor, "LLMEntityRelationExtractor", FakeExtractor)
    return FakeExtractor.chunks


def _debug_extract(chunk_indexes: list[int]) -> bool:
    return pipeline.debug_extract_chunks(
        MANUALS_DIR,
        filename="MAINTENANCE_A320.md",
        chunk_indexes=chunk_indexes,
        provider="bedrock",
        openai_api_key=None,
        region="us-east-1",
        llm_model="model",
        llm_max_tokens=1024,
        chunk_size=800,
        chunk_overlap=100,
    )


def test_selected_chunks_get_the_pipeline_chunk_ids_and_context(
    extracted: list[TextChunk],
) -> None:
    assert _debug_extract([0, 14]) is True

    assert [chunk.index for chunk in extracted] == [0, 14]
    assert [chunk.metadata["chunkId"] for chunk in extracted] == [
        "AMM-A320-2024-001:0",
        "AMM-A320-2024-001:14",
    ]
    assert all(
        chunk.text.startswith("[DOCUMENT CONTEXT] Aircraft Type: A320-200 | Title: ")
        for chunk in extracted
    )


def test_an_out_of_range_chunk_index_fails(extracted: list[TextChunk]) -> None:
    assert _debug_extract([10_000]) is False
    assert extracted == []
