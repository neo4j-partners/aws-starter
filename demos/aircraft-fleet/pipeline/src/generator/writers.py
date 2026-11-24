"""CSV writing utilities."""

from __future__ import annotations

import csv
from pathlib import Path

# Header for every CSV written through write_csv, keyed by file name. Keeping
# the columns here means an empty result still gets a header row, which the
# loader needs to read the file.
CSV_COLUMNS: dict[str, list[str]] = {
    "nodes_aircraft.csv": [
        ":ID(Aircraft)",
        "tail_number",
        "icao24",
        "model",
        "manufacturer",
        "operator",
    ],
    "nodes_systems.csv": [":ID(System)", "aircraft_id", "type", "name"],
    "nodes_components.csv": [":ID(Component)", "system_id", "type", "name"],
    "nodes_sensors.csv": [":ID(Sensor)", "system_id", "type", "name", "unit"],
    "operating_limits.csv": [
        "name",
        "parameterName",
        "regime",
        "aircraftType",
        "unit",
        "minValue",
        "maxValue",
        "nominalValue",
        "sourceBlock",
        "sourceText",
    ],
    "nodes_maintenance.csv": [
        ":ID(MaintenanceEvent)",
        "component_id",
        "system_id",
        "aircraft_id",
        "fault",
        "severity",
        "reported_at",
        "corrective_action",
    ],
    "nodes_airports.csv": [
        ":ID(Airport)",
        "name",
        "city",
        "country",
        "iata",
        "icao",
        "lat",
        "lon",
    ],
    "nodes_flights.csv": [
        ":ID(Flight)",
        "flight_number",
        "aircraft_id",
        "operator",
        "origin",
        "destination",
        "scheduled_departure",
        "scheduled_arrival",
    ],
    "nodes_delays.csv": [":ID(Delay)", "cause", "minutes"],
    "nodes_removals.csv": [
        ":ID(Removal)",
        "RMV_TRK_NO",
        "RMV_REA_TX",
        "component_id",
        "aircraft_id",
        "removal_date",
        "work_order_number",
        "technician_id",
        "part_number",
        "serial_number",
        "time_since_install",
        "flight_hours_at_removal",
        "flight_cycles_at_removal",
        "replacement_required",
        "shop_visit_required",
        "warranty_status",
        "removal_priority",
        "cost_estimate",
        "installation_date",
    ],
    "rels_aircraft_system.csv": [":START_ID(Aircraft)", ":END_ID(System)"],
    "rels_system_component.csv": [":START_ID(System)", ":END_ID(Component)"],
    "rels_system_sensor.csv": [":START_ID(System)", ":END_ID(Sensor)"],
    "rels_component_event.csv": [
        ":START_ID(Component)",
        ":END_ID(MaintenanceEvent)",
    ],
    "rels_event_system.csv": [":START_ID(MaintenanceEvent)", ":END_ID(System)"],
    "rels_event_aircraft.csv": [
        ":START_ID(MaintenanceEvent)",
        ":END_ID(Aircraft)",
    ],
    "rels_aircraft_flight.csv": [":START_ID(Aircraft)", ":END_ID(Flight)"],
    "rels_flight_departure.csv": [":START_ID(Flight)", ":END_ID(Airport)"],
    "rels_flight_arrival.csv": [":START_ID(Flight)", ":END_ID(Airport)"],
    "rels_flight_delay.csv": [":START_ID(Flight)", ":END_ID(Delay)"],
    "rels_aircraft_removal.csv": [
        ":START_ID(Aircraft)",
        ":END_ID(Removal)",
    ],
    "rels_component_removal.csv": [
        ":START_ID(Removal)",
        ":END_ID(Component)",
    ],
}


def write_csv(rows: list[dict], path: Path) -> int:
    """Write rows to a CSV file under its registered header.

    The header row is always written, even when ``rows`` is empty.

    Returns:
        The number of rows written.

    Raises:
        KeyError: If ``path.name`` has no entry in ``CSV_COLUMNS``.
        ValueError: If the rows' keys do not match the registered columns.
    """
    columns = CSV_COLUMNS[path.name]
    if rows and list(rows[0]) != columns:
        raise ValueError(
            f"{path.name}: row keys {list(rows[0])} do not match CSV_COLUMNS {columns}"
        )
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
