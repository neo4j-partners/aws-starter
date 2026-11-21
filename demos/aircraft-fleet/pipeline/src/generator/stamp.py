"""Record which config and generator code produced a generated/ directory.

generate writes .stamp.json after every CSV is in place, and removes it
first, so a run that fails partway leaves no stamp. The loader's verify
command compares the stamp's code hash with the current source.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import GeneratorConfig

STAMP_NAME = ".stamp.json"
_GENERATOR_DIR = Path(__file__).resolve().parent


def generator_hash() -> str:
    """Return a SHA-256 over the path and bytes of every .py file in the generator."""
    digest = hashlib.sha256()
    for path in sorted(_GENERATOR_DIR.rglob("*.py")):
        data = path.read_bytes()
        name = path.relative_to(_GENERATOR_DIR).as_posix()
        digest.update(f"{name}\0{len(data)}\0".encode())
        digest.update(data)
    return digest.hexdigest()


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
    }


def read_stamp(directory: Path) -> dict[str, Any] | None:
    """Return the directory's stamp, or None if it is missing or not valid JSON."""
    try:
        return json.loads((directory / STAMP_NAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        # A truncated or hand-edited stamp proves nothing, so treat it as missing.
        return None


def write_stamp(directory: Path, stamp: dict[str, Any]) -> None:
    (directory / STAMP_NAME).write_text(
        json.dumps(stamp, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def clear_stamp(directory: Path) -> None:
    (directory / STAMP_NAME).unlink(missing_ok=True)


def stale_reason(directory: Path) -> str | None:
    """Return why the directory's CSVs do not match the current generator code.

    Returns None when the stamp's code hash matches. The config is not
    checked here, since only setup.sh knows the GEN_* values.
    """
    stamp = read_stamp(directory)
    if stamp is None:
        return f"{directory} has no {STAMP_NAME}"
    if stamp.get("generator_hash") != generator_hash():
        return f"the generator code changed since {directory} was generated"
    return None
