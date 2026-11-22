"""EffortAnthropicLLM text extraction and miss counting, with stubbed replies."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from populate_aircraft_db.anthropic_effort import _MISS_PREFIX, EffortAnthropicLLM

# The Anthropic client comes from the optional `anthropic` extra.
pytest.importorskip("anthropic")


def _reply(stop_reason: str, *blocks: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


def _thinking() -> SimpleNamespace:
    return SimpleNamespace(type="thinking", thinking="...")


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> EffortAnthropicLLM:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return EffortAnthropicLLM(model_name="claude-sonnet-5-5", effort="low", api_key="test")


def test_text_after_thinking_is_returned(llm: EffortAnthropicLLM) -> None:
    reply = _reply("end_turn", _thinking(), _text('{"nodes": []}'))
    assert llm._extract_text(reply) == '{"nodes": []}'
    assert llm.miss_count == 0


@pytest.mark.parametrize(
    "reply",
    [
        _reply("max_tokens", _thinking(), _text('{"nodes": [')),
        _reply("max_tokens", _thinking()),
        _reply("end_turn", _thinking()),
    ],
    ids=["truncated-text", "max-tokens-no-text", "no-text"],
)
def test_miss_is_counted(llm: EffortAnthropicLLM, reply: SimpleNamespace) -> None:
    assert llm._extract_text(reply).startswith(_MISS_PREFIX)
    assert llm.miss_count == 1
