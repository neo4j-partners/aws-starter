"""Read side of NAMS memory: reuse a user's session and recall their history.

NAMS message search is scoped to one conversation and entity search is
workspace-wide with no user filter. To keep recall limited to one user, this
module reads only from the conversations that belong to that user
(``list_conversations(user_identifier=...)``) and never from workspace-wide
entity search.
"""

from __future__ import annotations

import asyncio
import logging

from neo4j_agent_memory import MemoryClient
from neo4j_agent_memory.core.exceptions import MemoryError as NamsError
from neo4j_agent_memory.memory.short_term import Conversation

logger = logging.getLogger(__name__)

MAX_CONVERSATIONS = 100
RECALLED_CONVERSATIONS = 10
HITS_PER_CONVERSATION = 3
MAX_MESSAGE_CHARS = 600
MAX_RECALL_CHARS = 4000


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}..."


async def list_user_conversations(
    memory: MemoryClient, user_id: str
) -> list[Conversation]:
    """Return the user's conversations, newest first. Empty if NAMS fails."""
    try:
        conversations = await memory.short_term.list_conversations(
            user_identifier=user_id, limit=MAX_CONVERSATIONS
        )
    except NamsError as error:
        logger.warning("NAMS conversation listing failed: %s", error)
        return []
    return sorted(
        conversations, key=lambda c: c.updated_at or c.created_at, reverse=True
    )


def find_session(
    conversations: list[Conversation], session_id: str
) -> Conversation | None:
    """Return the newest conversation tagged with this client session ID."""
    return next(
        (
            c
            for c in conversations
            if c.metadata.get("client_session_id") == session_id
        ),
        None,
    )


async def _session_text(
    memory: MemoryClient, conversation: Conversation, prompt: str
) -> str:
    try:
        return await memory.short_term.get_context(
            prompt, session_id=str(conversation.id)
        )
    except NamsError as error:
        logger.warning("NAMS session context failed: %s", error)
        return ""


async def _earlier_hits(
    memory: MemoryClient, conversation: Conversation, prompt: str
) -> list[str]:
    try:
        messages = await memory.short_term.search_messages(
            prompt, session_id=str(conversation.id), limit=HITS_PER_CONVERSATION
        )
    except NamsError as error:
        logger.warning("NAMS message search failed: %s", error)
        return []
    return [
        f"[{message.role.value}] {_clip(message.content, MAX_MESSAGE_CHARS)}"
        for message in messages
    ]


async def recall_context(
    memory: MemoryClient,
    prompt: str,
    conversations: list[Conversation],
    current: Conversation | None,
) -> str:
    """Build a recall block from this user's reused session and earlier sessions.

    ``current`` is the reused conversation, if any. Call this before the new
    user message is stored so the prompt is not echoed back as memory.
    """
    others = [c for c in conversations if current is None or c.id != current.id]
    async with asyncio.TaskGroup() as group:
        session_task = (
            group.create_task(_session_text(memory, current, prompt))
            if current
            else None
        )
        hit_tasks = [
            group.create_task(_earlier_hits(memory, conversation, prompt))
            for conversation in others[:RECALLED_CONVERSATIONS]
        ]

    parts: list[str] = []
    if session_task and (session := session_task.result()):
        parts.append(f"## This session so far\n{session}")
    if hits := [hit for task in hit_tasks for hit in task.result()]:
        parts.append("## Earlier sessions\n" + "\n".join(hits))
    return _clip("\n\n".join(parts), MAX_RECALL_CHARS)
