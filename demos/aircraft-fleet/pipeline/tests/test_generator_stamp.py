"""generated/.stamp.json records the config and generator code behind the CSVs."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from contextlib import nullcontext
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from generator import main as generator_main
from generator import stamp
from generator.config import GeneratorConfig
from populate_aircraft_db import main as loader_main

ARGS = {"aircraft": 6, "airports": 40, "days": 2, "seed": 42}
MARKER = "edited by the test\n"


def _generate(output: Path, *, if_stale: bool = False, **overrides: int) -> None:
    generator_main.generate(**{**ARGS, **overrides}, output=output, if_stale=if_stale)


def _fake_verify(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, *, graph_reason: str | None
) -> list[bool]:
    """Stand in for Neo4j in the verify command. Returns a list that records each verify run."""
    settings = SimpleNamespace(neo4j_uri="bolt://example", neo4j_database="db", data_dir=data_dir)
    verified: list[bool] = []

    def fake_verify(*args: object, **kwargs: object) -> bool:
        verified.append(True)
        return True

    monkeypatch.setattr(loader_main, "Settings", lambda: settings)
    monkeypatch.setattr(loader_main, "_connect", lambda s: nullcontext(object()))
    monkeypatch.setattr(loader_main, "_expected_embedding_dims", lambda s: 1024)
    monkeypatch.setattr(loader_main, "dataset_mismatch", lambda *args: graph_reason)
    monkeypatch.setattr(loader_main, "verify", fake_verify)
    return verified


def _mark(output: Path) -> Path:
    path = output / "nodes_aircraft.csv"
    path.write_text(MARKER)
    return path


def test_generate_writes_the_config_and_code_hash(tmp_path: Path) -> None:
    _generate(tmp_path)

    written = json.loads((tmp_path / stamp.STAMP_NAME).read_text())
    config = GeneratorConfig(n_aircraft=6, n_airports=40, n_days=2, seed=42)
    assert written == stamp.stamp_for(config)
    assert written["generator_hash"] == stamp.generator_hash()


def test_if_stale_skips_when_the_stamp_matches(tmp_path: Path) -> None:
    _generate(tmp_path)
    marked = _mark(tmp_path)

    _generate(tmp_path, if_stale=True)

    assert marked.read_text() == MARKER


def test_if_stale_regenerates_after_a_config_change(tmp_path: Path) -> None:
    _generate(tmp_path)
    marked = _mark(tmp_path)

    _generate(tmp_path, if_stale=True, seed=7)

    assert marked.read_text() != MARKER
    assert stamp.read_stamp(tmp_path)["config"]["seed"] == 7


def test_if_stale_regenerates_after_a_code_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _generate(tmp_path)
    marked = _mark(tmp_path)
    monkeypatch.setattr(stamp, "generator_hash", lambda: "changed")

    _generate(tmp_path, if_stale=True)

    assert marked.read_text() != MARKER
    assert stamp.read_stamp(tmp_path)["generator_hash"] == "changed"


def test_the_stamp_records_the_python_faker_and_numpy_versions(tmp_path: Path) -> None:
    # The CSVs depend on Faker's data and NumPy's random streams, not only
    # on the generator code.
    _generate(tmp_path)

    assert stamp.read_stamp(tmp_path)["runtime"] == {
        "faker": version("faker"),
        "numpy": version("numpy"),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def _bump_numpy(monkeypatch: pytest.MonkeyPatch) -> None:
    current = stamp.runtime_versions()
    monkeypatch.setattr(stamp, "runtime_versions", lambda: {**current, "numpy": "0.0.0"})


def test_if_stale_regenerates_after_a_library_version_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _generate(tmp_path)
    marked = _mark(tmp_path)
    _bump_numpy(monkeypatch)

    _generate(tmp_path, if_stale=True)

    assert marked.read_text() != MARKER
    assert stamp.read_stamp(tmp_path)["runtime"]["numpy"] == "0.0.0"


def test_stale_reason_names_a_changed_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _generate(tmp_path)
    assert stamp.stale_reason(tmp_path) is None
    _bump_numpy(monkeypatch)

    assert stamp.stale_reason(tmp_path) == (
        f"the numpy version changed since {tmp_path} was generated"
    )


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"[]", id="list"),
        pytest.param(b'"x"', id="string"),
        pytest.param(b"\xff\xfe not utf-8", id="not-utf-8"),
        pytest.param(None, id="directory"),
    ],
)
def test_read_stamp_returns_none_for_an_unusable_stamp(
    tmp_path: Path, content: bytes | None
) -> None:
    path = tmp_path / stamp.STAMP_NAME
    if content is None:
        path.mkdir()
    else:
        path.write_bytes(content)

    assert stamp.read_stamp(tmp_path) is None
    assert "has no .stamp.json" in stamp.stale_reason(tmp_path)


def test_generator_hash_covers_every_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "generator"
    (source / "sub").mkdir(parents=True)
    (source / "a.py").write_text("A = 1\n")
    (source / "sub" / "b.py").write_text("B = 1\n")
    monkeypatch.setattr(stamp, "_GENERATOR_DIR", source)
    before = stamp.generator_hash()

    (source / "sub" / "b.py").write_text("B = 2\n")

    assert stamp.generator_hash() != before


def _add_link(path: Path, target: str) -> None:
    path.symlink_to(target)


def _add_file(path: Path, text: str = "EDITOR = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.mark.parametrize(
    "add",
    [
        # Emacs writes a lock as a symlink to a name that does not exist.
        pytest.param(lambda src: _add_link(src / ".#a.py", "user@host.123:1"), id="emacs-lock"),
        pytest.param(
            lambda src: _add_file(src / ".ipynb_checkpoints" / "a-checkpoint.py"),
            id="ipynb-checkpoint",
        ),
        pytest.param(lambda src: _add_file(src / "sub" / "__pycache__" / "b.py"), id="pycache"),
        pytest.param(lambda src: _add_file(src / ".scratch.py"), id="dotfile"),
        pytest.param(lambda src: (src / "pkg.py").mkdir(), id="directory"),
        pytest.param(lambda src: _add_link(src / "gone.py", "missing.py"), id="dangling-link"),
    ],
)
def test_generator_hash_ignores_editor_and_cache_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, add: Callable[[Path], None]
) -> None:
    source = tmp_path / "generator"
    (source / "sub").mkdir(parents=True)
    (source / "a.py").write_text("A = 1\n")
    (source / "sub" / "b.py").write_text("B = 1\n")
    monkeypatch.setattr(stamp, "_GENERATOR_DIR", source)
    before = stamp.generator_hash()

    add(source)

    assert stamp.generator_hash() == before


@pytest.mark.parametrize(
    ("written", "reason"),
    [
        pytest.param(None, "has no .stamp.json", id="missing"),
        pytest.param("not json", "has no .stamp.json", id="unreadable"),
        pytest.param({"config": {}, "generator_hash": "old"}, "generator code changed", id="code"),
    ],
)
def test_strict_verify_fails_on_a_stale_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, written: object, reason: str
) -> None:
    if isinstance(written, str):
        (tmp_path / stamp.STAMP_NAME).write_text(written)
    elif written is not None:
        (tmp_path / stamp.STAMP_NAME).write_text(json.dumps(written))
    _fake_verify(monkeypatch, tmp_path, graph_reason=None)

    result = CliRunner().invoke(loader_main.app, ["verify", "--strict"])

    assert result.exit_code == 1, result.output
    assert "[FAIL]" in result.output
    assert reason in result.output
    assert "./setup.sh generate" in result.output


def test_verify_warns_on_a_stale_stamp_without_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_verify(monkeypatch, tmp_path, graph_reason=None)

    result = CliRunner().invoke(loader_main.app, ["verify"])

    assert result.exit_code == 0, result.output
    assert "[WARN]" in result.output
    assert "has no .stamp.json" in result.output


def test_verify_passes_a_current_stamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _generate(tmp_path)
    verified = _fake_verify(monkeypatch, tmp_path, graph_reason=None)

    result = CliRunner().invoke(loader_main.app, ["verify", "--strict"])

    assert result.exit_code == 0, result.output
    assert ".stamp.json" not in result.output
    assert verified == [True]


GRAPH_REASON = "the graph was loaded from a run with a different config.days than generated"


def test_strict_verify_fails_when_the_graph_does_not_match_the_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _generate(tmp_path)
    verified = _fake_verify(monkeypatch, tmp_path, graph_reason=GRAPH_REASON)

    result = CliRunner().invoke(loader_main.app, ["verify", "--strict"])

    assert result.exit_code == 1, result.output
    assert f"[FAIL] The graph does not match the generated CSVs: {GRAPH_REASON}." in result.output
    # The CSVs are current, so only a reload is needed.
    assert "Reload: ./setup.sh load." in result.output
    assert "./setup.sh generate" not in result.output
    assert verified == []


def test_verify_reports_a_stale_stamp_and_a_mismatched_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verified = _fake_verify(monkeypatch, tmp_path, graph_reason=GRAPH_REASON)

    result = CliRunner().invoke(loader_main.app, ["verify"])

    assert result.exit_code == 0, result.output
    assert "[WARN] Generated CSVs are stale" in result.output
    assert f"[WARN] The graph does not match the generated CSVs: {GRAPH_REASON}." in result.output
    assert verified == [True]
