"""setup.sh reads ../.env without overriding variables already exported."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

SETUP = Path(__file__).parent.parent / "setup.sh"

# Stands in for uv, so the run touches no Neo4j and no Python env.
STUB_UV = """#!/bin/sh
printf 'NEO4J_DATABASE=%s\\n' "$NEO4J_DATABASE"
printf 'NEO4J_URI=%s\\n' "$NEO4J_URI"
printf 'NEO4J_PASSWORD=%s\\n' "$NEO4J_PASSWORD"
"""


def _run_verify(tmp_path: Path, env_file: str, exported: dict[str, str]) -> list[str]:
    """Run a copy of setup.sh verify beside env_file, with exported set."""
    pipeline = tmp_path / "pipeline"
    (pipeline / "generated").mkdir(parents=True)
    (pipeline / "generated" / "nodes.csv").write_text("id\n", encoding="utf-8")
    shutil.copy(SETUP, pipeline / "setup.sh")
    (tmp_path / ".env").write_text(env_file, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(STUB_UV, encoding="utf-8")
    (bin_dir / "uv").chmod(0o755)

    env = {k: v for k, v in os.environ.items() if not k.startswith("NEO4J_")}
    env |= exported | {"PATH": f"{bin_dir}{os.pathsep}{env['PATH']}"}
    result = subprocess.run(
        ["bash", "setup.sh", "verify"],
        cwd=pipeline,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def test_an_exported_variable_wins_over_the_env_file(tmp_path: Path) -> None:
    env_file = (
        "NEO4J_DATABASE=from_env_file\n"
        "NEO4J_URI=bolt://env-file:7687\n"
        "NEO4J_PASSWORD='from env file'\n"
    )
    exported = {"NEO4J_DATABASE": "step13", "NEO4J_PASSWORD": 'it\'s "quoted" $HOME'}

    assert _run_verify(tmp_path, env_file, exported) == [
        "NEO4J_DATABASE=step13",
        "NEO4J_URI=bolt://env-file:7687",
        'NEO4J_PASSWORD=it\'s "quoted" $HOME',
    ]


def test_the_env_file_fills_variables_that_are_not_exported(tmp_path: Path) -> None:
    env_file = "NEO4J_DATABASE=from_env_file\nNEO4J_URI=bolt://env-file:7687\n"

    assert _run_verify(tmp_path, env_file, {})[:2] == [
        "NEO4J_DATABASE=from_env_file",
        "NEO4J_URI=bolt://env-file:7687",
    ]
