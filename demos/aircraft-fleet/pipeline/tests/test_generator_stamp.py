"""generated/.stamp.json records the config and generator code behind the CSVs."""

from __future__ import annotations

import json
from contextlib import nullcontext
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


def test_failed_generate_leaves_no_stamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _generate(tmp_path)

    def fail(*args: object) -> None:
        raise RuntimeError("generator bug")

    monkeypatch.setattr(generator_main, "generate_removals", fail)
    with pytest.raises(RuntimeError, match="generator bug"):
        _generate(tmp_path, seed=7)

    assert stamp.read_stamp(tmp_path) is None


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
    settings = SimpleNamespace(neo4j_uri="bolt://example", neo4j_database="db", data_dir=tmp_path)
    monkeypatch.setattr(loader_main, "Settings", lambda: settings)

    def no_connect(settings: object) -> None:
        raise AssertionError("verify connected despite a stale stamp")

    monkeypatch.setattr(loader_main, "_connect", no_connect)

    result = CliRunner().invoke(loader_main.app, ["verify", "--strict"])

    assert result.exit_code == 1, result.output
    assert "[FAIL]" in result.output
    assert reason in result.output
    assert "./setup.sh generate" in result.output


def test_verify_warns_on_a_stale_stamp_without_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = SimpleNamespace(neo4j_uri="bolt://example", neo4j_database="db", data_dir=tmp_path)
    monkeypatch.setattr(loader_main, "Settings", lambda: settings)
    monkeypatch.setattr(loader_main, "_connect", lambda s: nullcontext(object()))
    monkeypatch.setattr(loader_main, "_expected_embedding_dims", lambda s: 1024)
    monkeypatch.setattr(loader_main, "verify", lambda *args, **kwargs: True)

    result = CliRunner().invoke(loader_main.app, ["verify"])

    assert result.exit_code == 0, result.output
    assert "[WARN]" in result.output
    assert "has no .stamp.json" in result.output


def test_verify_passes_a_current_stamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _generate(tmp_path)
    settings = SimpleNamespace(neo4j_uri="bolt://example", neo4j_database="db", data_dir=tmp_path)
    monkeypatch.setattr(loader_main, "Settings", lambda: settings)
    monkeypatch.setattr(loader_main, "_connect", lambda s: nullcontext(object()))
    monkeypatch.setattr(loader_main, "_expected_embedding_dims", lambda s: 1024)
    monkeypatch.setattr(loader_main, "verify", lambda *args, **kwargs: True)

    result = CliRunner().invoke(loader_main.app, ["verify", "--strict"])

    assert result.exit_code == 0, result.output
    assert ".stamp.json" not in result.output
