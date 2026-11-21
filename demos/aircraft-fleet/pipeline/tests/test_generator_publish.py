"""generate writes into a temp directory, then moves each file into the output.

A run that fails before the move leaves the previous output and its stamp
as they were. The move clears the old stamp first and writes the new one
last, so an output caught mid-move has no stamp and reads as stale.
"""

from __future__ import annotations

import errno
import fcntl
import os
import shutil
from pathlib import Path

import pytest

from generator import main as generator_main
from generator import stamp
from generator.config import GeneratorConfig
from populate_aircraft_db.loader import iter_csv_batches

ARGS = {"aircraft": 6, "airports": 40, "days": 2, "seed": 42}
MARKER = "edited by the test\n"


def _generate(output: Path, **overrides: int) -> None:
    generator_main.generate(**{**ARGS, **overrides}, output=output)


def _temp_dirs(output: Path) -> list[Path]:
    return [p for p in output.iterdir() if p.name.startswith(".generating-")]


def _interrupt_on_call(monkeypatch: pytest.MonkeyPatch, call: int) -> None:
    """Make the given os.replace call raise KeyboardInterrupt."""
    real = os.replace
    calls = [0]

    def replace(src: Path, dst: Path) -> None:
        calls[0] += 1
        if calls[0] == call:
            raise KeyboardInterrupt
        real(src, dst)

    monkeypatch.setattr(os, "replace", replace)


def test_generate_writes_exactly_the_known_outputs(tmp_path: Path) -> None:
    _generate(tmp_path)

    names = {p.name for p in tmp_path.iterdir()}
    assert names == generator_main.OUTPUT_FILES | {stamp.STAMP_NAME, ".generate.lock"}


def test_a_failed_run_leaves_the_previous_output_and_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _generate(tmp_path)
    (tmp_path / "nodes_aircraft.csv").write_text(MARKER)

    def fail(*args: object) -> None:
        raise RuntimeError("generator bug")

    monkeypatch.setattr(generator_main, "generate_removals", fail)
    with pytest.raises(RuntimeError, match="generator bug"):
        _generate(tmp_path, seed=7)

    config = GeneratorConfig(n_aircraft=6, n_airports=40, n_days=2, seed=42)
    assert stamp.read_stamp(tmp_path) == stamp.stamp_for(config)
    assert (tmp_path / "nodes_aircraft.csv").read_text() == MARKER
    assert _temp_dirs(tmp_path) == []


def test_an_interrupt_after_the_second_csv_leaves_no_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The new run has more aircraft, so the first file it moves differs.
    new = tmp_path / "new"
    _generate(new, aircraft=8)
    output = tmp_path / "out"
    _generate(output)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    _interrupt_on_call(monkeypatch, 3)

    with pytest.raises(KeyboardInterrupt):
        _generate(output, aircraft=8)

    assert stamp.read_stamp(output) is None
    moved, kept = sorted(generator_main.OUTPUT_FILES)[:2], sorted(generator_main.OUTPUT_FILES)[2:]
    assert (new / moved[0]).read_bytes() != before[moved[0]]
    for name in moved:
        assert (output / name).read_bytes() == (new / name).read_bytes(), name
    for name in kept:
        assert (output / name).read_bytes() == before[name], name
    assert _temp_dirs(output) == []


def _publish_setup(tmp_path: Path) -> tuple[Path, Path]:
    """An output with an old stamp, a known file the run skips, and a user file."""
    output = tmp_path / "out"
    work = output / ".generating-test"
    work.mkdir(parents=True)
    stamp.write_stamp(output, {"generator_hash": "old"})
    (output / "nodes_delays.csv").write_text("old delays\n")
    (output / "nodes_aircraft.csv").write_text("old aircraft\n")
    (output / "notes.txt").write_text("mine\n")
    (work / "nodes_aircraft.csv").write_text("new aircraft\n")
    stamp.write_stamp(work, {"generator_hash": "new"})
    return output, work


def test_publish_removes_known_outputs_the_run_did_not_write(tmp_path: Path) -> None:
    output, work = _publish_setup(tmp_path)

    generator_main._publish(work, output)

    assert not (output / "nodes_delays.csv").exists()
    assert (output / "nodes_aircraft.csv").read_text() == "new aircraft\n"
    assert (output / "notes.txt").read_text() == "mine\n"
    assert stamp.read_stamp(output) == {"generator_hash": "new"}


def test_publish_clears_the_stamp_and_stale_outputs_before_moving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, work = _publish_setup(tmp_path)
    _interrupt_on_call(monkeypatch, 1)

    with pytest.raises(KeyboardInterrupt):
        generator_main._publish(work, output)

    assert stamp.read_stamp(output) is None
    assert not (output / "nodes_delays.csv").exists()
    assert (output / "nodes_aircraft.csv").read_text() == "old aircraft\n"
    assert (output / "notes.txt").read_text() == "mine\n"


def test_publish_refuses_a_file_outside_the_known_outputs(tmp_path: Path) -> None:
    # A new CSV must join OUTPUT_FILES, or a later run could not remove it.
    output, work = _publish_setup(tmp_path)
    (work / "nodes_new.csv").write_text("new\n")

    with pytest.raises(ValueError, match="nodes_new.csv"):
        generator_main._publish(work, output)

    assert stamp.read_stamp(output) == {"generator_hash": "old"}


def test_generate_removes_temp_dirs_left_by_a_killed_run(tmp_path: Path) -> None:
    # A SIGKILL skips the cleanup, so the next run removes what it left.
    output = tmp_path / "out"
    orphan = output / ".generating-abc123"
    orphan.mkdir(parents=True)
    (orphan / "nodes_aircraft.csv").write_text("partial\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep\n")
    (output / ".generating-link").symlink_to(outside)
    (output / ".generating-file").write_text("a file, not a directory\n")
    (output / ".generatingX").mkdir()

    _generate(output)

    assert not orphan.exists()
    assert (output / ".generating-link").is_symlink()
    assert (outside / "keep.txt").read_text() == "keep\n"
    assert (output / ".generating-file").exists()
    assert (output / ".generatingX").is_dir()


def test_readers_ignore_a_temp_dir_decoy(tmp_path: Path) -> None:
    decoy = tmp_path / ".generating-x"
    decoy.mkdir()
    (decoy / "nodes_aircraft.csv").write_text(":ID(Aircraft)\nDECOY\n")
    stamp.write_stamp(decoy, {"generator_hash": "decoy"})
    (tmp_path / "nodes_aircraft.csv").write_text(":ID(Aircraft)\nAC1001\n")

    rows = [row for batch in iter_csv_batches(tmp_path, "nodes_aircraft.csv") for row in batch]

    assert rows == [{":ID(Aircraft)": "AC1001"}]
    assert stamp.read_stamp(tmp_path) is None
    assert "has no .stamp.json" in stamp.stale_reason(tmp_path)


def test_generate_fails_fast_while_another_generate_runs(tmp_path: Path) -> None:
    # The other run's temp dir is live, so the orphan sweep must not touch it.
    output = tmp_path / "out"
    live = output / ".generating-live"
    live.mkdir(parents=True)
    (live / "nodes_aircraft.csv").write_text("partial\n")

    with (output / ".generate.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match=f"^another generate is running in {output}$"):
            _generate(output)

    assert (live / "nodes_aircraft.csv").read_text() == "partial\n"
    assert stamp.read_stamp(output) is None


def test_generate_takes_the_lock_again_after_a_run(tmp_path: Path) -> None:
    _generate(tmp_path)
    _generate(tmp_path, seed=7)

    assert stamp.read_stamp(tmp_path)["config"]["seed"] == 7


def test_a_missing_work_dir_does_not_hide_the_real_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(work: Path, output: Path) -> None:
        shutil.rmtree(work)
        raise RuntimeError("publish failed")

    monkeypatch.setattr(generator_main, "_publish", fail)

    with pytest.raises(RuntimeError, match="publish failed"):
        _generate(tmp_path)


def test_publish_syncs_files_before_moving_and_the_stamp_after_the_csvs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A power loss must not leave a stamp on disk ahead of its CSVs.
    output, work = _publish_setup(tmp_path)
    (work / "nodes_systems.csv").write_text("new systems\n")
    events: list[tuple[str, str]] = []
    real_replace = os.replace
    monkeypatch.setattr(generator_main, "_fsync", lambda path: events.append(("fsync", path.name)))

    def replace(src: Path, dst: Path) -> None:
        events.append(("replace", Path(dst).name))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)

    generator_main._publish(work, output)

    moved = ["nodes_aircraft.csv", "nodes_systems.csv"]
    synced = {("fsync", name) for name in [*moved, stamp.STAMP_NAME]}
    assert set(events[:3]) == synced
    assert events[3:] == [
        *[("replace", name) for name in moved],
        ("fsync", "out"),
        ("replace", stamp.STAMP_NAME),
        ("fsync", "out"),
    ]


def _fail_dir_fsync(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    """Make _fsync raise OSError with the given errno on directories only."""
    real = generator_main._fsync

    def fsync(path: Path) -> None:
        if path.is_dir():
            raise OSError(code, os.strerror(code))
        real(path)

    monkeypatch.setattr(generator_main, "_fsync", fsync)


def test_publish_ignores_einval_from_a_directory_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Some filesystems reject fsync on a directory with EINVAL.
    output, work = _publish_setup(tmp_path)
    _fail_dir_fsync(monkeypatch, errno.EINVAL)

    generator_main._publish(work, output)

    assert stamp.read_stamp(output) == {"generator_hash": "new"}


@pytest.mark.parametrize("code", [errno.EIO, errno.EACCES])
def test_publish_raises_other_directory_fsync_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    output, work = _publish_setup(tmp_path)
    _fail_dir_fsync(monkeypatch, code)

    with pytest.raises(OSError) as raised:
        generator_main._publish(work, output)

    assert raised.value.errno == code


def test_publish_raises_einval_from_a_file_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the directory fsync may be skipped. A file that cannot be synced
    # must not be published as if it were on disk.
    output, work = _publish_setup(tmp_path)

    def fsync(path: Path) -> None:
        if path.is_file():
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))

    monkeypatch.setattr(generator_main, "_fsync", fsync)

    with pytest.raises(OSError) as raised:
        generator_main._publish(work, output)

    assert raised.value.errno == errno.EINVAL


def _record_syncs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record which sync call _fsync makes, without running it."""
    calls: list[str] = []
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append("fsync"))

    def fcntl_call(fd: int, cmd: int, *args: object) -> int:
        assert cmd == fcntl.F_FULLFSYNC
        calls.append("F_FULLFSYNC")
        return 0

    monkeypatch.setattr(fcntl, "fcntl", fcntl_call)
    return calls


def test_fsync_uses_full_fsync_where_the_platform_has_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On macOS, fsync leaves data in the drive's cache. F_FULLFSYNC flushes it.
    monkeypatch.setattr(fcntl, "F_FULLFSYNC", 51, raising=False)
    calls = _record_syncs(monkeypatch)

    generator_main._fsync(tmp_path)

    assert calls == ["F_FULLFSYNC"]


def test_fsync_falls_back_to_os_fsync_without_full_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(fcntl, "F_FULLFSYNC", raising=False)
    calls = _record_syncs(monkeypatch)

    generator_main._fsync(tmp_path)

    assert calls == ["fsync"]
