"""Tests for the fleet UI server's Neo4j driver, built in ``ui/server.py``."""

import asyncio
import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import neo4j
import pytest
from neo4j import ManagedTransaction
from neo4j._sync.io._pool import IOPool
from neo4j._sync.work.session import Session

from fleet_supervisor.core.graph.retrieval import RotatingLoginAuthManager

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
    assert driver.kwargs == {
        "connection_timeout": 5,
        "connection_acquisition_timeout": 8,
        "max_transaction_retry_time": 10,
    }
    assert driver.closed


def test_the_ui_runs_without_a_driver_when_the_login_is_missing(
    ui_server: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the driver must not be built")

    monkeypatch.setenv("NEO4J_URI", "neo4j+s://fleet.example.test")
    monkeypatch.setattr(ui_server.GraphDatabase, "driver", fail)

    assert run_lifespan(ui_server).driver is None


def test_a_lookup_that_meets_a_rotated_password_retries_with_the_new_login(
    ui_server: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the real driver's retry loop, with the network calls stubbed out."""
    managers: list[RotatingLoginAuthManager] = []
    real_driver = ui_server.GraphDatabase.driver

    def recording_driver(uri: str, **kwargs: Any) -> neo4j.Driver:
        managers.append(kwargs["auth"])
        return real_driver(uri, **kwargs)

    passwords: list[str] = []
    delays: list[float] = []

    def open_transaction(session: Session, **_kwargs: Any) -> None:
        login = managers[0].get_auth()
        passwords.append(login.credentials)
        if login.credentials == "first-pw":
            # The secret was rotated before this lookup reached Neo4j.
            monkeypatch.setenv("NEO4J_PASSWORD", "rotated-pw")
            error = neo4j.exceptions.Neo4jError._hydrate_neo4j(
                code="Neo.ClientError.Security.Unauthorized", message="rejected"
            )
            # The pool asks the auth manager whether the error is retryable.
            IOPool.on_neo4j_error(
                None, error, SimpleNamespace(auth_manager=managers[0], auth=login)
            )
            raise error
        session._transaction = MagicMock(spec=ManagedTransaction)

    monkeypatch.setenv("NEO4J_URI", "neo4j://fleet.example.test")
    monkeypatch.setenv("NEO4J_USERNAME", "reader")
    monkeypatch.setenv("NEO4J_PASSWORD", "first-pw")
    monkeypatch.setattr(ui_server.GraphDatabase, "driver", recording_driver)
    monkeypatch.setattr(Session, "_open_transaction", open_transaction)
    monkeypatch.setattr("neo4j._sync.work.session.sleep", delays.append)

    graphs: list[dict[str, list[dict[str, Any]]]] = []
    run_lifespan(
        ui_server,
        lambda state: graphs.append(ui_server.load_evidence(state.driver, "neo4j", ["ME0042"])),
    )

    assert graphs == [{"nodes": [], "edges": []}]
    assert passwords == ["first-pw", "rotated-pw"]
    assert len(delays) == 1
