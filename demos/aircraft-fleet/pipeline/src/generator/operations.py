"""
Flight operations and delay generation.

Hub airports receive disproportionately more routes, producing a realistic
hub-and-spoke network where PageRank and Betweenness centrality produce
non-trivial rankings.
"""

from __future__ import annotations

import random
from datetime import timedelta

from .config import GeneratorConfig
from .fleet import AircraftNode
from .specs import AIRPORTS, DELAY_CAUSE_SPECS

# Each leg's block time is first drawn in this range of the aircraft's hours
# per cycle. The day's legs are then scaled to sum to its hours per day.
_BLOCK_SPREAD = (0.75, 1.25)

_DELAY_WEIGHTS = [spec.weight for spec in DELAY_CAUSE_SPECS]

# Hub airports get this weight multiplier in route selection
_HUB_WEIGHT = 4.0


def generate_operations(
    fleet: list[AircraftNode],
    config: GeneratorConfig,
    rng: random.Random,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """
    Returns (airport_nodes, flight_nodes, delay_nodes,
             rels_aircraft_flight, rels_flight_departure, rels_flight_arrival,
             rels_flight_delay)

    Actually returns six lists — see return statement.
    """
    airports = AIRPORTS[: config.n_airports]

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
        current_time = config.start_date

        for day in range(config.n_days):
            raw_blocks = [
                rng.uniform(*_BLOCK_SPREAD) * aircraft.hours_per_cycle for _ in range(n_flights)
            ]
            scale = aircraft.hours_per_day / sum(raw_blocks)
            # First departure between 06:00 and 09:00, but never before the
            # previous day's last leg has landed and turned around.
            current_time = max(
                current_time,
                config.start_date + timedelta(days=day, hours=rng.uniform(6.0, 9.0)),
            )

            for raw_block in raw_blocks:
                # Weighted destination selection — hubs attract more traffic
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

                # Delays — probability scaled by operator quality
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
                # Turnaround time: 45–90 minutes on ground
                current_time = arrival + timedelta(minutes=rng.randint(45, 90))

    return (
        airport_nodes,
        flight_nodes,
        delay_nodes,
        rels_aircraft_flight,
        rels_departure,
        rels_arrival,
        rels_delay,
    )
