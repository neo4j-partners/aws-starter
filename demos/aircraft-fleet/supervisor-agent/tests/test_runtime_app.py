"""The AgentCore entrypoint, with the runtime and supervisor stubbed."""

import uuid
from types import SimpleNamespace

import pytest

from server import runtime_app
from tests.conftest import collect


class FakeSupervisor:
    def __init__(self, events: list[dict] | None = None, error: Exception | None = None):
        self.events = events or []
        self.error = error
        self.prompts: list[str] = []

    async def stream_async(self, prompt: str):
        self.prompts.append(prompt)
        for event in self.events:
            yield event
        if self.error:
            raise self.error


@pytest.fixture
def supervisor(monkeypatch):
    """Install a fake supervisor and a fake runtime; return the supervisor."""
    fake = FakeSupervisor(
        events=[
            {"current_tool_use": {"toolUseId": "t1", "name": "operations_specialist"}},
            {"data": "42 flights"},
        ]
    )

    async def fake_runtime():
        return SimpleNamespace(model=object(), tools=[])

    monkeypatch.setattr(runtime_app, "get_runtime", fake_runtime)
    monkeypatch.setattr(runtime_app, "build_supervisor", lambda model, tools: fake)
    return fake


def test_streams_agent_chunk_and_complete(supervisor):
    events = collect(
        runtime_app.invoke({"prompt": "How many flights?"}, SimpleNamespace(session_id="s1"))
    )
    assert events == [
        {"type": "agent", "name": "Operations Agent"},
        {"type": "chunk", "data": "42 flights"},
        {"type": "complete"},
    ]
    assert supervisor.prompts == ["How many flights?"]


@pytest.mark.parametrize("key", ["prompt", "message", "query", "inputText", "input"])
def test_accepts_common_prompt_keys(supervisor, key):
    collect(runtime_app.invoke({key: "hi"}, SimpleNamespace(session_id="s1")))
    assert supervisor.prompts == ["hi"]


def test_missing_prompt_is_an_error(supervisor):
    events = collect(runtime_app.invoke({}, SimpleNamespace(session_id="s1")))
    assert [e["type"] for e in events] == ["error"]
    assert supervisor.prompts == []


def test_failure_sends_generic_error(supervisor, caplog):
    supervisor.error = RuntimeError("secret connection string")
    events = collect(runtime_app.invoke({"prompt": "q"}, SimpleNamespace(session_id="s1")))
    assert events[-1] == {"type": "error", "error": runtime_app.GENERIC_ERROR}
    assert "secret connection string" not in str(events)
    assert "secret connection string" in caplog.text


def test_session_id_comes_from_context(supervisor, caplog):
    caplog.set_level("INFO")
    collect(runtime_app.invoke({"prompt": "q"}, SimpleNamespace(session_id="abc-123")))
    assert "session=abc-123" in caplog.text


def test_missing_session_id_gets_a_fresh_uuid(supervisor, caplog):
    caplog.set_level("INFO")
    collect(runtime_app.invoke({"prompt": "q"}, SimpleNamespace(session_id=None)))
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("Request "))
    session = line.split("session=")[1].split()[0]
    assert uuid.UUID(session)
    assert "default" not in line
