"""CSV reading, batched loading, database clearing, and verification."""

from __future__ import annotations

import csv
import errno
import fcntl
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from itertools import batched
from pathlib import Path
from typing import Any, TextIO

from neo4j import READ_ACCESS, Driver, NotificationDisabledClassification
from neo4j.exceptions import Neo4jError

from generator.stamp import (
    LOCK_NAME,
    STAMP_NAME,
    GenerateRunningError,
    read_stamp,
    stamp_differences,
)

from .schema import CONSTRAINTS, EXTRACTION_CONSTRAINTS, UNIQUENESS_CONSTRAINT_TYPES

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000
OPERATIONAL_LABELS = [
    "Aircraft",
    "System",
    "Component",
    "Sensor",
    "Reading",
    "Airport",
    "Flight",
    "Delay",
    "MaintenanceEvent",
    "Removal",
]
ENRICHMENT_LABELS = [
    "Document",
    "Chunk",
    "AircraftModel",
    "SystemReference",
    "ComponentReference",
    "Fault",
    "MaintenanceProcedure",
    "OperatingLimit",
]
OPERATIONAL_RELATIONSHIP_TYPES = [
    "HAS_SYSTEM",
    "HAS_COMPONENT",
    "HAS_SENSOR",
    "HAS_READING",
    "HAS_EVENT",
    "OPERATES_FLIGHT",
    "DEPARTS_FROM",
    "ARRIVES_AT",
    "HAS_DELAY",
    "AFFECTS_SYSTEM",
    "AFFECTS_AIRCRAFT",
    "HAS_REMOVAL",
    "REMOVED_COMPONENT",
]
ENRICHMENT_RELATIONSHIP_TYPES = [
    "FROM_DOCUMENT",
    "APPLIES_TO",
    "DESCRIBES_MODEL",
    "DESCRIBES_SYSTEM",
    "DESCRIBES_COMPONENT",
    "HAS_LIMIT",
]
RELATIONSHIP_TYPES = [*OPERATIONAL_RELATIONSHIP_TYPES, *ENRICHMENT_RELATIONSHIP_TYPES]
REQUIRED_INDEXES = [
    "maintenanceChunkEmbeddings",
    "maintenanceChunkText",
]
REQUIRED_CONSTRAINTS = [*CONSTRAINTS, *EXTRACTION_CONSTRAINTS]

# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


def iter_csv_batches(data_dir: Path, filename: str) -> Iterator[list[dict[str, str]]]:
    """Stream a CSV file as lists of at most BATCH_SIZE row dicts.

    Only one batch is held in memory at a time. Full-mode readings reach
    about 1.7M rows, so reading the whole file at once is too costly.
    """
    with (data_dir / filename).open(newline="", encoding="utf-8") as f:
        for batch in batched(csv.DictReader(f), BATCH_SIZE):
            yield list(batch)


def _run_in_batches(
    driver: Driver, database: str, batches: Iterator[list[dict[str, str]]], query: str
) -> tuple[int, int]:
    """Execute a Cypher query once per batch.

    Returns the total row count and the number of skipped rows. A query
    reports skipped rows by returning a ``skipped`` column.
    """
    total = skipped = 0
    for batch in batches:
        records, _, _ = driver.execute_query(query, batch=batch, database_=database)
        skipped += sum(record.get("skipped", 0) for record in records)
        total += len(batch)
        print(f"  Progress: {total:,} rows", end="\r")
    print()
    return total, skipped


# ---------------------------------------------------------------------------
# Node loading. Reading rows also create their HAS_READING relationship,
# so the large readings CSV is read only once. A reading whose sensor_id
# matches no Sensor is skipped and counted.
# ---------------------------------------------------------------------------

_NODE_DEFINITIONS: list[tuple[str, str, str]] = [
    (
        "Aircraft",
        "nodes_aircraft.csv",
        """
        UNWIND $batch AS row
        MERGE (a:Aircraft {aircraft_id: row[':ID(Aircraft)']})
        SET a.tail_number = row['tail_number'],
            a.icao24 = row['icao24'],
            a.model = row['model'],
            a.manufacturer = row['manufacturer'],
            a.operator = row['operator']
        """,
    ),
    (
        "System",
        "nodes_systems.csv",
        """
        UNWIND $batch AS row
        MERGE (s:System {system_id: row[':ID(System)']})
        SET s.aircraft_id = row['aircraft_id'],
            s.type = row['type'],
            s.name = row['name']
        """,
    ),
    (
        "Component",
        "nodes_components.csv",
        """
        UNWIND $batch AS row
        MERGE (c:Component {component_id: row[':ID(Component)']})
        SET c.system_id = row['system_id'],
            c.type = row['type'],
            c.name = row['name']
        """,
    ),
    (
        "Sensor",
        "nodes_sensors.csv",
        """
        UNWIND $batch AS row
        MERGE (s:Sensor {sensor_id: row[':ID(Sensor)']})
        SET s.system_id = row['system_id'],
            s.type = row['type'],
            s.name = row['name'],
            s.unit = row['unit']
        """,
    ),
    (
        "Reading",
        "nodes_readings.csv",
        """
        UNWIND $batch AS row
        OPTIONAL MATCH (s:Sensor {sensor_id: row['sensor_id']})
        CALL (row, s) {
            WITH row, s
            WHERE s IS NOT NULL
            MERGE (r:Reading {reading_id: row['reading_id']})
            SET r.sensor_id = row['sensor_id'],
                r.timestamp = row['ts'],
                r.value = toFloat(row['value'])
            MERGE (s)-[:HAS_READING]->(r)
        }
        RETURN count(*) - count(s) AS skipped
        """,
    ),
    (
        "Airport",
        "nodes_airports.csv",
        """
        UNWIND $batch AS row
        MERGE (a:Airport {airport_id: row[':ID(Airport)']})
        SET a.name = row['name'],
            a.city = row['city'],
            a.country = row['country'],
            a.iata = row['iata'],
            a.icao = row['icao'],
            a.lat = toFloat(row['lat']),
            a.lon = toFloat(row['lon'])
        """,
    ),
    (
        "Flight",
        "nodes_flights.csv",
        """
        UNWIND $batch AS row
        MERGE (f:Flight {flight_id: row[':ID(Flight)']})
        SET f.flight_number = row['flight_number'],
            f.aircraft_id = row['aircraft_id'],
            f.operator = row['operator'],
            f.origin = row['origin'],
            f.destination = row['destination'],
            f.scheduled_departure = row['scheduled_departure'],
            f.scheduled_arrival = row['scheduled_arrival']
        """,
    ),
    (
        "Delay",
        "nodes_delays.csv",
        """
        UNWIND $batch AS row
        MERGE (d:Delay {delay_id: row[':ID(Delay)']})
        SET d.cause = row['cause'],
            d.minutes = toInteger(row['minutes'])
        """,
    ),
    (
        "MaintenanceEvent",
        "nodes_maintenance.csv",
        """
        UNWIND $batch AS row
        MERGE (m:MaintenanceEvent {event_id: row[':ID(MaintenanceEvent)']})
        SET m.component_id = row['component_id'],
            m.system_id = row['system_id'],
            m.aircraft_id = row['aircraft_id'],
            m.fault = row['fault'],
            m.severity = row['severity'],
            m.reported_at = row['reported_at'],
            m.corrective_action = row['corrective_action']
        """,
    ),
    (
        "Removal",
        "nodes_removals.csv",
        """
        UNWIND $batch AS row
        MERGE (r:Removal {removal_id: row[':ID(Removal)']})
        SET r.tracking_number = row['RMV_TRK_NO'],
            r.component_id = row['component_id'],
            r.aircraft_id = row['aircraft_id'],
            r.removal_date = row['removal_date'],
            r.reason = row['RMV_REA_TX'],
            r.work_order_number = row['work_order_number'],
            r.technician_id = row['technician_id'],
            r.part_number = row['part_number'],
            r.serial_number = row['serial_number'],
            r.hours_since_install = toFloat(row['time_since_install']),
            r.flight_hours_at_removal = toFloat(row['flight_hours_at_removal']),
            r.flight_cycles_at_removal = toInteger(row['flight_cycles_at_removal']),
            r.replacement_required = toBoolean(row['replacement_required']),
            r.shop_visit_required = toBoolean(row['shop_visit_required']),
            r.warranty_status = row['warranty_status'],
            r.removal_priority = row['removal_priority'],
            r.cost_estimate = toFloat(row['cost_estimate']),
            r.installation_date = row['installation_date']
        """,
    ),
]

# ---------------------------------------------------------------------------
# Relationship loading. The Cypher matches notebook 02 exactly.
# ---------------------------------------------------------------------------

_REL_DEFINITIONS: list[tuple[str, str, str]] = [
    (
        "HAS_SYSTEM",
        "rels_aircraft_system.csv",
        """
        UNWIND $batch AS row
        MATCH (a:Aircraft {aircraft_id: row[':START_ID(Aircraft)']})
        MATCH (s:System {system_id: row[':END_ID(System)']})
        MERGE (a)-[:HAS_SYSTEM]->(s)
        """,
    ),
    (
        "HAS_COMPONENT",
        "rels_system_component.csv",
        """
        UNWIND $batch AS row
        MATCH (s:System {system_id: row[':START_ID(System)']})
        MATCH (c:Component {component_id: row[':END_ID(Component)']})
        MERGE (s)-[:HAS_COMPONENT]->(c)
        """,
    ),
    (
        "HAS_SENSOR",
        "rels_system_sensor.csv",
        """
        UNWIND $batch AS row
        MATCH (s:System {system_id: row[':START_ID(System)']})
        MATCH (sn:Sensor {sensor_id: row[':END_ID(Sensor)']})
        MERGE (s)-[:HAS_SENSOR]->(sn)
        """,
    ),
    (
        "HAS_EVENT",
        "rels_component_event.csv",
        """
        UNWIND $batch AS row
        MATCH (c:Component {component_id: row[':START_ID(Component)']})
        MATCH (m:MaintenanceEvent {event_id: row[':END_ID(MaintenanceEvent)']})
        MERGE (c)-[:HAS_EVENT]->(m)
        """,
    ),
    (
        "OPERATES_FLIGHT",
        "rels_aircraft_flight.csv",
        """
        UNWIND $batch AS row
        MATCH (a:Aircraft {aircraft_id: row[':START_ID(Aircraft)']})
        MATCH (f:Flight {flight_id: row[':END_ID(Flight)']})
        MERGE (a)-[:OPERATES_FLIGHT]->(f)
        """,
    ),
    (
        "DEPARTS_FROM",
        "rels_flight_departure.csv",
        """
        UNWIND $batch AS row
        MATCH (f:Flight {flight_id: row[':START_ID(Flight)']})
        MATCH (a:Airport {airport_id: row[':END_ID(Airport)']})
        MERGE (f)-[:DEPARTS_FROM]->(a)
        """,
    ),
    (
        "ARRIVES_AT",
        "rels_flight_arrival.csv",
        """
        UNWIND $batch AS row
        MATCH (f:Flight {flight_id: row[':START_ID(Flight)']})
        MATCH (a:Airport {airport_id: row[':END_ID(Airport)']})
        MERGE (f)-[:ARRIVES_AT]->(a)
        """,
    ),
    (
        "HAS_DELAY",
        "rels_flight_delay.csv",
        """
        UNWIND $batch AS row
        MATCH (f:Flight {flight_id: row[':START_ID(Flight)']})
        MATCH (d:Delay {delay_id: row[':END_ID(Delay)']})
        MERGE (f)-[:HAS_DELAY]->(d)
        """,
    ),
    (
        "AFFECTS_SYSTEM",
        "rels_event_system.csv",
        """
        UNWIND $batch AS row
        MATCH (m:MaintenanceEvent {event_id: row[':START_ID(MaintenanceEvent)']})
        MATCH (s:System {system_id: row[':END_ID(System)']})
        MERGE (m)-[:AFFECTS_SYSTEM]->(s)
        """,
    ),
    (
        "AFFECTS_AIRCRAFT",
        "rels_event_aircraft.csv",
        """
        UNWIND $batch AS row
        MATCH (m:MaintenanceEvent {event_id: row[':START_ID(MaintenanceEvent)']})
        MATCH (a:Aircraft {aircraft_id: row[':END_ID(Aircraft)']})
        MERGE (m)-[:AFFECTS_AIRCRAFT]->(a)
        """,
    ),
    (
        "HAS_REMOVAL",
        "rels_aircraft_removal.csv",
        """
        UNWIND $batch AS row
        MATCH (a:Aircraft {aircraft_id: row[':START_ID(Aircraft)']})
        MATCH (r:Removal {removal_id: row[':END_ID(Removal)']})
        MERGE (a)-[:HAS_REMOVAL]->(r)
        """,
    ),
    (
        "REMOVED_COMPONENT",
        "rels_component_removal.csv",
        """
        UNWIND $batch AS row
        MATCH (r:Removal {removal_id: row[':START_ID(Removal)']})
        MATCH (c:Component {component_id: row[':END_ID(Component)']})
        MERGE (r)-[:REMOVED_COMPONENT]->(c)
        """,
    ),
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_nodes(driver: Driver, database: str, data_dir: Path) -> int:
    """Load every operational node type from its CSV file.

    Returns the number of skipped rows, which are readings with an unknown
    sensor_id.
    """
    skipped_total = 0
    for label, filename, query in _NODE_DEFINITIONS:
        logger.info("Loading %s nodes...", label)
        count, skipped = _run_in_batches(
            driver, database, iter_csv_batches(data_dir, filename), query
        )
        skipped_total += skipped
        logger.info("  [OK] Loaded %d %s nodes.", count - skipped, label)
    return skipped_total


def load_relationships(driver: Driver, database: str, data_dir: Path) -> None:
    """Load every operational relationship type from its CSV file."""
    for index, (rel_type, filename, query) in enumerate(_REL_DEFINITIONS):
        # The CLI starts the relationship phase with a blank line.
        logger.info("Loading %s relationships...", rel_type, extra={"blank_before": index == 0})
        count, _ = _run_in_batches(driver, database, iter_csv_batches(data_dir, filename), query)
        logger.info("  [OK] Loaded %d %s relationships.", count, rel_type)


def load_operational_graph(driver: Driver, database: str, data_dir: Path) -> None:
    """Load all operational nodes, then all relationships, then report skips.

    The generator stamp is recorded last on a Dataset node, so verify can
    tell which generated run the graph holds. The old node is removed first,
    so a load that fails partway leaves none.

    Raises:
        GenerateRunningError: If a generate is running in data_dir.
    """
    with _shared_lock(data_dir):
        _load_operational_graph(driver, database, data_dir)


@contextmanager
def _shared_lock(data_dir: Path) -> Iterator[None]:
    """Hold data_dir's generate lock shared, or fail at once if a generate holds it.

    A generate publishes its CSVs one at a time under the exclusive lock, so
    a load without this lock could read a mix of old and new files.

    When the lock file is missing and data_dir is read-only, the load runs
    without the lock. A generate cannot publish into that directory either.

    Raises:
        GenerateRunningError: If a generate holds the lock.
    """
    path = data_dir / LOCK_NAME
    if (handle := _open_lock_file(path)) is None:
        logger.warning("[WARN] Cannot create %s, so the load runs without the generate lock.", path)
        yield
        return
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise GenerateRunningError(f"a generate is running in {data_dir}") from exc
        yield


def _open_lock_file(path: Path) -> TextIO | None:
    """Open the lock file read-only, creating it only when it is missing.

    flock works on a read-only file, so a load never needs write access to
    an existing lock. Returns None when the file is missing and its
    directory refuses new files with EACCES or EROFS.
    """
    with suppress(FileNotFoundError):
        return path.open("r")
    try:
        return path.open("a")
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EROFS):
            return None
        raise


def _load_operational_graph(driver: Driver, database: str, data_dir: Path) -> None:
    """Do the load for load_operational_graph, with the lock already held."""
    stamp = read_stamp(data_dir)
    driver.execute_query("MATCH (d:Dataset) DETACH DELETE d", database_=database)
    skipped = load_nodes(driver, database, data_dir)
    load_relationships(driver, database, data_dir)
    if skipped:
        logger.warning(
            "[WARN] Skipped %s readings whose sensor_id matches no Sensor.",
            f"{skipped:,}",
            extra={"blank_before": True},
        )
    else:
        logger.info("[OK] No readings skipped.", extra={"blank_before": True})
    if stamp is None:
        logger.warning(
            "[WARN] %s has no %s, so the graph gets no Dataset node.", data_dir, STAMP_NAME
        )
        return
    driver.execute_query(
        """
        MERGE (d:Dataset {id: 'current'})
        SET d += {generator_hash: $hash, stamp: $stamp, loaded_at: datetime()}
        """,
        hash=stamp.get("generator_hash"),
        stamp=json.dumps(stamp, sort_keys=True),
        database_=database,
    )
    logger.info("[OK] Recorded the generator stamp on a Dataset node.")


def dataset_mismatch(driver: Driver, database: str, data_dir: Path) -> str | None:
    """Return why the graph's Dataset node does not match data_dir's stamp.

    Returns None when they match, or when data_dir has no stamp, since
    stale_reason already reports that.
    """
    # The label or property may not exist yet, so the UNRECOGNIZED notice
    # is expected noise.
    with driver.session(
        database=database,
        default_access_mode=READ_ACCESS,
        notifications_disabled_classifications=[NotificationDisabledClassification.UNRECOGNIZED],
    ) as session:
        stored = session.execute_read(
            lambda tx: [r["stamp"] for r in tx.run("MATCH (d:Dataset) RETURN d.stamp AS stamp")]
        )
    if not stored:
        return (
            "the graph has no Dataset node (loaded before stamps, from unstamped CSVs,"
            " or a load did not finish)"
        )
    if len(stored) > 1:
        return f"the graph has {len(stored)} Dataset nodes, where a load writes one"
    local = read_stamp(data_dir)
    if local is None:
        return None
    try:
        graph = json.loads(stored[0])
    except (TypeError, ValueError):
        graph = None
    if not isinstance(graph, dict):
        return "the graph's Dataset node has no readable stamp"
    if differs := stamp_differences(graph, local):
        return (
            f"the graph was loaded from a run with a different {', '.join(differs)} than {data_dir}"
        )
    return None


# Rows deleted per inner transaction when clearing nodes. DETACH DELETE also
# removes every relationship on each node, so a larger batch can exceed the
# transaction memory limit on small Aura tiers.
_DELETE_BATCH_SIZE = 1000
# Relationships deleted per inner transaction. Each row is one relationship,
# so the transaction size stays bounded however dense the nodes are.
_RELATIONSHIP_DELETE_BATCH_SIZE = 10_000


def detach_delete_nodes(driver: Driver, database: str, label: str | None = None) -> int:
    """Detach-delete every node, or every node with ``label``, in batches.

    ``CALL ... IN TRANSACTIONS`` must run in an auto-commit transaction, so
    this uses ``session.run`` rather than ``execute_query``.

    Returns:
        The number of nodes deleted.
    """
    pattern = f"(n:{label})" if label else "(n)"
    query = (
        f"MATCH {pattern} "
        "CALL (n) { DETACH DELETE n } "
        f"IN TRANSACTIONS OF {_DELETE_BATCH_SIZE} ROWS"
    )
    with driver.session(database=database) as session:
        summary = session.run(query).consume()
    return summary.counters.nodes_deleted


def delete_all_relationships(driver: Driver, database: str) -> int:
    """Delete every relationship in batches and return how many were deleted.

    Like ``detach_delete_nodes``, this needs an auto-commit transaction.
    """
    query = (
        "MATCH ()-[r]->() "
        "CALL (r) { DELETE r } "
        f"IN TRANSACTIONS OF {_RELATIONSHIP_DELETE_BATCH_SIZE} ROWS"
    )
    with driver.session(database=database) as session:
        summary = session.run(query).consume()
    return summary.counters.relationships_deleted


def clear_database(driver: Driver, database: str) -> None:
    """Delete all relationships, then all nodes, in batches.

    Deleting relationships first bounds each transaction. A detach-delete
    batch of dense nodes, such as Sensors with thousands of readings, can
    otherwise exceed the heap.
    """
    logger.info("Clearing database...")
    relationships = delete_all_relationships(driver, database)
    nodes = detach_delete_nodes(driver, database)
    logger.info(
        "  [OK] Database cleared (%d relationships, %d nodes deleted).", relationships, nodes
    )


def _get_label_counts(driver: Driver, database: str) -> dict[str, int]:
    records, _, _ = driver.execute_query(
        """
        MATCH (n)
        UNWIND labels(n) AS label
        RETURN label, count(n) AS count
        """,
        database_=database,
    )
    return {record["label"]: record["count"] for record in records}


def _get_relationship_counts(driver: Driver, database: str) -> dict[str, int]:
    records, _, _ = driver.execute_query(
        """
        MATCH ()-[r]->()
        RETURN type(r) AS rel_type, count(r) AS count
        """,
        database_=database,
    )
    return {record["rel_type"]: record["count"] for record in records}


def _print_count_section(title: str, counts: dict[str, int]) -> None:
    print(f"\n{title}:")
    for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
        print(f"  {name}: {count:,}")
    print("  ---------------------")
    print(f"  Total: {sum(counts.values()):,}")


def _has_constraint(constraint_rows: list[dict[str, Any]], label: str, property_name: str) -> bool:
    return any(
        row["type"] in UNIQUENESS_CONSTRAINT_TYPES
        and row["labelsOrTypes"] == [label]
        and row["properties"] == [property_name]
        for row in constraint_rows
    )


@dataclass
class _VerifyResult:
    """Failed checks, collected as failures in strict mode and warnings otherwise.

    With skip_enrichment, a failed enrichment check stays a warning even in
    strict mode. Operational and consistency checks still fail.
    """

    strict: bool
    skip_enrichment: bool = False
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def check(self, condition: bool, message: str, *, enrichment: bool = False) -> None:
        if condition:
            return
        if self.strict and not (enrichment and self.skip_enrichment):
            self.failures.append(message)
        else:
            self.warnings.append(message)


def _verify_vector_search(
    driver: Driver,
    database: str,
    *,
    has_chunk_embeddings: bool,
    has_vector_index: bool,
) -> tuple[bool, str]:
    if not has_chunk_embeddings:
        return False, "no chunk embeddings found"
    if not has_vector_index:
        return False, "missing maintenanceChunkEmbeddings index"

    try:
        records, _, _ = driver.execute_query(
            """
            MATCH (c:Chunk)
            WHERE c.embedding IS NOT NULL
            WITH c.embedding AS embedding
            LIMIT 1
            CALL db.index.vector.queryNodes(
                'maintenanceChunkEmbeddings',
                1,
                embedding
            )
            YIELD node, score
            RETURN count(node) AS count, max(score) AS score
        """,
            database_=database,
        )
    except Neo4jError as exc:
        return False, str(exc)

    count = records[0]["count"]
    score = records[0]["score"]
    if count < 1:
        return False, "vector query returned no rows"
    return True, f"{count} result(s), best score={score:.4f}"


# (name, query, labels it needs, relationship types it needs, whether it checks
# enrichment). A check whose labels or relationship types are absent counts 0
# without running.
_ORPHAN_CHECKS = [
    (
        "Readings without Sensor",
        "MATCH (r:Reading) WHERE NOT (r)<-[:HAS_READING]-(:Sensor) RETURN count(r) AS count",
        {"Reading", "Sensor"},
        {"HAS_READING"},
        False,
    ),
    (
        "Flights without Aircraft",
        "MATCH (f:Flight) WHERE NOT (f)<-[:OPERATES_FLIGHT]-(:Aircraft) RETURN count(f) AS count",
        {"Flight", "Aircraft"},
        {"OPERATES_FLIGHT"},
        False,
    ),
    (
        "Components without System",
        "MATCH (c:Component) WHERE NOT (c)<-[:HAS_COMPONENT]-(:System) RETURN count(c) AS count",
        {"Component", "System"},
        {"HAS_COMPONENT"},
        False,
    ),
    (
        "Sensors without Readings",
        "MATCH (s:Sensor) WHERE NOT (s)-[:HAS_READING]->(:Reading) RETURN count(s) AS count",
        {"Sensor", "Reading"},
        {"HAS_READING"},
        False,
    ),
    (
        "Documents without Chunks",
        "MATCH (d:Document) WHERE NOT (:Chunk)-[:FROM_DOCUMENT]->(d) RETURN count(d) AS count",
        {"Document", "Chunk"},
        {"FROM_DOCUMENT"},
        True,
    ),
]


def _check_counts(
    label_counts: dict[str, int], rel_counts: dict[str, int], result: _VerifyResult
) -> None:
    operational_counts = {label: label_counts.get(label, 0) for label in OPERATIONAL_LABELS}
    enrichment_counts = {label: label_counts.get(label, 0) for label in ENRICHMENT_LABELS}
    _print_count_section("Operational Node Counts", operational_counts)
    _print_count_section("Enrichment Node Counts", enrichment_counts)
    _print_count_section("Relationship Counts", rel_counts)

    for label in OPERATIONAL_LABELS:
        result.check(operational_counts[label] > 0, f"{label} has no nodes")
    for rel_type in OPERATIONAL_RELATIONSHIP_TYPES:
        result.check(rel_counts[rel_type] > 0, f"{rel_type} has no relationships")
    for label in ("Document", "Chunk", "AircraftModel", "OperatingLimit"):
        result.check(
            enrichment_counts[label] > 0, f"{label} has no enrichment nodes", enrichment=True
        )


def _csv_row_count(path: Path) -> int:
    """Count a CSV's records the way the loader reads them."""
    with path.open(newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def _check_csv_counts(label_counts: dict[str, int], data_dir: Path, result: _VerifyResult) -> None:
    """Compare each operational label's node count with its CSV's row count.

    The load MERGEs into whatever the graph holds, so a direct load over an
    earlier, larger dataset leaves extra nodes. They show up here.
    """
    files = [(label, filename) for label, filename, _ in _NODE_DEFINITIONS]
    if not any((data_dir / filename).is_file() for _, filename in files):
        result.check(
            False, f"{data_dir} has no node CSVs, so node counts were not compared with them"
        )
        return
    matched = True
    for label, filename in files:
        path = data_dir / filename
        if not path.is_file():
            matched = False
            result.check(
                False,
                f"{filename} is missing from {data_dir}, so the {label} count was not compared",
            )
            continue
        rows = _csv_row_count(path)
        nodes = label_counts.get(label, 0)
        if nodes != rows:
            matched = False
            result.check(
                False,
                f"{label} has {nodes:,} nodes, but {filename} in {data_dir} has {rows:,} rows",
            )
    if matched:
        print(f"\n[OK] Node counts match the CSVs in {data_dir}.")


def _check_embeddings(
    driver: Driver,
    database: str,
    chunk_count: int,
    expected_dimensions: int,
    result: _VerifyResult,
) -> int:
    """Check chunk embeddings and return how many chunks have one."""
    if chunk_count > 0:
        embedding_records, _, _ = driver.execute_query(
            """
            MATCH (c:Chunk)
            RETURN count(c) AS chunks,
                   count(c.embedding) AS with_embedding,
                   count(CASE WHEN c.embedding IS NULL THEN 1 END) AS missing_embedding,
                   collect(DISTINCT size(c.embedding)) AS dimensions
            """,
            database_=database,
        )
        embedding_row = embedding_records[0]
        bad_dim_records, _, _ = driver.execute_query(
            """
            MATCH (c:Chunk)
            WHERE c.embedding IS NOT NULL
              AND size(c.embedding) <> $expected_dimensions
            RETURN count(c) AS count
            """,
            expected_dimensions=expected_dimensions,
            database_=database,
        )
        bad_dimensions = bad_dim_records[0]["count"]
    else:
        embedding_row = {
            "chunks": 0,
            "with_embedding": 0,
            "missing_embedding": 0,
            "dimensions": [],
        }
        bad_dimensions = 0
    dimensions = [dim for dim in embedding_row["dimensions"] if dim is not None]

    print("\nEmbedding Integrity:")
    print(f"  Chunks: {embedding_row['chunks']:,}")
    print(f"  With embeddings: {embedding_row['with_embedding']:,}")
    print(f"  Missing embeddings: {embedding_row['missing_embedding']:,}")
    print(f"  Dimensions found: {dimensions}")
    print(f"  Wrong-dimension embeddings: {bad_dimensions:,}")

    result.check(embedding_row["with_embedding"] > 0, "no chunk embeddings found", enrichment=True)
    result.check(
        embedding_row["missing_embedding"] == 0,
        "some chunks are missing embeddings",
        enrichment=True,
    )
    result.check(
        bad_dimensions == 0,
        f"some embeddings do not have {expected_dimensions} dimensions",
        enrichment=True,
    )
    return embedding_row["with_embedding"]


def _check_indexes(driver: Driver, database: str, result: _VerifyResult) -> set[str]:
    """Check the chunk indexes and return the names of all indexes.

    Both required indexes are built in the enrichment stage.
    """
    index_rows, _, _ = driver.execute_query(
        """
        SHOW INDEXES
        YIELD name, type, state, labelsOrTypes, properties
        RETURN name, type, state, labelsOrTypes, properties
    """,
        database_=database,
    )
    index_by_name = {row["name"]: row for row in index_rows}

    print("\nRequired Indexes:")
    for name in REQUIRED_INDEXES:
        row = index_by_name.get(name)
        if row is None:
            print(f"  [MISSING] {name}")
            result.check(False, f"missing index {name}", enrichment=True)
            continue
        print(f"  [OK] {name}: {row['type']} {row['state']}")
        result.check(row["state"] == "ONLINE", f"index {name} is {row['state']}", enrichment=True)
    return set(index_by_name)


def _check_constraints(driver: Driver, database: str, result: _VerifyResult) -> None:
    constraint_rows, _, _ = driver.execute_query(
        """
        SHOW CONSTRAINTS
        YIELD name, type, labelsOrTypes, properties
        RETURN name, type, labelsOrTypes, properties
    """,
        database_=database,
    )
    constraint_dicts = [dict(row) for row in constraint_rows]

    print("\nRequired Constraints:")
    for label, property_name in REQUIRED_CONSTRAINTS:
        exists = _has_constraint(constraint_dicts, label, property_name)
        status = "[OK]" if exists else "[MISSING]"
        print(f"  {status} {label}.{property_name}")
        result.check(
            exists,
            f"missing uniqueness constraint {label}.{property_name}",
            enrichment=(label, property_name) in EXTRACTION_CONSTRAINTS,
        )


def _check_vector_search(
    driver: Driver,
    database: str,
    *,
    has_chunk_embeddings: bool,
    has_vector_index: bool,
    result: _VerifyResult,
) -> None:
    vector_ok, vector_detail = _verify_vector_search(
        driver,
        database,
        has_chunk_embeddings=has_chunk_embeddings,
        has_vector_index=has_vector_index,
    )
    print("\nVector Search Smoke Test:")
    print(f"  {'[OK]' if vector_ok else '[FAIL]'} {vector_detail}")
    result.check(vector_ok, f"vector search smoke test failed: {vector_detail}", enrichment=True)


def _check_cross_links(rel_counts: dict[str, int], result: _VerifyResult) -> None:
    cross_link_checks = [
        ("Document -> Aircraft", rel_counts["APPLIES_TO"]),
        ("AircraftModel -> Aircraft", rel_counts["DESCRIBES_MODEL"]),
        ("SystemReference -> System", rel_counts["DESCRIBES_SYSTEM"]),
        ("Sensor -> OperatingLimit", rel_counts["HAS_LIMIT"]),
    ]
    print("\nCross-Link Checks:")
    for label, count in cross_link_checks:
        print(f"  {label}: {count:,}")
        result.check(count > 0, f"{label} has no links", enrichment=True)


def _check_data_quality(
    driver: Driver,
    database: str,
    existing_labels: set[str],
    existing_relationships: set[str],
    result: _VerifyResult,
) -> None:
    print("\nData Quality Checks:")
    for label, query, required_labels, required_relationships, enrichment in _ORPHAN_CHECKS:
        if required_labels <= existing_labels and required_relationships <= existing_relationships:
            records, _, _ = driver.execute_query(query, database_=database)
            count = records[0]["count"]
        else:
            count = 0
        print(f"  {label}: {count:,}")
        result.check(count == 0, f"{label}: {count:,}", enrichment=enrichment)


def _print_summary(result: _VerifyResult) -> bool:
    """Print warnings and failures and return whether verification passed."""
    if result.warnings:
        print("\nWarnings:")
        for warning in result.warnings:
            print(f"  [WARN] {warning}")

    if result.failures:
        print("\nFailures:")
        for failure in result.failures:
            print(f"  [FAIL] {failure}")
        print("=" * 60)
        return False

    if result.warnings:
        print("\n[OK] Verification completed with warnings.")
    else:
        print("\n[OK] Verification passed.")
    print("=" * 60)
    return True


def verify(
    driver: Driver,
    database: str,
    *,
    expected_embedding_dimensions: int = 1536,
    strict: bool = False,
    skip_enrichment: bool = False,
    data_dir: Path | None = None,
) -> bool:
    """Print comprehensive graph verification and return whether it passed.

    With data_dir, it also compares each operational label's node count
    with the row count of its CSV there. With skip_enrichment, failed
    enrichment checks are warnings even in strict mode.
    """
    result = _VerifyResult(strict=strict, skip_enrichment=skip_enrichment)

    label_counts = _get_label_counts(driver, database)
    relationship_counts = _get_relationship_counts(driver, database)
    rel_counts = {rel_type: relationship_counts.get(rel_type, 0) for rel_type in RELATIONSHIP_TYPES}

    print()
    print("=" * 60)
    print("Verification")
    print("=" * 60)
    _check_counts(label_counts, rel_counts, result)
    if data_dir is not None:
        _check_csv_counts(label_counts, data_dir, result)
    with_embedding = _check_embeddings(
        driver, database, label_counts.get("Chunk", 0), expected_embedding_dimensions, result
    )
    index_names = _check_indexes(driver, database, result)
    _check_constraints(driver, database, result)
    _check_vector_search(
        driver,
        database,
        has_chunk_embeddings=with_embedding > 0,
        has_vector_index="maintenanceChunkEmbeddings" in index_names,
        result=result,
    )
    _check_cross_links(rel_counts, result)
    _check_data_quality(driver, database, set(label_counts), set(relationship_counts), result)
    return _print_summary(result)
