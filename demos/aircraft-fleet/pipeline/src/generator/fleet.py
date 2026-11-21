"""Generate the static fleet topology: Aircraft, System, Component, Sensor nodes."""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import count, zip_longest

from .config import GeneratorConfig
from .specs import (
    COMPONENTS_BY_SYSTEM,
    ENGINE_SPECS,
    ENTRY_INTO_SERVICE_RANGES,
    MANUAL_FLEET_TAILS,
    MANUAL_TAIL_ENTRY_INTO_SERVICE,
    MANUAL_TAIL_OPERATORS,
    MANUFACTURER,
    MODEL_DISTRIBUTION,
    OPERATORS,
    UTILIZATION,
    OperatorProfile,
    sensors_for,
)

# Six hex digits are 24 bits. Tests shrink this to force collisions.
_ICAO24_HEX_DIGITS = 6


def icao24(tail_number: str, attempt: int = 0) -> str:
    """Return a 24-bit address as six hex digits, from SHA-256 of the tail.

    The address does not depend on the RNG or the seed, so the A220 manual
    can list it. Attempt 0 hashes the tail itself. A later attempt hashes
    "<tail>#<attempt>" and is used only after a collision.
    """
    key = tail_number if attempt == 0 else f"{tail_number}#{attempt}"
    return hashlib.sha256(key.encode()).hexdigest()[:_ICAO24_HEX_DIGITS]


def _unique_icao24s(tail_numbers: list[str]) -> list[str]:
    """Return one address per tail, unique across the fleet.

    Tails are taken in fleet order. A tail whose address is already taken is
    rehashed with the next attempt number until the address is free. The
    manual registry tails come first, so they always keep attempt 0. A
    smaller fleet is a prefix of a larger one, so each tail keeps its address
    as the fleet grows.
    """
    codes: list[str] = []
    taken: set[str] = set()
    for tail in tail_numbers:
        code = next(code for n in count() if (code := icao24(tail, n)) not in taken)
        taken.add(code)
        codes.append(code)
    return codes


def entry_into_service(model: str, tail_number: str) -> date:
    """Return the tail's entry-into-service date.

    A tail with a manual date gets that date. Any other tail gets a day in
    its model's range, picked from a SHA-256 hash of the tail number. The
    date of a (model, tail) pair is fixed. Which model a generated tail gets
    depends on the seed, so its date can change with the seed.
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
    type: str  # a SensorSpec type, such as EGT or HydPressure
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
    # Flight hours per calendar day, flight hours per cycle, and legs per
    # day. hours_per_day is legs_per_day * hours_per_cycle, so a day's
    # cycles are its legs. Flights, airframe hours, and cycles all follow
    # these. Internal only.
    hours_per_day: float
    hours_per_cycle: float
    legs_per_day: int
    systems: list[SystemNode] = field(default_factory=list)


def _build_system(
    model: str,
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
    specs = [spec for spec in COMPONENTS_BY_SYSTEM[system_type] if spec.fits(model)]
    for comp_index, spec in enumerate(specs, start=1):
        system.components.append(
            ComponentNode(
                component_id=f"{system_id}-C{comp_index:02d}",
                system_id=system_id,
                type=spec.type,
                name=spec.name_for(model),
            )
        )

    # Sensors
    for sensor_index, spec in enumerate(sensors_for(system_type, model), start=1):
        system.sensors.append(
            SensorNode(
                sensor_id=f"{system_id}-SN{sensor_index:02d}",
                system_id=system_id,
                type=spec.type,
                name=spec.name,
                unit=spec.unit,
            )
        )

    return system


def _build_aircraft(
    index: int,
    model: str,
    tail_number: str,
    address: str,
    operator: OperatorProfile,
    utilization: tuple[float, float, int],
) -> AircraftNode:
    aircraft_id = f"AC{1001 + index}"
    engine_type = ENGINE_SPECS[model].engine_type

    aircraft = AircraftNode(
        aircraft_id=aircraft_id,
        tail_number=tail_number,
        icao24=address,
        model=model,
        manufacturer=MANUFACTURER[model],
        operator=operator.name,
        operator_profile=operator,
        entry_into_service=entry_into_service(model, tail_number),
        hours_per_day=utilization[0],
        hours_per_cycle=utilization[1],
        legs_per_day=utilization[2],
    )

    # Two engines
    for i in (1, 2):
        aircraft.systems.append(
            _build_system(model, aircraft_id, i, "Engine", f"{engine_type} #{i}", engine_index=i)
        )

    # Avionics and Hydraulics (no sensors)
    aircraft.systems.append(
        _build_system(model, aircraft_id, 3, "Avionics", "Avionics", engine_index=None)
    )
    aircraft.systems.append(
        _build_system(model, aircraft_id, 4, "Hydraulics", "Hydraulics", engine_index=None)
    )

    return aircraft


def _utilization(model: str, rng: random.Random) -> tuple[float, float, int]:
    """Draw hours per day, hours per cycle, and a whole number of legs per day.

    The legs are a whole number whose block hours fall in the hours-per-day
    range. Hours per day is then exactly legs * hours per cycle.
    """
    jitter = UTILIZATION.cycle_jitter
    hours_per_cycle = UTILIZATION.hours_per_cycle[model] * rng.uniform(1 - jitter, 1 + jitter)
    low, high = UTILIZATION.hours_per_day
    fewest, most = math.ceil(low / hours_per_cycle), math.floor(high / hours_per_cycle)
    if fewest > most:
        raise ValueError(
            f"{model}: no whole number of {hours_per_cycle:.2f}-hour legs "
            f"fills {low}-{high} hours a day"
        )
    legs = rng.randint(fewest, most)
    return legs * hours_per_cycle, hours_per_cycle, legs


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

    icao24s = _unique_icao24s([tail for _, tail in plan])
    utilizations = [_utilization(model, rng) for model, _ in plan]
    return [
        _build_aircraft(i, model, tail, code, op, utilization)
        for i, ((model, tail), code, op, utilization) in enumerate(
            zip(plan, icao24s, operator_assignments, utilizations, strict=True)
        )
    ]
