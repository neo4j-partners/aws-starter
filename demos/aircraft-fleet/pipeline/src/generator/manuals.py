"""Render the generated blocks of the maintenance manuals from specs.

A block is the text between two marker lines:

    <!-- BEGIN GENERATED: vibration-bands -->
    ...rendered markdown...
    <!-- END GENERATED: vibration-bands -->

Rendering replaces each block's body with its renderer's output and keeps
every other line. The loader strips the markers before chunking.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .specs import ENGINE_SPECS, SYSTEM_SENSORS, EngineSpec, sensors_for

MANUALS_DIR = Path(__file__).resolve().parent.parent.parent / "manuals"

# Aircraft model -> manual file. Matches the loader's document registry.
MANUAL_FILES: dict[str, str] = {
    "A320-200": "MAINTENANCE_A320.md",
    "A321neo": "MAINTENANCE_A321neo.md",
    "B737-800": "MAINTENANCE_B737.md",
    "E190": "MAINTENANCE_E190.md",
    "A220-300": "MAINTENANCE_A220.md",
}

Stats = Mapping[str, Any]
Renderer = Callable[[str, EngineSpec, Stats], str]

# Where each sensor sits, as the manuals describe it. Only the manuals use
# this, so it lives here and not in specs.
_SENSOR_LOCATIONS: dict[str, str] = {
    "EGT": "Turbine exhaust section",
    "Vibration": "Fan frame, turbine frame",
    "N1Speed": "Fan shaft",
    "FuelFlow": "Fuel metering valve",
    "BusVoltage": "DC essential bus",
    "AirDataDisagree": "Captain and first officer air data sources",
    "HydPressure": "System pressure manifold",
    "HydQuantity": "Hydraulic reservoir",
}
_MODEL_SENSOR_LOCATIONS: dict[str, dict[str, str]] = {
    "A220-300": {"N1Speed": "Fan shaft (gearbox output)"},
    "A320-200": {
        "EGT": "Turbine exhaust",
        "Vibration": "Fan case",
        "FuelFlow": "Fuel metering unit",
    },
    "A321neo": {
        "EGT": "HPT exit (8 thermocouples)",
        "Vibration": "Fan case, core case",
        "FuelFlow": "Fuel metering unit",
    },
}
_COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def _count(n: int) -> str:
    return _COUNT_WORDS.get(n, str(n))


def _sensor_location(model: str, sensor_type: str) -> str:
    return _MODEL_SENSOR_LOCATIONS.get(model, {}).get(sensor_type, _SENSOR_LOCATIONS[sensor_type])


def _sensor_table(model: str, engine: EngineSpec, stats: Stats) -> str:
    """§2.2: every generated sensor, by system, with its unit and location."""
    counts = {system: len(sensors_for(system, model)) for system in SYSTEM_SENSORS}
    others = sorted(system for system in counts if system != "Engine")
    if len({counts[system] for system in others}) == 1:
        rest = f"The {' and '.join(others)} systems carry {_count(counts[others[0]])} sensors each."
    else:
        rest = " ".join(
            f"The {system} system carries {_count(counts[system])} sensors." for system in others
        )
    lines = [
        f"Each {engine.engine_type} engine carries {_count(counts['Engine'])} monitoring "
        f"sensors. {rest} The digital twin records every sensor hourly.",
        "",
        "| System | Sensor Type | Parameter | Unit | Location |",
        "|--------|-------------|-----------|------|----------|",
    ]
    for system in SYSTEM_SENSORS:
        for spec in sensors_for(system, model):
            location = _sensor_location(model, spec.type)
            lines.append(f"| {system} | {spec.type} | {spec.name} | {spec.unit} | {location} |")
    return "\n".join(lines)


def _egt_trend_note(model: str, engine: EngineSpec, stats: Stats) -> str:
    """§2.2: the hourly EGT trend scale, with its baseline and bands."""
    egt = next(s for s in engine.sensors if s.type == "EGT")
    b = egt.bands
    return (
        "**Digital Twin Monitoring Note:** The Digital Twin Monitoring System records "
        "hourly trend-averaged EGT values on a normalized scale calibrated for long-term "
        f"degradation detection. For the {engine.engine_type}, the trend baseline is "
        f"{egt.baseline:g}°C, with Advisory at {b.advisory:g}°C, Caution at "
        f"{b.caution:g}°C, and Warning at {b.warning:g}°C. These trend values differ from "
        "the instantaneous EGT limits in the Normal Operating Parameters table and "
        "Appendix 10.1, which reflect peak values during takeoff and high-power "
        "operations. The trend scale detects gradual EGT margin deterioration over weeks "
        "and months, not acute exceedances. The absolute limits in this manual refer to "
        "instantaneous FADEC-monitored readings."
    )


# Block id -> renderer. Each takes (model, engine spec, fleet stats).
RENDERERS: dict[str, Renderer] = {
    "sensor-table": _sensor_table,
    "egt-trend-note": _egt_trend_note,
}

# Blocks every manual must have, once each.
REQUIRED_BLOCKS: tuple[str, ...] = tuple(RENDERERS)

_MARKER = re.compile(r"^<!-- (BEGIN|END) GENERATED: ([a-z0-9-]+) -->$")
# A line that looks like a marker but does not match _MARKER exactly.
_MARKER_LIKE = re.compile(r"^\s*<!--\s*(BEGIN|END)\s+GENERATED", re.IGNORECASE)


class ManualBlockError(ValueError):
    """A manual's block markers are malformed, unknown, or missing."""


def load_stats() -> Stats:
    """The fleet statistics the stats blocks render from."""
    return {}


def render_text(
    text: str,
    model: str,
    stats: Stats,
    *,
    renderers: Mapping[str, Renderer] | None = None,
    required: tuple[str, ...] | None = None,
) -> str:
    """Return text with every block body rendered for model."""
    renderers = RENDERERS if renderers is None else renderers
    required = REQUIRED_BLOCKS if required is None else required
    engine = ENGINE_SPECS[model]
    out: list[str] = []
    seen: set[str] = set()
    open_id: str | None = None
    open_line = 0
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        stripped = line.rstrip("\n")
        if (match := _MARKER.match(stripped)) is None:
            if _MARKER_LIKE.match(stripped):
                raise ManualBlockError(f"line {number}: malformed marker {stripped!r}")
            if open_id is None:
                out.append(line)
            continue
        kind, block_id = match.groups()
        if kind == "BEGIN":
            if open_id is not None:
                raise ManualBlockError(
                    f"line {number}: BEGIN marker for {block_id!r} inside block {open_id!r}"
                )
            if block_id not in renderers:
                raise ManualBlockError(f"line {number}: unknown block id {block_id!r}")
            if block_id in seen:
                raise ManualBlockError(f"line {number}: block {block_id!r} appears twice")
            seen.add(block_id)
            open_id, open_line = block_id, number
            out.append(line)
            if body := renderers[block_id](model, engine, stats).rstrip("\n"):
                out.append(body + "\n")
        elif open_id is None:
            raise ManualBlockError(f"line {number}: END marker for {block_id!r} without a BEGIN")
        elif block_id != open_id:
            raise ManualBlockError(
                f"line {number}: END marker for {block_id!r} inside block {open_id!r}"
            )
        else:
            open_id = None
            out.append(line if line.endswith("\n") else line + "\n")
    if open_id is not None:
        raise ManualBlockError(f"line {open_line}: block {open_id!r} has no END marker")
    for block_id in required:
        if block_id not in seen:
            raise ManualBlockError(f"missing required block {block_id!r}")
    return "".join(out)
