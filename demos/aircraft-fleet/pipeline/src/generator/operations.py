"""
Flight operations and delay generation.

Hub airports receive disproportionately more routes, producing a realistic
hub-and-spoke network where PageRank and Betweenness centrality produce
non-trivial rankings.

A CRITICAL maintenance event grounds its aircraft from the hour it is
reported to the end of that day. Every leg that would depart in that time is
cancelled, so it has no Flight row. The aircraft flies again the next morning
from the airport where it last landed.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta

from .config import GeneratorConfig
from .fleet import AircraftNode
from .specs import AIRPORTS, DELAY_CAUSE_SPECS

# Each leg's block time is first drawn in this range of the aircraft's hours
# per cycle. The day's legs are then scaled to sum to its hours per day.
_BLOCK_SPREAD = (0.75, 1.25)

_DELAY_WEIGHTS = [spec.weight for spec in DELAY_CAUSE_SPECS]

# Minutes on the ground between legs.
_TURNAROUND_MINUTES = (45, 90)

# The first departure of a day falls between these hours. At most 10 hours
# of flying and 6 turnarounds of 90 minutes fit between 05:00 and midnight.
_FIRST_DEPARTURE = 5.0
_LATEST_FIRST_DEPARTURE = 9.0

# Hub airports get this weight multiplier in route selection.
_HUB_WEIGHT = 4.0

# Events of this severity ground the aircraft for the rest of their day.
_GROUNDING_SEVERITY = "CRITICAL"


def _grounding_starts(
    maintenance_events: Iterable[Mapping[str, str]],
) -> dict[tuple[str, date], datetime]:
    """When each aircraft is grounded on each day, keyed by (aircraft_id, day).

    The value is the day's earliest grounding event. The aircraft stays on
    the ground from then until midnight.
    """
    starts: dict[tuple[str, date], datetime] = {}
    for evt in maintenance_events:
        if evt["severity"] != _GROUNDING_SEVERITY:
            continue
        reported = datetime.fromisoformat(evt["reported_at"])
        key = (evt["aircraft_id"], reported.date())
        starts[key] = min(starts.get(key, reported), reported)
    return starts


def generate_operations(
    fleet: list[AircraftNode],
    config: GeneratorConfig,
    rng: random.Random,
    maintenance_events: Iterable[Mapping[str, str]] = (),
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Generate airports, flights, and delays, with no flights while a CRITICAL event grounds.

    Returns:
        Seven lists: (airport_nodes, flight_nodes, delay_nodes,
        rels_aircraft_flight, rels_flight_departure, rels_flight_arrival,
        rels_flight_delay).
    """
    airports = AIRPORTS[: config.n_airports]
    grounding_starts = _grounding_starts(maintenance_events)

    airport_nodes = [
        {
            ":ID(Airport)": ap.airport_id,
            "name": ap.name,
            "city": ap.city,
            "country": ap.country,
            "iata": ap.iata,
            "icao": ap.icao,
            "lat": ap.lat,
            "lon": ap.lon,
        }
        for ap in airports
    ]

    flight_nodes: list[dict] = []
    delay_nodes: list[dict] = []
    rels_aircraft_flight: list[dict] = []
    rels_departure: list[dict] = []
    rels_arrival: list[dict] = []
    rels_delay: list[dict] = []

    flight_counter = 0
    delay_counter = 0

    for aircraft in fleet:
        delay_rate = aircraft.operator_profile.delay_rate
        # Each aircraft starts at a random hub airport
        current_airport = rng.choices([ap for ap in airports if ap.is_hub])[0]

        # One leg is one cycle, so the legs flown match the cycles counted.
        n_flights = aircraft.legs_per_day

        for day in range(config.n_days):
            raw_blocks = [
                rng.uniform(*_BLOCK_SPREAD) * aircraft.hours_per_cycle for _ in range(n_flights)
            ]
            scale = aircraft.hours_per_day / sum(raw_blocks)
            turnarounds = [rng.randint(*_TURNAROUND_MINUTES) for _ in range(n_flights - 1)]
            # The day's flying, from first departure to last arrival.
            span = aircraft.hours_per_day + sum(turnarounds) / 60
            # First departure from 05:00, late enough in the morning that the
            # last leg lands by midnight. So no leg flies into the next day.
            latest = min(_LATEST_FIRST_DEPARTURE, 24.0 - span)
            # This fires only if the UTILIZATION or turnaround specs change:
            # the current worst case starts at exactly 05:00.
            if latest < _FIRST_DEPARTURE:
                raise ValueError(
                    f"{aircraft.aircraft_id}: {span:.1f} hours of flying a day "
                    f"does not fit between 05:00 and midnight"
                )
            current_time = config.start_date + timedelta(
                days=day, hours=rng.uniform(_FIRST_DEPARTURE, latest)
            )
            grounded_from = grounding_starts.get((aircraft.aircraft_id, current_time.date()))

            for leg, raw_block in enumerate(raw_blocks):
                # A grounded aircraft cancels this leg and the rest of the day's.
                if grounded_from is not None and current_time >= grounded_from:
                    break
                # Weighted destination selection: hubs attract more traffic.
                candidates = [ap for ap in airports if ap.airport_id != current_airport.airport_id]
                candidate_weights = [_HUB_WEIGHT if ap.is_hub else 1.0 for ap in candidates]
                destination = rng.choices(candidates, weights=candidate_weights)[0]

                flight_counter += 1
                flight_id = f"FL{flight_counter:05d}"
                block_hours = raw_block * scale
                departure = current_time
                arrival = departure + timedelta(hours=block_hours)

                flight_number = f"{aircraft.operator[:2].upper()}{rng.randint(100, 999)}"

                flight_nodes.append(
                    {
                        ":ID(Flight)": flight_id,
                        "flight_number": flight_number,
                        "aircraft_id": aircraft.aircraft_id,
                        "operator": aircraft.operator,
                        "origin": current_airport.iata,
                        "destination": destination.iata,
                        "scheduled_departure": departure.strftime("%Y-%m-%dT%H:%M:%S"),
                        "scheduled_arrival": arrival.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                )
                rels_aircraft_flight.append(
                    {":START_ID(Aircraft)": aircraft.aircraft_id, ":END_ID(Flight)": flight_id}
                )
                rels_departure.append(
                    {":START_ID(Flight)": flight_id, ":END_ID(Airport)": current_airport.airport_id}
                )
                rels_arrival.append(
                    {":START_ID(Flight)": flight_id, ":END_ID(Airport)": destination.airport_id}
                )

                # The operator's quality scales the delay probability.
                if rng.random() < delay_rate:
                    delay_counter += 1
                    spec = rng.choices(DELAY_CAUSE_SPECS, weights=_DELAY_WEIGHTS)[0]
                    minutes = rng.randint(spec.min_minutes, spec.max_minutes)
                    delay_id = f"DLY{delay_counter:05d}"
                    delay_nodes.append(
                        {":ID(Delay)": delay_id, "cause": spec.cause, "minutes": minutes}
                    )
                    rels_delay.append({":START_ID(Flight)": flight_id, ":END_ID(Delay)": delay_id})

                current_airport = destination
                if leg < len(turnarounds):
                    current_time = arrival + timedelta(minutes=turnarounds[leg])

    return (
        airport_nodes,
        flight_nodes,
        delay_nodes,
        rels_aircraft_flight,
        rels_departure,
        rels_arrival,
        rels_delay,
    )
