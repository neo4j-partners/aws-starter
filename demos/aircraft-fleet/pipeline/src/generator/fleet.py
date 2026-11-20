"""Generate the static fleet topology: Aircraft, System, Component, Sensor nodes."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import count, zip_longest

from .config import GeneratorConfig
from .specs import (
    COMPONENT_TYPES_BY_SYSTEM,
    ENTRY_INTO_SERVICE_RANGES,
    MANUAL_FLEET_TAILS,
    MANUAL_TAIL_ENTRY_INTO_SERVICE,
    MANUAL_TAIL_OPERATORS,
    MANUFACTURER,
    MODEL_DISTRIBUTION,
    OPERATORS,
    OperatorProfile,
)


def icao24(tail_number: str) -> str:
    """Return a 24-bit address as six hex digits, from SHA-256 of the tail.

    The address does not depend on the RNG, the seed, or the fleet size, so
    the A220 manual can list it.
    """
    return hashlib.sha256(tail_number.encode()).hexdigest()[:6]


def entry_into_service(model: str, tail_number: str) -> date:
    """Return the tail's entry-into-service date.

    A tail with a manual date gets that date. Any other tail gets a day in
    its model's range, picked from a SHA-256 hash of the tail number, so the
    date does not depend on the RNG, the seed, or the fleet size.
    """
    if tail_number in MANUAL_TAIL_ENTRY_INTO_SERVICE:
        return MANUAL_TAIL_ENTRY_INTO_SERVICE[tail_number]
    first, last = ENTRY_INTO_SERVICE_RANGES[model]
    digest = hashlib.sha256(f"entry-into-service:{tail_number}".encode()).digest()
    offset = int.from_bytes(digest[:8], "big") % ((last - first).days + 1)
    return first + timedelta(days=offset)


def _registry_fleet() -> list[tuple[str, str]]:
    """Return (model, tail) pairs for every manual tail, interleaved by model.

    The order is round-robin across MANUAL_FLEET_TAILS, so AC1001 to AC1005
    hold the first tail of each model. Models with more tails fill the end.
    """
    columns = [[(model, tail) for tail in tails] for model, tails in MANUAL_FLEET_TAILS.items()]
    return [pair for row in zip_longest(*columns) for pair in row if pair is not None]


def _distribute(n: int) -> list[str]:
    """Split n aircraft across MODEL_DISTRIBUTION with largest-remainder rounding."""
    quotas = [(model, n * fraction) for model, fraction in MODEL_DISTRIBUTION]
    counts = {model: int(quota) for model, quota in quotas}
    shortfall = n - sum(counts.values())
    by_remainder = sorted(quotas, key=lambda mq: mq[1] - int(mq[1]), reverse=True)
    for model, _ in by_remainder[:shortfall]:
        counts[model] += 1
    return [model for model, _ in MODEL_DISTRIBUTION for _ in range(counts[model])]


def _generated_tails(registry_tails: set[str]) -> Iterator[str]:
    """Yield N90000, N90001, ... skipping any manual tail.

    No manual uses this block, so generated tails stay apart from the
    E190 (N100xx) and A220 (N2000x) manual tails.
    """
    return (tail for tail in (f"N{i}" for i in count(90000)) if tail not in registry_tails)


@dataclass
class SensorNode:
    sensor_id: str
    system_id: str
    type: str  # EGT | Vibration | N1Speed | FuelFlow
    name: str
    unit: str


@dataclass
class ComponentNode:
    component_id: str
    system_id: str
    type: str
    name: str


@dataclass
class SystemNode:
    system_id: str
    aircraft_id: str
    type: str  # Engine | Avionics | Hydraulics
    name: str
    engine_index: int | None  # 1 or 2 for Engine systems, None otherwise
    sensors: list[SensorNode] = field(default_factory=list)
    components: list[ComponentNode] = field(default_factory=list)


@dataclass
class AircraftNode:
    aircraft_id: str
    tail_number: str
    icao24: str
    model: str
    manufacturer: str
    operator: str
    operator_profile: OperatorProfile
    # Internal only: not written to the CSVs or the graph.
    entry_into_service: date
    systems: list[SystemNode] = field(default_factory=list)


_SENSOR_TYPES: list[tuple[str, str, str]] = [
    ("EGT", "Exhaust Gas Temperature", "C"),
    ("Vibration", "Engine Vibration", "ips"),
    ("N1Speed", "Fan Speed N1", "rpm"),
    ("FuelFlow", "Fuel Flow", "kg/s"),
]

_ENGINE_NAMES: dict[str, list[str]] = {
    "B737-800": ["CFM56-7B #1", "CFM56-7B #2"],
    "A320-200": ["CFM56-5B #1", "CFM56-5B #2"],
    "A321neo": ["LEAP-1A #1", "LEAP-1A #2"],
    "E190": ["CF34-10E #1", "CF34-10E #2"],
    "A220-300": ["PW1500G #1", "PW1500G #2"],
}


def _build_system(
    aircraft_id: str,
    system_index: int,
    system_type: str,
    system_name: str,
    engine_index: int | None,
) -> SystemNode:
    system_id = f"{aircraft_id}-S{system_index:02d}"
    system = SystemNode(
        system_id=system_id,
        aircraft_id=aircraft_id,
        type=system_type,
        name=system_name,
        engine_index=engine_index,
    )

    # Components
    for comp_index, comp_type in enumerate(COMPONENT_TYPES_BY_SYSTEM[system_type], start=1):
        system.components.append(
            ComponentNode(
                component_id=f"{system_id}-C{comp_index:02d}",
                system_id=system_id,
                type=comp_type,
                name=comp_type,
            )
        )

    # Sensors (engines only)
    if system_type == "Engine":
        for sensor_index, (s_type, s_name, s_unit) in enumerate(_SENSOR_TYPES, start=1):
            system.sensors.append(
                SensorNode(
                    sensor_id=f"{system_id}-SN{sensor_index:02d}",
                    system_id=system_id,
                    type=s_type,
                    name=s_name,
                    unit=s_unit,
                )
            )

    return system


def _build_aircraft(
    index: int, model: str, tail_number: str, operator: OperatorProfile
) -> AircraftNode:
    aircraft_id = f"AC{1001 + index}"
    engine_names = _ENGINE_NAMES[model]

    aircraft = AircraftNode(
        aircraft_id=aircraft_id,
        tail_number=tail_number,
        icao24=icao24(tail_number),
        model=model,
        manufacturer=MANUFACTURER[model],
        operator=operator.name,
        operator_profile=operator,
        entry_into_service=entry_into_service(model, tail_number),
    )

    # Two engines
    for i, ename in enumerate(engine_names, start=1):
        aircraft.systems.append(_build_system(aircraft_id, i, "Engine", ename, engine_index=i))

    # Avionics and Hydraulics (no sensors)
    aircraft.systems.append(
        _build_system(aircraft_id, 3, "Avionics", "Avionics Suite", engine_index=None)
    )
    aircraft.systems.append(
        _build_system(aircraft_id, 4, "Hydraulics", "Hydraulics System", engine_index=None)
    )

    return aircraft


def generate_fleet(config: GeneratorConfig) -> list[AircraftNode]:
    """Build the fleet: the manual registry aircraft first, then the rest.

    The first aircraft carry the manual tails in a fixed order, each with the
    operator its manual names. Any aircraft beyond the registry follow
    MODEL_DISTRIBUTION in a shuffled order, with shuffled operators.
    """
    rng = random.Random(config.seed)

    full_registry = _registry_fleet()
    registry = full_registry[: config.n_aircraft]
    extra_models = _distribute(config.n_aircraft - len(registry))
    rng.shuffle(extra_models)
    tails = _generated_tails({tail for _, tail in full_registry})
    plan = [*registry, *((model, next(tails)) for model in extra_models)]

    # Registry tails keep their manual operator. Extra aircraft get operators
    # round-robin, then shuffled, so each operator gets a similar share.
    operators_by_name = {op.name: op for op in OPERATORS}
    extra_operators = [OPERATORS[i % len(OPERATORS)] for i in range(len(extra_models))]
    rng.shuffle(extra_operators)
    operator_assignments = [
        *(operators_by_name[MANUAL_TAIL_OPERATORS[tail]] for _, tail in registry),
        *extra_operators,
    ]

    return [
        _build_aircraft(i, model, tail, op)
        for i, ((model, tail), op) in enumerate(zip(plan, operator_assignments, strict=True))
    ]
