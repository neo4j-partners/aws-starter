"""Render the generated blocks of the maintenance manuals from specs.

A block is the text between two marker lines:

    <!-- BEGIN GENERATED: vibration-bands -->
    ...rendered markdown...
    <!-- END GENERATED: vibration-bands -->

Rendering replaces each block's body with its renderer's output and keeps
every other line. The loader strips the markers before chunking.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .config import GeneratorConfig
from .fleet import AircraftNode, SystemNode, generate_fleet
from .maintenance import SEVERITY_BY_LEVEL
from .specs import (
    ENGINE_SPECS,
    EVENT_SEVERITIES,
    FAULT_CODES,
    MANUAL_FLEET_TAILS,
    PHASES,
    SYSTEM_SENSORS,
    VIBRATION_LEVELS,
    Direction,
    EgtBand,
    EngineSpec,
    FaultCode,
    SensorSpec,
    sensors_for,
)

MANUALS_DIR = Path(__file__).resolve().parent.parent.parent / "manuals"
# The fleet statistics file, in the manuals directory.
STATS_NAME = "fleet-stats.json"

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


# The tree spells out a part name that is an abbreviation, and adds the
# abbreviation to one that is not.
_TREE_LABELS: dict[str, str] = {
    "FMS": "Flight Management System (FMS)",
    "ADC": "Air Data Computer (ADC)",
    "ADIRU": "Air Data and Inertial Reference Unit (ADIRU)",
    "NAV": "Navigation Receiver (NAV)",
    "MMR": "Multi-Mode Receiver (MMR)",
    "Electrohydraulic Servo Actuators": "Electrohydraulic Servo Actuators (EHSA)",
}
_ENGINE_SIDES = {1: "Left", 2: "Right"}
# The component number each manual's §2.3 example points at.
_EXAMPLE_COMPONENT: dict[str, int] = {"A321neo": 1}


@functools.cache
def _registry_aircraft(model: str) -> AircraftNode:
    """The first generated aircraft of model. It carries the model's first manual tail."""
    fleet = generate_fleet(GeneratorConfig(n_aircraft=len(MANUAL_FLEET_TAILS)))
    return next(a for a in fleet if a.model == model)


def _system_header(system: SystemNode, engine: EngineSpec) -> str:
    if system.engine_index is None:
        return f"{system.type.upper()} SYSTEM"
    side = _ENGINE_SIDES[system.engine_index]
    return f"ENGINE SYSTEM #{system.engine_index} ({engine.engine_type} {side})"


def _component_tree(model: str, engine: EngineSpec, stats: Stats) -> str:
    """§2.1: the systems and components of every aircraft of model, in id order."""
    aircraft = _registry_aircraft(model)
    lines = ["```", f"AIRCRAFT ({model})", "│"]
    for number, system in enumerate(aircraft.systems, start=1):
        last_system = number == len(aircraft.systems)
        lines.append(f"{'└' if last_system else '├'}── {_system_header(system, engine)}")
        stem = " " if last_system else "│"
        for index, component in enumerate(system.components, start=1):
            branch = "└" if index == len(system.components) else "├"
            label = _TREE_LABELS.get(component.name, component.name)
            lines.append(f"{stem}   {branch}── {label}")
        if not last_system:
            lines.append("│")
    lines.append("```")
    return "\n".join(lines)


def _system_code(system: SystemNode) -> str:
    if system.engine_index is None:
        return system.name
    return f"Engine #{system.engine_index} ({_ENGINE_SIDES[system.engine_index]})"


def _component_ids(model: str, engine: EngineSpec, stats: Stats) -> str:
    """§2.3: an example component id from a manual-tail aircraft, and the system codes."""
    aircraft = _registry_aircraft(model)
    first_engine = aircraft.systems[0]
    component = first_engine.components[_EXAMPLE_COMPONENT.get(model, 3) - 1]
    lines = [
        "```",
        "[Aircraft ID]-[System]-[Component]",
        "",
        f"Example: {component.component_id}",
        f"         │       │    └── Component: {component.name}",
        f"         │       └─────── System: {_system_code(first_engine).split(' (')[0]}",
        f"         └─────────────── Aircraft: {aircraft.aircraft_id} ({aircraft.tail_number})",
        "```",
        "",
        "**System Codes:**",
        *(f"- {s.system_id.rsplit('-', 1)[1]}: {_system_code(s)}" for s in aircraft.systems),
    ]
    return "\n".join(lines)


# The flight deck alert at each vibration level above Normal. The Airbus
# models use ECAM names.
_BOEING_STYLE_ALERTS = ("ENG VIB (amber)", "ENG VIB (amber)", "ENG VIB (red)")
_ECAM_ALERTS = ("ENG 1(2) VIB (amber)", "ENG 1(2) VIB HI (amber)", "ENG 1(2) VIB (red)")
_VIBRATION_ALERTS: dict[str, tuple[str, str, str]] = {
    "A220-300": _BOEING_STYLE_ALERTS,
    "A320-200": _ECAM_ALERTS,
    "A321neo": _ECAM_ALERTS,
    "B737-800": _BOEING_STYLE_ALERTS,
    "E190": _BOEING_STYLE_ALERTS,
}


def _vibration_thresholds(engine: EngineSpec) -> tuple[float, float, float]:
    vibration = next(s for s in engine.sensors if s.type == "Vibration")
    b = vibration.bands
    return b.advisory, b.caution, b.warning


def _vibration_bands(model: str, engine: EngineSpec, stats: Stats) -> str:
    """§4: the Vibration Limits table, with the event severity of each level."""
    advisory, caution, warning = _vibration_thresholds(engine)
    ranges = (
        f"< {advisory:.1f} ips",
        f"{advisory:.1f}-{caution:.1f} ips",
        f"{caution:.1f}-{warning:.1f} ips",
        f"≥ {warning:.1f} ips",
    )
    severities = ("None", *(SEVERITY_BY_LEVEL[level] for level in (1, 2, 3)))
    alerts = ("None", *_VIBRATION_ALERTS[model])
    lines = [
        "| Level | N1 Vibration | Event Severity | Flight Deck Alert |",
        "|-------|--------------|----------------|-------------------|",
        *(
            f"| {level} | {band} | {severity} | {alert} |"
            for level, band, severity, alert in zip(
                VIBRATION_LEVELS, ranges, severities, alerts, strict=True
            )
        ),
    ]
    return "\n".join(lines)


def _vibration_shutdown(model: str, engine: EngineSpec, stats: Stats) -> str:
    """§8.1: the vibration levels the decision tree below names."""
    advisory, caution, warning = _vibration_thresholds(engine)
    return (
        "**Vibration thresholds:** The levels come from the Vibration Limits table in "
        "the Vibration Exceedance section. They apply to N1 vibration, the channel the "
        f"digital twin records. The Warning level starts at {warning:.1f} ips. The "
        f"Caution level starts at {caution:.1f} ips. The Advisory level starts at "
        f"{advisory:.1f} ips. The tree below names these levels."
    )


def _table(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("-" * (len(cell) + 2) for cell in header) + "|",
        *("| " + " | ".join(row) + " |" for row in rows),
    ]
    return "\n".join(lines)


# The rows of the Normal Operating Parameters table, in order. A row the
# model has no data for is left out.
_PHASE_ROWS = (
    "N1Speed (%)",
    "N2 (%)",
    "EGT (°C)",
    "FuelFlow (kg/s)",
    "Oil Pressure (psi)",
    "Oil Temperature (°C)",
    "Vibration N1 (ips)",
    "Gearbox Oil Pressure (psi)",
    "Gearbox Oil Temperature (°C)",
)
# The sensor each row's cruise cell comes from.
_CRUISE_SENSORS = {
    "N1Speed (%)": "N1Speed",
    "EGT (°C)": "EGT",
    "FuelFlow (kg/s)": "FuelFlow",
    "Vibration N1 (ips)": "Vibration",
}
_CRUISE_DECIMALS = {"N1Speed": 0, "EGT": 0, "FuelFlow": 2, "Vibration": 1}


def _cruise_cell(spec: SensorSpec) -> str:
    """The digital twin baseline, with the range before the Advisory band."""
    places = _CRUISE_DECIMALS[spec.type]
    advisory = spec.offsets()[0]
    if spec.direction is Direction.DEVIATION:
        low, high = spec.baseline - advisory, spec.baseline + advisory
        return f"{spec.baseline:g} ({low:.{places}f}-{high:.{places}f})"
    return f"{spec.baseline:g} (< {spec.bands.advisory:.{places}f})"


def _phase_limits(model: str, engine: EngineSpec, stats: Stats) -> str:
    """§3.3 and §10.1: engine limits at each power setting, with the cruise baseline."""
    specs = {s.type: s for s in engine.sensors}
    limits = engine.egt_limits
    advisory = f"< {specs['Vibration'].bands.advisory:.1f}"
    cells = {
        **engine.phase_limits,
        "EGT (°C)": (
            limits.ground_idle,
            limits.flight_idle,
            f"< {limits.max_continuous.normal_below:,.0f}",
            f"< {limits.takeoff.normal_below:,.0f}",
        ),
        "Vibration N1 (ips)": (advisory,) * len(PHASES),
    }
    rows = []
    for label in _PHASE_ROWS:
        if label not in cells:
            continue
        sensor = _CRUISE_SENSORS.get(label)
        cruise = "—" if sensor is None else _cruise_cell(specs[sensor])
        idle, flight_idle, max_continuous, takeoff = cells[label]
        rows.append((label, idle, flight_idle, cruise, max_continuous, takeoff))
    header = ("Parameter", *PHASES[:2], "Cruise (digital twin)", *PHASES[2:])
    return _table(header, rows)


def _fuel_flow_range(model: str, engine: EngineSpec, stats: Stats) -> str:
    """§3.2.4: the fuel pump's flow range, from ground idle to takeoff."""
    bounds = [
        float(value) for cell in engine.phase_limits["FuelFlow (kg/s)"] for value in cell.split("-")
    ]
    return f"**Flow Rate:** {min(bounds):.2f} - {max(bounds):.2f} kg/s (ground idle to takeoff)"


def _egt_row(label: str, band: EgtBand) -> tuple[str, ...]:
    return (
        label,
        f"< {band.normal_below:,.0f}°C",
        f"{band.normal_below:,.0f}-{band.caution_to:,.0f}°C",
        f"{band.maximum:,.0f}°C",
    )


def _egt_limits(model: str, engine: EngineSpec, stats: Stats) -> str:
    """§3.2.3: the instantaneous turbine temperature limits."""
    limits = engine.egt_limits
    rows = [
        _egt_row("EGT (Takeoff, 5 min)", limits.takeoff),
        _egt_row("EGT (Max Continuous)", limits.max_continuous),
    ]
    if limits.start_max is not None:
        rows.append(("EGT (Start)", "—", "—", f"{limits.start_max:,.0f}°C"))
    return _table(("Parameter", "Normal", "Caution", "Maximum"), rows)


def _hydraulic_limits(model: str, engine: EngineSpec, stats: Stats) -> str:
    """§10.1: the hydraulic bands every circuit shares."""
    rows = []
    for spec in sensors_for("Hydraulics", model):
        b = spec.bands
        rows.append(
            (
                f"{spec.name} ({spec.unit})",
                f"{spec.baseline:,g}",
                f"> {b.advisory:,g}",
                f"{b.caution:,g}-{b.advisory:,g}",
                f"{b.warning:,g}-{b.caution:,g}",
                f"≤ {b.warning:,g}",
            )
        )
    header = ("Parameter", "Nominal", "Normal", "Advisory", "Caution", "Warning")
    return _table(header, rows)


# The section 7 text of each code, from the B737 manual: description, ATA
# chapter, and primary action.
_FAULT_CODE_TEXT: dict[str, tuple[str, int, str]] = {
    "ENG-SDR-001": ("Sensor Drift", 77, "Identify sensor, verify, replace"),
    "ENG-CNT-002": ("Contamination", 72, "Oil/fuel analysis, wash/clean"),
    "ENG-BRG-003": ("Bearing Wear", 72, "Oil analysis, vibration check"),
    "ENG-LEAK-004": ("Fluid Leak", 79, "Identify source, repair"),
    "ENG-VIB-005": ("Vibration Exceedance", 72, "Fan balance, bearing check"),
    "ENG-OVH-006": ("Overheat", 72, "Reduce thrust, borescope"),
    "ENG-FUEL-007": ("Fuel Starvation", 73, "Check fuel system, filter"),
    "ENG-ELF-008": ("Electrical Fault", 77, "FADEC diagnostics, wiring"),
    "AVN-SDR-001": ("Sensor Drift", 34, "ADC comparison, calibration"),
    "AVN-ELF-002": ("Electrical Fault", 34, "Power check, connector inspect"),
    "AVN-FMS-003": ("FMS Malfunction", 34, "Reset, database reload"),
    "AVN-NAV-004": ("NAV Receiver Fault", 34, "Antenna check, LRU swap"),
    "HYD-LEAK-001": ("System Leak", 29, "Locate, classify, repair"),
    "HYD-CNT-002": ("Contamination", 29, "Sample analysis, filter"),
    "HYD-PRS-003": ("Low Pressure", 29, "Pump check, leak check"),
    "HYD-QTY-004": ("Low Quantity", 29, "Check level, leak inspect"),
}

# Model -> code -> primary action, only where the action names equipment
# that model has and the B737 does not.
MODEL_ACTIONS: dict[str, dict[str, str]] = {
    "A220-300": {"AVN-SDR-001": "ADIRU comparison, calibration"},
    "A321neo": {
        "ENG-SDR-001": "EMU diagnostics",
        "ENG-OVH-006": "Borescope, CMC inspect",
        "AVN-SDR-001": "ADIRU comparison",
        "AVN-NAV-004": "Antenna, MMR check",
    },
    "E190": {"AVN-SDR-001": "ADIRU comparison, calibration"},
}

_SEVERITY_ABBREVIATIONS = {"CRITICAL": "CRIT", "MAJOR": "MAJ", "MINOR": "MIN"}


def fault_code_severities(code: FaultCode, model: str) -> tuple[str, ...]:
    """The severities a code's events can carry on one model, worst first."""
    if not code.generated:
        return code.severities
    routed = any(
        route.fault == code.fault and route.weight > 0
        for spec in sensors_for(code.system, model)
        for route in spec.faults
    )
    if not routed:
        raise ValueError(
            f"fault code {code.code}: no {code.system} route raises {code.fault!r} on the {model}"
        )
    # A crossing into any band picks one of the routes on its side, so a
    # routed fault can be raised at every level.
    return tuple(SEVERITY_BY_LEVEL[level] for level in sorted(SEVERITY_BY_LEVEL, reverse=True))


def _fault_codes(system: str, model: str, engine: EngineSpec, stats: Stats) -> str:
    """§7.1 to §7.3: the canonical codes of one system type."""
    actions = MODEL_ACTIONS.get(model, {})
    rows = []
    for code in FAULT_CODES:
        if code.system != system:
            continue
        description, ata, action = _FAULT_CODE_TEXT[code.code]
        severities = fault_code_severities(code, model)
        rows.append(
            (
                code.code,
                description,
                "/".join(_SEVERITY_ABBREVIATIONS[s] for s in severities),
                str(ata),
                actions.get(code.code, action),
            )
        )
    return _table(("Code", "Description", "Severity", "ATA", "Primary Action"), rows)


def _share(count: int, total: int) -> str:
    return f"{round(100 * count / total)}%" if total else "0%"


def _events(count: int) -> str:
    return f"{count} event" if count == 1 else f"{count} events"


def _join(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


# The subject of each system's share sentence in §2.1.
_SHARE_SUBJECTS = {
    "Engine": "engine systems account",
    "Avionics": "avionics accounts",
    "Hydraulics": "the hydraulics system accounts",
}
# How many faults a share sentence names.
_TOP_FAULTS = 3


def _system_shares(system: str, model: str, engine: EngineSpec, stats: Stats) -> str:
    """§2.1.x: a system's share of the model's events, and its top faults."""
    counts = stats["models"][model]
    count, total = counts["by_system"][system], counts["events"]
    lines = [
        f"In the generated fleet data, {_SHARE_SUBJECTS[system]} for {count} of the "
        f"{model}'s {total} maintenance events, or {_share(count, total)}."
    ]
    # Most events first. A tie keeps the faults in name order.
    ranked = sorted(
        ((n, fault) for fault, n in counts["by_fault"][system].items() if n),
        key=lambda item: (-item[0], item[1]),
    )
    named = [
        f"{fault.lower()} with {_events(n) if i == 0 else n}"
        for i, (n, fault) in enumerate(ranked[:_TOP_FAULTS])
    ]
    system_word = system.lower()
    if len(ranked) == 1:
        lines.append(f"All of them are {ranked[0][1].lower()}.")
    elif len(ranked) > _TOP_FAULTS:
        lines.append(f"The most common {system_word} faults are {_join(named)}.")
    elif ranked:
        lines.append(f"The {system_word} faults are {_join(named)}.")
    return " ".join(lines)


FAULT_STATS_PREFIX = "fault-stats-"


def fault_stats_id(code: FaultCode) -> str:
    """The id of the statistics block in the §4 to §6 section of a fault code."""
    return f"{FAULT_STATS_PREFIX}{code.system.lower()}-{code.fault.lower().replace(' ', '-')}"


def _fault_stats(code: FaultCode, model: str, engine: EngineSpec, stats: Stats) -> str:
    """The statistics line of a fault's troubleshooting section."""
    system = code.system.lower()
    fault = code.fault.lower()
    if not code.generated:
        return (
            f"**Fleet Statistics:** The generated fleet data has no {system} {fault} events, "
            "because the data generator does not raise this fault."
        )
    counts = stats["models"][model]
    count, total = counts["by_fault"][code.system][code.fault], counts["by_system"][code.system]
    return (
        f"**Fleet Statistics:** In the generated fleet data, {fault} accounts for {count} of "
        f"the {model}'s {total} {system} maintenance events, or {_share(count, total)}."
    )


def _fleet_statistics(model: str, engine: EngineSpec, stats: Stats) -> str:
    """§10.5: the model's events by severity, system, and fault."""
    config, counts = stats["config"], stats["models"][model]
    total = counts["events"]
    intro = (
        "These figures are counts from this demo's generated fleet data: "
        f"{config['aircraft']} aircraft over {config['days']} days, seed {config['seed']}. "
        f"The {model} has {counts['aircraft']} of the aircraft and {total} of the "
        "maintenance events."
    )
    by_severity, by_system = counts["by_severity"], counts["by_system"]
    severities = [
        (s.title(), str(by_severity[s]), _share(by_severity[s], total)) for s in EVENT_SEVERITIES
    ]
    systems = [(s, str(by_system[s]), _share(by_system[s], total)) for s in SYSTEM_SENSORS]
    # Most events first. A tie goes in system order, then fault name order.
    faults = sorted(
        (
            (n, rank, fault, system)
            for rank, system in enumerate(SYSTEM_SENSORS)
            for fault, n in counts["by_fault"][system].items()
            if n
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    return "\n\n".join(
        (
            intro,
            "**Events by Severity:**",
            _table(("Severity", "Events", "Share"), severities),
            "**Events by System:**",
            _table(("System", "Events", "Share"), systems),
            "**Events by Fault:**",
            _table(
                ("Fault", "System", "Events", "Share"),
                [(fault, system, str(n), _share(n, total)) for n, _, fault, system in faults],
            ),
        )
    )


# Block id -> renderer. Each takes (model, engine spec, fleet stats).
RENDERERS: dict[str, Renderer] = {
    "sensor-table": _sensor_table,
    "egt-trend-note": _egt_trend_note,
    "component-tree": _component_tree,
    "component-ids": _component_ids,
    "vibration-bands": _vibration_bands,
    "vibration-shutdown": _vibration_shutdown,
    "egt-limits": _egt_limits,
    "normal-parameters": _phase_limits,
    "quick-ref-engine": _phase_limits,
    "fuel-flow-range": _fuel_flow_range,
    "quick-ref-hydraulics": _hydraulic_limits,
    "fault-codes-engine": functools.partial(_fault_codes, "Engine"),
    "fault-codes-avionics": functools.partial(_fault_codes, "Avionics"),
    "fault-codes-hydraulics": functools.partial(_fault_codes, "Hydraulics"),
    **{
        f"system-shares-{system.lower()}": functools.partial(_system_shares, system)
        for system in SYSTEM_SENSORS
    },
    **{fault_stats_id(code): functools.partial(_fault_stats, code) for code in FAULT_CODES},
    "fleet-statistics": _fleet_statistics,
}

# Blocks every manual must have, once each. A manual has a fault's statistics
# block only in the section of that fault.
REQUIRED_BLOCKS: tuple[str, ...] = tuple(
    block_id for block_id in RENDERERS if not block_id.startswith(FAULT_STATS_PREFIX)
)

_MARKER = re.compile(r"^<!-- (BEGIN|END) GENERATED: ([a-z0-9-]+) -->$")
# A line that looks like a marker but does not match _MARKER exactly.
_MARKER_LIKE = re.compile(r"^\s*<!--\s*(BEGIN|END)\s+GENERATED", re.IGNORECASE)


class ManualBlockError(ValueError):
    """A manual's block markers are malformed, unknown, or missing."""


def load_stats(manuals_dir: Path = MANUALS_DIR) -> Stats:
    """The fleet statistics the stats blocks render from."""
    return json.loads((manuals_dir / STATS_NAME).read_text(encoding="utf-8"))


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
