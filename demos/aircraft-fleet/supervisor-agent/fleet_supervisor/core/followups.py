"""Suggest follow-up questions for a finished answer.

One small structured model call sees the question and the final answer, and
nothing else. It runs on the model directly, with no agent, tools, or session
manager, so it never reads or writes memory and its questions are never stored.

A failed or slow call is logged and returns no questions. The answer has
already streamed by then, so it stays intact.
"""

import asyncio
import logging
from collections.abc import Callable
from contextlib import aclosing
from functools import cache

from botocore.config import Config as BotocoreConfig
from pydantic import BaseModel, Field
from strands.models import BedrockModel
from strands.models.model import Model
from strands.types.content import Messages

from fleet_supervisor.core.config import AWS_REGION, FOLLOWUP_MODEL_ID, FOLLOWUP_TIMEOUT_S

logger = logging.getLogger(__name__)

FOLLOWUP_COUNT = 3
MAX_QUESTION_CHARS = 200
# The call needs the gist of the answer, not all of it. The cap bounds its
# input tokens and so its latency.
MAX_ANSWER_CHARS = 6000
FOLLOWUP_MAX_TOKENS = 400

SYSTEM_PROMPT = f"""\
You suggest follow-up questions for an aircraft fleet assistant. The assistant \
answers from a graph of aircraft, systems, components, sensors, maintenance \
events, flights, delays, and airports, and from the aircraft maintenance manuals.

Read the user's question and the assistant's answer. Suggest {FOLLOWUP_COUNT} \
short questions the user could ask next to dig deeper into that answer. Each \
question must stand on its own, name the aircraft, system, or fault it is about, \
and be answerable from the fleet data or the manuals. Keep each under 120 \
characters. Do not repeat the user's question."""


class FollowUps(BaseModel):
    """Questions the user could ask next."""

    questions: list[str] = Field(
        description=f"{FOLLOWUP_COUNT} short follow-up questions, each under 120 characters."
    )


@cache
def followup_model() -> BedrockModel:
    """Return the process-wide follow-up model, built on first use.

    The call is not streamed, and botocore gets the same bound as the caller.
    So a call the caller has given up on also ends its worker thread, with no
    retry.
    """
    return BedrockModel(
        model_id=FOLLOWUP_MODEL_ID,
        region_name=AWS_REGION,
        max_tokens=FOLLOWUP_MAX_TOKENS,
        streaming=False,
        boto_client_config=BotocoreConfig(
            connect_timeout=FOLLOWUP_TIMEOUT_S,
            read_timeout=FOLLOWUP_TIMEOUT_S,
            retries={"total_max_attempts": 1},
        ),
    )


def clean_questions(questions: list[str], asked: str) -> list[str]:
    """Trim the questions, and drop blanks, repeats, and the question already asked."""
    seen = {asked.strip().casefold()}
    kept: list[str] = []
    for question in questions:
        text = " ".join(question.split())[:MAX_QUESTION_CHARS]
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            kept.append(text)
    return kept[:FOLLOWUP_COUNT]


async def suggest_followups(
    question: str,
    answer: str,
    *,
    model_factory: Callable[[], Model] = followup_model,
    timeout_s: float = FOLLOWUP_TIMEOUT_S,
) -> list[str]:
    """Return up to three follow-up questions, or none if the call fails or runs slow."""
    content = (
        f"<question>\n{question}\n</question>\n\n<answer>\n{answer[:MAX_ANSWER_CHARS]}\n</answer>"
    )
    messages: Messages = [{"role": "user", "content": [{"text": content}]}]
    output: FollowUps | None = None
    try:
        async with asyncio.timeout(timeout_s):
            model = await asyncio.to_thread(model_factory)
            events = model.structured_output(FollowUps, messages, system_prompt=SYSTEM_PROMPT)
            async with aclosing(events):
                async for event in events:
                    output = event.get("output", output)
    except TimeoutError:
        logger.warning("Follow-up questions timed out after %.1f s", timeout_s)
        return []
    except Exception:
        # Any failure, such as a throttled call or a reply that fails the
        # schema, costs only the links. The answer has already streamed.
        logger.warning("Follow-up questions failed", exc_info=True)
        return []
    if output is None:
        logger.warning("Follow-up questions returned no output")
        return []
    return clean_questions(output.questions, question)
