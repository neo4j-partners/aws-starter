"""Record which config and generator code produced a generated/ directory.

generate writes each run into a temp directory, stamp included. When the
run finishes, it removes the old stamp, moves each CSV into place, and moves
the new stamp in last. A failed run leaves the old CSVs and stamp, and a run
stopped during the moves leaves no stamp. The loader's verify
command compares the stamp's code hash and library versions with the
current ones.
"""

from __future__ import annotations

import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .config import GeneratorConfig

STAMP_NAME = ".stamp.json"
# A generate holds an exclusive lock on this file in its output directory,
# and a load holds a shared one, so a load never reads a run mid-publish.
LOCK_NAME = ".generate.lock"


class GenerateRunningError(RuntimeError):
    """A generate or a load holds a directory's lock that the caller needs."""


_GENERATOR_DIR = Path(__file__).resolve().parent
# Libraries whose data or random streams shape the CSVs.
_LIBRARIES = ("faker", "numpy")


def _is_source(path: Path) -> bool:
    """Return whether a .py path under the generator is source code.

    Editor and tool files are left out: any path part that starts with "."
    covers an Emacs .#lock link and .ipynb_checkpoints, and __pycache__ is
    left out too. So is anything that is not a regular file, such as a
    directory or a dangling link, since it has no bytes to hash.
    """
    parts = path.relative_to(_GENERATOR_DIR).parts
    if any(part.startswith(".") or part == "__pycache__" for part in parts):
        return False
    return path.is_file()


def generator_hash() -> str:
    """Return a SHA-256 over the path and bytes of every .py source file in the generator."""
    digest = hashlib.sha256()
    for path in sorted(filter(_is_source, _GENERATOR_DIR.rglob("*.py"))):
        data = path.read_bytes()
        name = path.relative_to(_GENERATOR_DIR).as_posix()
        digest.update(f"{name}\0{len(data)}\0".encode())
        digest.update(data)
    return digest.hexdigest()


def runtime_versions() -> dict[str, str]:
    """Return the Python major.minor and the version of each library the output depends on.

    The same seed can give different CSVs under another Faker, whose data
    files change between releases, or another NumPy or Python, whose random
    streams may change.
    """
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    return {"python": python} | {name: version(name) for name in _LIBRARIES}


def stamp_for(config: GeneratorConfig) -> dict[str, Any]:
    """Return the stamp a run of this config writes with the current code."""
    return {
        "config": {
            "aircraft": config.n_aircraft,
            "airports": config.n_airports,
            "days": config.n_days,
            "seed": config.seed,
            "start_date": config.start_date.isoformat(),
        },
        "generator_hash": generator_hash(),
        "runtime": runtime_versions(),
    }


def read_stamp(directory: Path) -> dict[str, Any] | None:
    """Return the directory's stamp, or None if it is missing or unusable.

    A stamp that cannot be read, is not UTF-8 JSON, or is not a JSON object
    proves nothing, so it counts as missing. OSError covers a missing file
    and a directory in its place. ValueError covers bad UTF-8 and bad JSON.
    """
    try:
        stamp = json.loads((directory / STAMP_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return stamp if isinstance(stamp, dict) else None


def write_stamp(directory: Path, stamp: dict[str, Any]) -> None:
    (directory / STAMP_NAME).write_text(
        json.dumps(stamp, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def stamp_differences(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Return the stamp keys whose values differ, naming nested keys as <key>.<subkey>."""
    keys = []
    for key in sorted(old.keys() | new.keys()):
        old_value, new_value = old.get(key), new.get(key)
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            keys += [
                f"{key}.{k}"
                for k in sorted(old_value.keys() | new_value.keys())
                if old_value.get(k) != new_value.get(k)
            ]
        elif old_value != new_value:
            keys.append(key)
    return keys


def regenerate_reason(directory: Path, stamp: dict[str, Any]) -> str | None:
    """Return why a run with this stamp must rewrite directory.

    Returns None when the directory's stamp already matches.
    """
    current = read_stamp(directory)
    if current is None:
        return f"there is no {STAMP_NAME}"
    if differs := stamp_differences(current, stamp):
        return f"the stamp has a different {', '.join(differs)}"
    return None


def clear_stamp(directory: Path) -> None:
    (directory / STAMP_NAME).unlink(missing_ok=True)


def stale_reason(directory: Path) -> str | None:
    """Return why the directory's CSVs do not match the current generator code.

    Returns None when the stamp's code hash and library versions match. The
    config is not checked here, since only setup.sh knows the GEN_* values.
    """
    stamp = read_stamp(directory)
    if stamp is None:
        return f"{directory} has no {STAMP_NAME}"
    if stamp.get("generator_hash") != generator_hash():
        return f"the generator code changed since {directory} was generated"
    recorded = stamp.get("runtime")
    if not isinstance(recorded, dict) or not recorded:
        return "the stamp records no runtime versions"
    if changed := [k for k, v in runtime_versions().items() if recorded.get(k) != v]:
        return f"the {', '.join(changed)} version changed since {directory} was generated"
    return None
