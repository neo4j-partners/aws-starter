"""
Component removal records generation using Faker for realistic text fields.

Removals are loosely correlated with maintenance events: aircraft with more
critical events have a higher removal rate.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from faker import Faker

from .config import GeneratorConfig
from .fleet import AircraftNode
from .specs import ENTRY_INTO_SERVICE_RANGES

_fake = Faker()
_fake.seed_instance(0)  # overridden per-call via seed

_PRIORITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
_PRIORITY_WEIGHTS = [0.10, 0.30, 0.40, 0.20]

_WARRANTY = ["IN_WARRANTY", "OUT_WARRANTY"]
_WARRANTY_WEIGHTS = [0.35, 0.65]

# Removals per aircraft per year (approx) — scaled to config.n_days
_BASE_REMOVALS_PER_YEAR = 4

# Flight hours per calendar day. Each aircraft draws one rate, which turns
# days since entry into service into airframe hours, and flight hours since
# install into days since install.
_UTILIZATION_HOURS_PER_DAY = (8.0, 10.0)
# Fewest flight hours since install: about 90 days at 8 hours a day.
_MIN_HOURS_SINCE_INSTALL = 720

# Hours since install are drawn from [_MIN_HOURS_SINCE_INSTALL, airframe
# hours - 1]. The latest entry into service, at the lowest rate, must still
# give more airframe hours than that minimum by the start of the data window.
_LATEST_ENTRY_INTO_SERVICE = max(last for _, last in ENTRY_INTO_SERVICE_RANGES.values())


def _check_start_date(config: GeneratorConfig) -> None:
    """Raise ValueError if the window opens too soon after the latest entry into service."""
    days = (config.start_date.date() - _LATEST_ENTRY_INTO_SERVICE).days
    if days * _UTILIZATION_HOURS_PER_DAY[0] <= _MIN_HOURS_SINCE_INSTALL:
        raise ValueError(
            f"start_date {config.start_date.date()} is too soon after the latest entry "
            f"into service, {_LATEST_ENTRY_INTO_SERVICE}: an aircraft needs more than "
            f"{_MIN_HOURS_SINCE_INSTALL} airframe hours when the data window opens"
        )


def _part_number(rng: random.Random) -> str:
    prefix = rng.choice(["P", "PN", "PT", "PNR"])
    return f"{prefix}{rng.randint(10000, 99999)}-{rng.randint(1, 999):03d}"


def _serial_number() -> str:
    return f"SN{_fake.bothify('??######').upper()}"


def _work_order(date: datetime, seq: int) -> str:
    return f"WO{date.strftime('%y%m')}-{seq:04d}"


def generate_removals(
    fleet: list[AircraftNode],
    maintenance_events: list[dict],
    config: GeneratorConfig,
    rng: random.Random,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Returns (removal_nodes, rels_aircraft_removal, rels_component_removal).

    Raises ValueError if config.start_date leaves too few airframe hours.
    """
    _check_start_date(config)
    _fake.seed_instance(config.seed + 999)

    # Count critical events per aircraft to modulate removal rate
    critical_by_aircraft: dict[str, int] = {}
    for evt in maintenance_events:
        aid = evt["aircraft_id"]
        if evt["severity"] == "CRITICAL":
            critical_by_aircraft[aid] = critical_by_aircraft.get(aid, 0) + 1

    removal_nodes: list[dict] = []
    rels_aircraft: list[dict] = []
    rels_component: list[dict] = []
    removal_counter = 0
    wo_seq = 1

    year_fraction = config.n_days / 365.0

    for aircraft in fleet:
        # More critical events → slightly more removals
        multiplier = 1.0 + 0.15 * critical_by_aircraft.get(aircraft.aircraft_id, 0)
        n_removals = max(1, round(_BASE_REMOVALS_PER_YEAR * year_fraction * multiplier))

        all_components = [comp for system in aircraft.systems for comp in system.components]
        # One rate per aircraft, so airframe hours grow with the removal date.
        utilization = rng.uniform(*_UTILIZATION_HOURS_PER_DAY)
        in_service = datetime.combine(aircraft.entry_into_service, datetime.min.time())

        # Each component is removed at most once in the window, so its install
        # and removal dates never overlap another removal of the same part.
        removed = rng.sample(all_components, min(n_removals, len(all_components)))

        for component in removed:
            removal_counter += 1
            removal_id = f"RE{removal_counter:06d}"

            removal_date = config.start_date + timedelta(
                days=rng.randint(0, config.n_days - 1),
                hours=rng.randint(6, 18),
            )
            # Airframe hours are the days in service at the aircraft's rate.
            days_in_service = (removal_date - in_service).total_seconds() / 86400
            flight_hours_at_removal = int(days_in_service * utilization)
            # Flight hours since install stay below the airframe total. The
            # install date follows from them at the same rate, so it falls
            # after entry into service, and the hours and the date agree.
            hours_since_install = rng.randint(_MIN_HOURS_SINCE_INSTALL, flight_hours_at_removal - 1)
            install_date = removal_date - timedelta(days=hours_since_install / utilization)

            priority = rng.choices(_PRIORITIES, weights=_PRIORITY_WEIGHTS)[0]
            warranty = rng.choices(_WARRANTY, weights=_WARRANTY_WEIGHTS)[0]

            base_cost = rng.randint(3000, 60000)
            cost_mult = {"CRITICAL": 2.2, "HIGH": 1.6, "MEDIUM": 1.0, "LOW": 0.5}[priority]

            removal_nodes.append(
                {
                    ":ID(Removal)": removal_id,
                    "RMV_TRK_NO": f"RMV{removal_date.strftime('%y%m%d')}{removal_counter:06d}",
                    "RMV_REA_TX": _fake.sentence(nb_words=8).rstrip("."),
                    "component_id": component.component_id,
                    "aircraft_id": aircraft.aircraft_id,
                    "removal_date": removal_date.strftime("%Y-%m-%dT%H:%M:%S"),
                    "work_order_number": _work_order(removal_date, wo_seq),
                    "technician_id": _fake.name(),
                    "part_number": _part_number(rng),
                    "serial_number": _serial_number(),
                    "time_since_install": hours_since_install,
                    "flight_hours_at_removal": flight_hours_at_removal,
                    "flight_cycles_at_removal": rng.randint(200, 4000),
                    "replacement_required": rng.random() < 0.85,
                    "shop_visit_required": rng.random() < 0.60,
                    "warranty_status": warranty,
                    "removal_priority": priority,
                    "cost_estimate": int(base_cost * cost_mult),
                    "installation_date": install_date.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )
            rels_aircraft.append(
                {":START_ID(Aircraft)": aircraft.aircraft_id, ":END_ID(Removal)": removal_id}
            )
            rels_component.append(
                {
                    ":START_ID(Removal)": removal_id,
                    ":END_ID(Component)": component.component_id,
                }
            )
            wo_seq += 1

    return removal_nodes, rels_aircraft, rels_component
