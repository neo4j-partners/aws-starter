"""A load holds a shared lock on the generate lock file for the whole load.

A generate publishes its CSVs one by one under an exclusive lock, so a load
that ran during the publish could read a mix of old and new files.
"""

from __future__ import annotations

import fcntl
from pathlib import Path

import pytest

from generator import main as generator_main
from generator.stamp import LOCK_NAME
from populate_aircraft_db import loader


class _Driver:
    """A driver that records each query and runs nothing."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute_query(self, query: str, **kwargs: object) -> tuple[list, None, None]:
        self.queries.append(query)
        return [], None, None


def _try_exclusive(data_dir: Path) -> bool:
    """Return True if a second open file can take the lock exclusively."""
    with (data_dir / LOCK_NAME).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def test_a_load_fails_at_once_while_a_generate_runs(tmp_path: Path) -> None:
    driver = _Driver()
    with (tmp_path / LOCK_NAME).open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match=f"^a generate is running in {tmp_path}$"):
            loader.load_operational_graph(driver, "db", tmp_path)

    assert driver.queries == []


def test_the_lock_is_held_for_the_whole_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The lock file does not exist yet, so the load creates it.
    held: list[str] = []
    monkeypatch.setattr(
        loader,
        "load_nodes",
        lambda *args: held.append("nodes") if not _try_exclusive(tmp_path) else 0,
    )
    monkeypatch.setattr(
        loader,
        "load_relationships",
        lambda *args: held.append("relationships") if not _try_exclusive(tmp_path) else None,
    )

    loader.load_operational_graph(_Driver(), "db", tmp_path)

    assert held == ["nodes", "relationships"]
    assert _try_exclusive(tmp_path)


def test_a_generate_fails_at_once_while_a_load_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors: list[str] = []

    def generate_during_load(*args: object) -> int:
        try:
            generator_main.generate(aircraft=2, airports=40, days=2, seed=42, output=tmp_path)
        except RuntimeError as exc:
            errors.append(str(exc))
        return 0

    monkeypatch.setattr(loader, "load_nodes", generate_during_load)
    monkeypatch.setattr(loader, "load_relationships", lambda *args: None)

    loader.load_operational_graph(_Driver(), "db", tmp_path)

    assert errors == [f"another generate is running in {tmp_path}"]
