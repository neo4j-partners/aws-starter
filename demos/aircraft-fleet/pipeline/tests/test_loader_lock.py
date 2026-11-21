"""A load holds a shared lock on the generate lock file for the whole load.

A generate publishes its CSVs one by one under an exclusive lock, so a load
that ran during the publish could read a mix of old and new files.
"""

from __future__ import annotations

import errno
import fcntl
import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

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


_needs_permissions = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")


@pytest.fixture
def read_only_dir(tmp_path: Path) -> Iterator[Path]:
    """A data dir that nobody can create files in, restored for cleanup."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    yield data_dir
    data_dir.chmod(0o755)


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
    results = []

    def generate_during_load(*args: object) -> int:
        cli_args = ["generate", "--aircraft", "2", "--days", "2", "--output", str(tmp_path)]
        results.append(CliRunner().invoke(generator_main.app, cli_args))
        return 0

    monkeypatch.setattr(loader, "load_nodes", generate_during_load)
    monkeypatch.setattr(loader, "load_relationships", lambda *args: None)

    loader.load_operational_graph(_Driver(), "db", tmp_path)

    assert [(r.exit_code, r.output) for r in results] == [
        (1, f"another generate or a load is running in {tmp_path}\n")
    ]


@_needs_permissions
def test_a_load_takes_the_lock_on_a_read_only_lock_file(
    read_only_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # flock works on a read-only file, so a load never needs write access.
    lock = read_only_dir / LOCK_NAME
    lock.touch()
    lock.chmod(0o444)
    read_only_dir.chmod(0o555)
    seen: list[bool] = []

    def load_nodes(*args: object) -> int:
        with lock.open("r") as other:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                seen.append(True)
            else:
                seen.append(False)
        return 0

    monkeypatch.setattr(loader, "load_nodes", load_nodes)
    monkeypatch.setattr(loader, "load_relationships", lambda *args: None)

    loader.load_operational_graph(_Driver(), "db", read_only_dir)

    assert seen == [True]


@_needs_permissions
def test_a_load_runs_without_the_lock_when_it_cannot_create_one(
    read_only_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # A generate cannot publish into this directory either, so it is safe.
    read_only_dir.chmod(0o555)
    ran: list[str] = []
    monkeypatch.setattr(loader, "load_nodes", lambda *args: ran.append("nodes") or 0)
    monkeypatch.setattr(loader, "load_relationships", lambda *args: None)

    with caplog.at_level(logging.WARNING, logger=loader.__name__):
        loader.load_operational_graph(_Driver(), "db", read_only_dir)

    assert ran == ["nodes"]
    assert not (read_only_dir / LOCK_NAME).exists()
    lock_warnings = [r.getMessage() for r in caplog.records if LOCK_NAME in r.getMessage()]
    assert lock_warnings == [
        f"[WARN] Cannot create {read_only_dir / LOCK_NAME}, so the load runs without "
        "the generate lock."
    ]


@pytest.mark.parametrize(
    ("code", "loads"), [(errno.EROFS, True), (errno.EACCES, True), (errno.ENOSPC, False)]
)
def test_only_a_read_only_directory_lets_a_load_skip_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, loads: bool
) -> None:
    real_open = Path.open

    def open_(self: Path, mode: str = "r", *args: object, **kwargs: object):
        if self.name == LOCK_NAME and mode == "a":
            raise OSError(code, os.strerror(code))
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_)
    monkeypatch.setattr(loader, "load_nodes", lambda *args: 0)
    monkeypatch.setattr(loader, "load_relationships", lambda *args: None)

    if loads:
        loader.load_operational_graph(_Driver(), "db", tmp_path)
    else:
        with pytest.raises(OSError) as raised:
            loader.load_operational_graph(_Driver(), "db", tmp_path)
        assert raised.value.errno == code
