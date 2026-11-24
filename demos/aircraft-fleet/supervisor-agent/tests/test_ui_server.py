"""Tests for the fleet UI server's Neo4j driver, built in ``ui/server.py``."""

import asyncio
import copy
import importlib.util
import json
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import uuid4

import neo4j
import pytest

from fleet_supervisor.core.graph.retrieval import RotatingLoginAuthManager
from tests.fake_bolt import FakeNeo4j

UI_DIR = Path(__file__).resolve().parents[2] / "ui"


class FakeDriver:
    """Records the arguments it was built with and whether it was closed."""

    def __init__(self, uri: str, **kwargs: Any) -> None:
        self.uri = uri
        self.kwargs = kwargs
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def ui_server(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load ``ui/server.py``, which imports ``evidence`` from its own folder."""
    monkeypatch.syspath_prepend(str(UI_DIR))
    spec = importlib.util.spec_from_file_location("fleet_ui_server", UI_DIR / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_lifespan(
    ui_server: ModuleType, during: Callable[[SimpleNamespace], None] | None = None
) -> SimpleNamespace:
    """Start and stop the UI's lifespan, returning the app state it set.

    ``during`` runs with the app state while the driver is still open.
    """
    app = SimpleNamespace(state=SimpleNamespace())

    async def start_and_stop() -> None:
        async with ui_server.lifespan(app):
            if during is not None:
                during(app.state)

    asyncio.run(start_and_stop())
    return app.state


def test_the_ui_driver_uses_the_rotating_login(
    ui_server: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[FakeDriver] = []

    def fake_driver(uri: str, **kwargs: Any) -> FakeDriver:
        built.append(FakeDriver(uri, **kwargs))
        return built[-1]

    monkeypatch.setenv("NEO4J_URI", "neo4j+s://fleet.example.test")
    monkeypatch.setenv("NEO4J_USERNAME", "reader")
    monkeypatch.setenv("NEO4J_PASSWORD", "first-pw")
    monkeypatch.setattr(ui_server.GraphDatabase, "driver", fake_driver)

    state = run_lifespan(ui_server)

    assert len(built) == 1
    driver = built[0]
    assert state.driver is driver
    assert driver.uri == "neo4j+s://fleet.example.test"
    auth = driver.kwargs.pop("auth")
    assert isinstance(auth, RotatingLoginAuthManager)
    assert auth.get_auth() == neo4j.basic_auth("reader", "first-pw")
    assert state.auth is auth
    assert driver.kwargs == {
        "connection_timeout": 5,
        "connection_acquisition_timeout": 8,
        "max_transaction_retry_time": 0,
    }
    assert driver.closed


def test_the_ui_runs_without_a_driver_when_the_login_is_missing(
    ui_server: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the driver must not be built")

    monkeypatch.setenv("NEO4J_URI", "neo4j+s://fleet.example.test")
    monkeypatch.setattr(ui_server.GraphDatabase, "driver", fail)

    state = run_lifespan(ui_server)
    assert state.driver is None
    assert state.auth is None


EVIDENCE_TURN = [
    {"type": "tool_complete", "tool": "search_maintenance", "evidence_ids": ["ME0042"]},
    {"type": "complete", "response": "Done."},
]


def relay_frames(ui_server: ModuleType, state: SimpleNamespace) -> list[dict[str, Any]]:
    turn = ui_server.ChatRequest(prompt="Find hydraulic issues", session_id=uuid4())
    frames = ui_server.relay(turn, state.driver, state.auth)
    return [json.loads(frame.removeprefix("data: ")) for frame in frames]


@pytest.fixture
def ui_on_fake_neo4j(
    ui_server: ModuleType, fake_neo4j: FakeNeo4j, monkeypatch: pytest.MonkeyPatch
) -> FakeNeo4j:
    """Point the UI at the fake server with a login it rejects, and stub the supervisor."""
    monkeypatch.setenv("NEO4J_URI", fake_neo4j.uri)
    monkeypatch.setenv("NEO4J_USERNAME", "reader")
    monkeypatch.setenv("NEO4J_PASSWORD", "first-pw")
    monkeypatch.setattr(ui_server, "supervisor_stream", lambda _turn: nullcontext([]))
    monkeypatch.setattr(
        ui_server, "iter_events", lambda _chunks: iter(copy.deepcopy(EVIDENCE_TURN))
    )
    return fake_neo4j


def test_a_lookup_that_meets_a_rotated_password_recovers_in_the_same_turn(
    ui_server: ModuleType, ui_on_fake_neo4j: FakeNeo4j, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real driver opens a new connection, and Neo4j rejects its LOGON."""
    frames: list[list[dict[str, Any]]] = []

    def rotate_then_relay(state: SimpleNamespace) -> None:
        # The secret was rotated after the UI started.
        monkeypatch.setenv("NEO4J_PASSWORD", "rotated-pw")
        frames.append(relay_frames(ui_server, state))

    run_lifespan(ui_server, rotate_then_relay)

    assert frames == [
        [
            {
                "type": "tool_complete",
                "tool": "search_maintenance",
                "graph": {"nodes": [], "edges": []},
            },
            {"type": "complete", "response": "Done."},
        ]
    ]
    assert ui_on_fake_neo4j.logins == ["first-pw", "rotated-pw"]


def test_a_lookup_with_a_password_still_wrong_marks_the_graph_unavailable(
    ui_server: ModuleType, ui_on_fake_neo4j: FakeNeo4j
) -> None:
    frames: list[list[dict[str, Any]]] = []

    run_lifespan(ui_server, lambda state: frames.append(relay_frames(ui_server, state)))

    assert frames == [
        [
            {"type": "tool_complete", "tool": "search_maintenance", "graph_unavailable": True},
            {"type": "complete", "response": "Done."},
        ]
    ]
    assert ui_on_fake_neo4j.logins == ["first-pw"]


def static_login(monkeypatch: pytest.MonkeyPatch) -> RotatingLoginAuthManager:
    monkeypatch.setenv("NEO4J_USERNAME", "reader")
    monkeypatch.setenv("NEO4J_PASSWORD", "first-pw")
    return RotatingLoginAuthManager()


def test_a_failed_secret_read_marks_the_graph_unavailable(
    ui_server: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        {"type": "tool_complete", "tool": "search_maintenance", "evidence_ids": ["ME0042"]},
        {"type": "complete", "response": "Done."},
    ]

    def fail(*_args: object) -> None:
        raise ui_server.ConfigError("Could not read the Neo4j secret.")

    monkeypatch.setattr(ui_server, "supervisor_stream", lambda _turn: nullcontext([]))
    monkeypatch.setattr(ui_server, "iter_events", lambda _chunks: iter(events))
    monkeypatch.setattr(ui_server, "load_evidence", fail)
    turn = ui_server.ChatRequest(prompt="Find hydraulic issues", session_id=uuid4())

    frames = list(ui_server.relay(turn, driver=object(), auth=static_login(monkeypatch)))

    assert [json.loads(frame.removeprefix("data: ")) for frame in frames] == [
        {"type": "tool_complete", "tool": "search_maintenance", "graph_unavailable": True},
        {"type": "complete", "response": "Done."},
    ]


class NodeWithoutId:
    """An Aircraft node that has no ``aircraft_id`` property."""

    labels = frozenset({"Aircraft"})

    def __getitem__(self, key: str) -> Any:
        raise KeyError(key)

    def get(self, _key: str) -> None:
        return None


class OneNodeDriver:
    """Returns one path that holds only ``NodeWithoutId``."""

    def execute_query(self, *_args: object, **_kwargs: object) -> tuple[list, None, None]:
        path = SimpleNamespace(nodes=[NodeWithoutId()], relationships=[])
        return [{"path": path}], None, None


def test_a_node_with_no_id_marks_the_graph_unavailable_and_keeps_streaming(
    ui_server: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        {"type": "tool_complete", "tool": "search_maintenance", "evidence_ids": ["N12345"]},
        {"type": "chunk", "data": "Two aircraft."},
        {"type": "complete", "response": "Two aircraft."},
    ]
    monkeypatch.setattr(ui_server, "supervisor_stream", lambda _turn: nullcontext([]))
    monkeypatch.setattr(ui_server, "iter_events", lambda _chunks: iter(events))
    turn = ui_server.ChatRequest(prompt="Find hydraulic issues", session_id=uuid4())

    frames = list(ui_server.relay(turn, driver=OneNodeDriver(), auth=static_login(monkeypatch)))

    assert [json.loads(frame.removeprefix("data: ")) for frame in frames] == [
        {"type": "tool_complete", "tool": "search_maintenance", "graph_unavailable": True},
        {"type": "chunk", "data": "Two aircraft."},
        {"type": "complete", "response": "Two aircraft."},
    ]
