"""Offline checks for user-scoped NAMS recall and session reuse."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from neo4j_agent_memory.core.exceptions import TransportError
from neo4j_agent_memory.memory.short_term import Conversation

from server import memory_recall


def _conversation(session: str, day: int) -> Conversation:
    return Conversation(
        session_id=str(uuid4()),
        created_at=datetime(2026, 1, day, tzinfo=UTC),
        metadata={"client_session_id": session},
    )


def _message(role: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(role=SimpleNamespace(value=role), content=content)


def _memory(**short_term: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(short_term=SimpleNamespace(**short_term))


class SessionLookupTests(unittest.TestCase):
    def test_list_sorts_newest_first_and_find_session_picks_newest(self) -> None:
        old, new = _conversation("s1", 1), _conversation("s1", 5)
        other = _conversation("s2", 3)
        memory = _memory(list_conversations=AsyncMock(return_value=[old, other, new]))

        conversations = asyncio.run(memory_recall.list_user_conversations(memory, "u1"))

        memory.short_term.list_conversations.assert_awaited_once_with(
            user_identifier="u1", limit=memory_recall.MAX_CONVERSATIONS
        )
        self.assertEqual([c.id for c in conversations], [new.id, other.id, old.id])
        self.assertEqual(memory_recall.find_session(conversations, "s1"), new)
        self.assertIsNone(memory_recall.find_session(conversations, "missing"))

    def test_list_failure_returns_empty(self) -> None:
        memory = _memory(list_conversations=AsyncMock(side_effect=TransportError("x")))

        self.assertEqual(
            asyncio.run(memory_recall.list_user_conversations(memory, "u1")), []
        )


class RecallTests(unittest.TestCase):
    def test_recall_combines_session_context_and_earlier_hits(self) -> None:
        current, earlier = _conversation("s1", 5), _conversation("s0", 1)
        memory = _memory(
            get_context=AsyncMock(return_value="## Recent Messages\n[user] hi"),
            search_messages=AsyncMock(return_value=[_message("assistant", "ACC-9")]),
        )

        recalled = asyncio.run(
            memory_recall.recall_context(
                memory, "ACC-9?", [current, earlier], current=current
            )
        )

        self.assertIn("## This session so far\n## Recent Messages", recalled)
        self.assertIn("## Earlier sessions\n[assistant] ACC-9", recalled)
        # Only the other conversation is searched; the current one uses context.
        memory.short_term.search_messages.assert_awaited_once_with(
            "ACC-9?",
            session_id=str(earlier.id),
            limit=memory_recall.HITS_PER_CONVERSATION,
        )
        memory.short_term.get_context.assert_awaited_once_with(
            "ACC-9?", session_id=str(current.id)
        )

    def test_new_session_skips_session_context(self) -> None:
        earlier = _conversation("s0", 1)
        memory = _memory(
            get_context=AsyncMock(),
            search_messages=AsyncMock(return_value=[_message("user", "hello")]),
        )

        recalled = asyncio.run(
            memory_recall.recall_context(memory, "q", [earlier], current=None)
        )

        memory.short_term.get_context.assert_not_awaited()
        self.assertEqual(recalled, "## Earlier sessions\n[user] hello")

    def test_nams_failures_degrade_to_empty_recall(self) -> None:
        current, earlier = _conversation("s1", 5), _conversation("s0", 1)
        memory = _memory(
            get_context=AsyncMock(side_effect=TransportError("down")),
            search_messages=AsyncMock(side_effect=TransportError("down")),
        )

        recalled = asyncio.run(
            memory_recall.recall_context(
                memory, "q", [current, earlier], current=current
            )
        )

        self.assertEqual(recalled, "")

    def test_long_messages_and_total_are_clipped(self) -> None:
        conversations = [_conversation(f"s{i}", i + 1) for i in range(10)]
        memory = _memory(
            search_messages=AsyncMock(
                return_value=[_message("user", "x" * 5000)] * 3
            ),
        )

        recalled = asyncio.run(
            memory_recall.recall_context(memory, "q", conversations, current=None)
        )

        self.assertLessEqual(
            len(recalled), memory_recall.MAX_RECALL_CHARS + len("...")
        )
        self.assertNotIn("x" * (memory_recall.MAX_MESSAGE_CHARS + 10), recalled)


if __name__ == "__main__":
    unittest.main()
