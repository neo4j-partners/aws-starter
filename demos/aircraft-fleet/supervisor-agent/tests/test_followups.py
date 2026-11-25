"""Tests for the follow-up question call in ``fleet_supervisor.core.followups``."""

import asyncio
import logging
import time
from typing import Any

import pytest
from botocore.exceptions import ClientError

from fleet_supervisor.core import followups
from fleet_supervisor.core.followups import FollowUps, clean_questions, suggest_followups

QUESTION = "Find aircraft with hydraulic system issues."
ANSWER = "N12345 had a hydraulic leak, event ME0012."


class FakeModel:
    """Stands in for ``BedrockModel.structured_output`` and records each call."""

    def __init__(self, questions: list[str] | None = None, error: Exception | None = None) -> None:
        self.questions = questions or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def structured_output(
        self, output_model: type[FollowUps], prompt: list[dict[str, Any]], system_prompt: str
    ):
        self.calls.append(
            {"output_model": output_model, "prompt": prompt, "system_prompt": system_prompt}
        )
        yield {"contentBlockDelta": {}}
        if self.error is not None:
            raise self.error
        yield {"output": output_model(questions=self.questions)}


class SlowModel:
    async def structured_output(self, *_args: Any, **_kwargs: Any):
        await asyncio.sleep(10)
        yield {"output": FollowUps(questions=["Too late?"])}


class SilentModel:
    async def structured_output(self, *_args: Any, **_kwargs: Any):
        yield {"contentBlockDelta": {}}


def suggest(model: Any, **kwargs: Any) -> list[str]:
    return asyncio.run(suggest_followups(QUESTION, ANSWER, model_factory=lambda: model, **kwargs))


def test_the_call_returns_the_questions_and_sees_only_the_question_and_answer() -> None:
    model = FakeModel(["Which systems failed on N12345?", "What fixed ME0012?", "Any repeats?"])

    questions = suggest(model)

    assert questions == ["Which systems failed on N12345?", "What fixed ME0012?", "Any repeats?"]
    [call] = model.calls
    assert call["output_model"] is FollowUps
    assert call["system_prompt"] == followups.SYSTEM_PROMPT
    [message] = call["prompt"]
    assert message["role"] == "user"
    assert message["content"] == [
        {"text": f"<question>\n{QUESTION}\n</question>\n\n<answer>\n{ANSWER}\n</answer>"}
    ]


def test_a_long_answer_is_cut_before_the_call() -> None:
    model = FakeModel(["Next?"])

    asyncio.run(suggest_followups(QUESTION, "x" * 50_000, model_factory=lambda: model, timeout_s=5))

    text = model.calls[0]["prompt"][0]["content"][0]["text"]
    assert text.count("x") == followups.MAX_ANSWER_CHARS


@pytest.mark.parametrize(
    "error",
    [
        ClientError({"Error": {"Code": "ThrottlingException"}}, "Converse"),
        ValueError('Model returned stop_reason: max_tokens instead of "tool_use".'),
    ],
    ids=["throttled", "bad-reply"],
)
def test_a_failed_call_returns_no_questions_and_logs(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=followups.__name__):
        assert suggest(FakeModel(error=error)) == []

    assert "Follow-up questions failed" in caplog.text


def test_a_model_that_cannot_be_built_returns_no_questions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken_factory() -> Any:
        raise ValueError("no region")

    with caplog.at_level(logging.WARNING, logger=followups.__name__):
        questions = asyncio.run(suggest_followups(QUESTION, ANSWER, model_factory=broken_factory))

    assert questions == []
    assert "Follow-up questions failed" in caplog.text


def test_a_slow_call_is_abandoned_at_the_timeout(caplog: pytest.LogCaptureFixture) -> None:
    started = time.monotonic()

    with caplog.at_level(logging.WARNING, logger=followups.__name__):
        questions = suggest(SlowModel(), timeout_s=0.2)

    assert questions == []
    assert time.monotonic() - started < 2
    assert "timed out after 0.2 s" in caplog.text


def test_a_call_with_no_output_returns_no_questions(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=followups.__name__):
        assert suggest(SilentModel()) == []

    assert "returned no output" in caplog.text


def test_the_questions_are_trimmed_deduplicated_and_capped() -> None:
    questions = [
        "  Which   tails\nflew? ",
        "",
        "which tails flew?",
        QUESTION.upper(),
        "y" * 500,
        "Third?",
        "Fourth?",
    ]

    assert clean_questions(questions, QUESTION) == [
        "Which tails flew?",
        "y" * followups.MAX_QUESTION_CHARS,
        "Third?",
    ]


def test_the_follow_up_model_is_haiku_with_a_bounded_unstreamed_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    followups.followup_model.cache_clear()
    try:
        model = followups.followup_model()
    finally:
        followups.followup_model.cache_clear()

    assert model.config["model_id"] == "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert model.config["streaming"] is False
    assert model.config["max_tokens"] == followups.FOLLOWUP_MAX_TOKENS
    client_config = model.client.meta.config
    assert client_config.read_timeout == followups.FOLLOWUP_TIMEOUT_S
    assert client_config.connect_timeout == followups.FOLLOWUP_TIMEOUT_S
    assert client_config.retries["total_max_attempts"] == 1
