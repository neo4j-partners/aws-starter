"""Offline checks for the runtime entrypoint.

The session manager and the agent are replaced with fakes, so no test
reaches NAMS, Bedrock, or the Gateway.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import Mock, patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from starlette.exceptions import HTTPException
from starlette.testclient import TestClient

from server import runtime_app

REQUEST = runtime_app.InvocationRequest(prompt="q", user_id="analyst-1", session_id="s1")


class FakeAgent:
    """Streams fixed events, or raises after them."""

    def __init__(self, events: list[dict], error: Exception | None = None) -> None:
        self.events = events
        self.error = error
        self.cleaned = False

    async def stream_async(self, prompt: str):
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error

    def cleanup(self) -> None:
        self.cleaned = True


async def collect(stream) -> list[dict]:
    return [event async for event in stream]


class ParseRequestTests(unittest.TestCase):
    def test_missing_prompt_is_a_400(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            runtime_app._parse_request({"user_id": "analyst-1"})
        self.assertEqual(caught.exception.status_code, 400)

    def test_missing_user_id_is_a_400(self) -> None:
        for payload in ({"prompt": "q"}, {"prompt": "q", "user_id": " "}):
            with self.assertRaises(HTTPException) as caught:
                runtime_app._parse_request(payload)
            self.assertEqual(caught.exception.status_code, 400)

    def test_session_id_is_not_used_as_the_user(self) -> None:
        with self.assertRaises(HTTPException):
            runtime_app._parse_request({"prompt": "q", "session_id": "s1"})

    def test_actor_id_is_accepted(self) -> None:
        request = runtime_app._parse_request({"query": "q", "actor_id": "analyst-2"})
        self.assertEqual(request.user_id, "analyst-2")

    def test_ids_are_cleaned(self) -> None:
        request = runtime_app._parse_request(
            {"prompt": "q", "user_id": "a b\n1", "session_id": "case/42"}
        )
        self.assertEqual(request.user_id, "ab1")
        self.assertEqual(request.session_id, "case42")

    def test_new_session_id_when_none_sent(self) -> None:
        first = runtime_app._parse_request({"prompt": "q", "user_id": "u"})
        second = runtime_app._parse_request({"prompt": "q", "user_id": "u"})
        self.assertTrue(first.session_id.startswith("fraud-"))
        self.assertNotEqual(first.session_id, second.session_id)


class EntrypointTests(unittest.TestCase):
    def test_request_without_user_id_gets_http_400(self) -> None:
        with TestClient(runtime_app.app) as client:
            response = client.post("/invocations", json={"prompt": "q"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("user_id", response.json()["error"])


class RunAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[dict] = []
        self.memory = Mock()

    def run_with(self, agent: FakeAgent) -> None:
        """Run one turn. Events stay in self.events even when it raises."""

        async def run() -> None:
            async for event in runtime_app._run_agent(REQUEST):
                self.events.append(event)

        with (
            patch.object(runtime_app, "_session_manager", return_value=self.memory),
            patch.object(runtime_app, "_build_agent", return_value=agent),
        ):
            asyncio.run(run())

    def test_maps_chunks_and_each_tool_once(self) -> None:
        tool = {"toolUseId": "t1", "name": "read_cypher", "input": {}}
        agent = FakeAgent(
            [
                {"current_tool_use": tool},
                {"current_tool_use": tool},
                {"data": "Answer"},
            ]
        )
        self.run_with(agent)
        self.assertEqual(
            self.events,
            [
                {"type": "tool", "name": "read_cypher"},
                {"type": "chunk", "data": "Answer"},
                {"type": "complete"},
            ],
        )
        self.assertTrue(agent.cleaned)
        self.memory.close.assert_called_once()

    def test_error_propagates_after_release(self) -> None:
        agent = FakeAgent([{"data": "partial"}], error=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            self.run_with(agent)
        self.assertEqual(self.events, [{"type": "chunk", "data": "partial"}])
        self.assertTrue(agent.cleaned)
        self.memory.close.assert_called_once()

    def test_memory_closes_when_the_build_fails(self) -> None:
        with (
            patch.object(runtime_app, "_session_manager", return_value=self.memory),
            patch.object(runtime_app, "_build_agent", side_effect=RuntimeError("no gateway")),
            self.assertRaises(RuntimeError),
        ):
            asyncio.run(collect(runtime_app._run_agent(REQUEST)))
        self.memory.close.assert_called_once()


class SpanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        patcher = patch.object(runtime_app, "tracer", provider.get_tracer(__name__))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_stream(self, events: list[dict], error: Exception | None = None) -> None:
        async def fake_run_agent(request):
            for event in events:
                yield event
            if error is not None:
                raise error

        with patch.object(runtime_app, "_run_agent", fake_run_agent):
            asyncio.run(collect(runtime_app._stream(REQUEST)))

    def test_failure_marks_the_span_error(self) -> None:
        with self.assertRaises(RuntimeError):
            self.run_stream([{"type": "chunk", "data": "x"}], RuntimeError("boom"))
        (span,) = self.exporter.get_finished_spans()
        self.assertEqual(span.name, "fraud_memory_agent.invoke")
        self.assertEqual(span.status.status_code, StatusCode.ERROR)
        self.assertEqual(span.events[0].name, "exception")

    def test_success_leaves_the_span_unset(self) -> None:
        self.run_stream([{"type": "complete"}])
        (span,) = self.exporter.get_finished_spans()
        self.assertEqual(span.status.status_code, StatusCode.UNSET)
        self.assertEqual(span.attributes["session.id"], "s1")


if __name__ == "__main__":
    unittest.main()
