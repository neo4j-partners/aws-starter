"""Constraint and index definitions for the Aircraft Digital Twin graph."""

from __future__ import annotations

import logging

from neo4j import Driver

from generator.specs import (
    COMPONENT_ALIASES,
    COMPONENT_TYPES_BY_SYSTEM,
    COMPONENTS_BY_SYSTEM,
    SENSOR_TYPES,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fleet type vocabulary for extraction
# ---------------------------------------------------------------------------
# The cross-link joins in pipeline.link_to_existing_graph match a
# SystemReference systemType and a ComponentReference componentType to the
# operational System and Component types. The extraction prompt and schema
# give the LLM the same lists, from the generator specs, so the values match.

SYSTEM_TYPES: list[str] = list(COMPONENT_TYPES_BY_SYSTEM)


def system_type_by_component_type(components_by_system: dict[str, list[str]]) -> dict[str, str]:
    """Return lowercase component type -> the system type that has it.

    Raises ValueError if a component type, ignoring case, is listed under
    more than one system type or twice under one.
    """
    mapping: dict[str, str] = {}
    for system, components in components_by_system.items():
        for component in components:
            key = component.lower()
            if key in mapping and mapping[key] == system:
                raise ValueError(
                    f"component type {component!r} is listed twice under {system!r}, "
                    "ignoring case; a component type must be listed once"
                )
            if key in mapping:
                raise ValueError(
                    f"component type {component!r} is listed under {mapping[key]!r} "
                    f"and {system!r}; a component type must belong to one system type"
                )
            mapping[key] = system
    return mapping


SYSTEM_TYPE_BY_COMPONENT_TYPE = system_type_by_component_type(COMPONENT_TYPES_BY_SYSTEM)

# The join maps an extracted componentType through this, so a manual's part
# name, such as ADIRU, links like its type.
COMPONENT_TYPE_BY_ALIAS: dict[str, str] = COMPONENT_ALIASES

# "Engine: Fan Module, HP Compressor, ...; Avionics: ...; Hydraulics: ..."
COMPONENT_TYPES_TEXT = "; ".join(
    f"{system}: {', '.join(components)}" for system, components in COMPONENT_TYPES_BY_SYSTEM.items()
)
SYSTEM_TYPES_TEXT = ", ".join(SYSTEM_TYPES)

# "HP Turbine for High-Pressure Turbine; Air Data Unit for ADC or ADIRU; ..."
COMPONENT_ALIASES_TEXT = "; ".join(
    f"{spec.type} for {' or '.join(spec.aliases()[1:])}"
    for specs in COMPONENTS_BY_SYSTEM.values()
    for spec in specs
    if len(spec.aliases()) > 1
)

# The fleet sensor types, which the Sensor HAS_LIMIT join matches to
# OperatingLimit parameterName.
SENSOR_PARAMETER_NAMES = ", ".join(sensor_type for sensor_type, _, _ in SENSOR_TYPES)

# The closed list of OperatingLimit regimes, from the manuals' limit tables.
# Entity resolution merges limits by name and keeps one node's properties,
# so the name carries the regime and each regime names one kind of limit:
# - Takeoff, Max Continuous, Start: hard limits, from the Operating Limits
#   table's Maximum column.
# - "<regime> Normal": normal ranges, one per column of the Normal Operating
#   Parameters table and its Quick Reference copy.
# - Trend Advisory, Trend Caution, Trend Warning: the Digital Twin
#   trend-averaged EGT thresholds.
# - Advisory, Caution, Warning: band thresholds, such as vibration, DC bus
#   voltage, and hydraulic pressure.
# - All: a limit whose text names no regime.
OPERATING_LIMIT_REGIMES: list[str] = [
    "Takeoff",
    "Max Continuous",
    "Start",
    "Ground Idle Normal",
    "Flight Idle Normal",
    "Cruise Normal",
    "Max Continuous Normal",
    "Takeoff Normal",
    "Trend Advisory",
    "Trend Caution",
    "Trend Warning",
    "Advisory",
    "Caution",
    "Warning",
    "All",
]
OPERATING_LIMIT_REGIMES_TEXT = ", ".join(OPERATING_LIMIT_REGIMES)

# (label, property) pairs, one uniqueness constraint each.
CONSTRAINTS: list[tuple[str, str]] = [
    ("Aircraft", "aircraft_id"),
    ("System", "system_id"),
    ("Component", "component_id"),
    ("Sensor", "sensor_id"),
    ("Reading", "reading_id"),
    ("Airport", "airport_id"),
    ("Flight", "flight_id"),
    ("Delay", "delay_id"),
    ("MaintenanceEvent", "event_id"),
    ("Removal", "removal_id"),
    ("Document", "documentId"),
    ("Chunk", "chunkId"),
    # The load records its generator stamp on one Dataset node, id 'current'.
    ("Dataset", "id"),
]

# (label, property) pairs: property indexes for common lookups.
INDEXES: list[tuple[str, str]] = [
    ("MaintenanceEvent", "severity"),
    ("Flight", "aircraft_id"),
    ("Reading", "sensor_id"),
    ("Reading", "timestamp"),
    ("Removal", "aircraft_id"),
]

# (index_name, label, [properties]): fulltext indexes for sample queries.
FULLTEXT_INDEXES: list[tuple[str, str, list[str]]] = [
    ("maintenance_search", "MaintenanceEvent", ["fault", "corrective_action"]),
    ("delay_search", "Delay", ["cause"]),
    ("component_search", "Component", ["name", "type"]),
    ("document_search", "Document", ["title", "aircraftType"]),
]

# Constraints for entity types created by the enrichment phase of `setup`.
# SimpleKGPipeline deduplicates on the `name` property.
EXTRACTION_CONSTRAINTS: list[tuple[str, str]] = [
    ("AircraftModel", "name"),
    ("SystemReference", "name"),
    ("ComponentReference", "name"),
    ("Fault", "name"),
    ("MaintenanceProcedure", "name"),
    ("OperatingLimit", "name"),
]

# SHOW CONSTRAINTS reports a node uniqueness constraint as UNIQUENESS on
# older Neo4j releases and as NODE_PROPERTY_UNIQUENESS on newer ones,
# such as the 2026.06 test container. Match either name.
UNIQUENESS_CONSTRAINT_TYPES: list[str] = ["UNIQUENESS", "NODE_PROPERTY_UNIQUENESS"]


def _quote_identifier(identifier: str) -> str:
    """Quote a Neo4j schema identifier."""
    return f"`{identifier.replace('`', '``')}`"


def create_constraints(driver: Driver, database: str) -> None:
    """Create uniqueness constraints (idempotent)."""
    for label, prop in CONSTRAINTS:
        driver.execute_query(
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{_quote_identifier(label)}) "
            f"REQUIRE n.{_quote_identifier(prop)} IS UNIQUE",
            database_=database,
        )
        logger.info("  [OK] Constraint: %s.%s", label, prop)


def create_indexes(driver: Driver, database: str) -> None:
    """Create property indexes (idempotent)."""
    for label, prop in INDEXES:
        index_name = f"idx_{label.lower()}_{prop.lower()}"
        driver.execute_query(
            f"CREATE INDEX {_quote_identifier(index_name)} IF NOT EXISTS "
            f"FOR (n:{_quote_identifier(label)}) ON (n.{_quote_identifier(prop)})",
            database_=database,
        )
        logger.info("  [OK] Index: %s.%s", label, prop)


def create_fulltext_indexes(driver: Driver, database: str) -> None:
    """Create fulltext indexes for sample demo queries (idempotent)."""
    for name, label, props in FULLTEXT_INDEXES:
        props_clause = ", ".join(f"n.{_quote_identifier(p)}" for p in props)
        driver.execute_query(
            f"CREATE FULLTEXT INDEX {_quote_identifier(name)} IF NOT EXISTS "
            f"FOR (n:{_quote_identifier(label)}) ON EACH [{props_clause}]",
            database_=database,
        )
        logger.info("  [OK] Fulltext index: %s on %s(%s)", name, label, ", ".join(props))


def create_extraction_constraints(driver: Driver, database: str) -> None:
    """Create uniqueness constraints for extracted entity types (idempotent)."""
    for label, prop in EXTRACTION_CONSTRAINTS:
        driver.execute_query(
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{_quote_identifier(label)}) "
            f"REQUIRE n.{_quote_identifier(prop)} IS UNIQUE",
            database_=database,
        )
        logger.info("  [OK] Constraint: %s.%s", label, prop)


def drop_extraction_constraints(driver: Driver, database: str) -> None:
    """Drop extracted-entity uniqueness constraints before SimpleKGPipeline runs.

    The pipeline writes duplicate extracted nodes first and performs entity
    resolution afterward. Uniqueness constraints are therefore valid only after
    the pipeline has finished.
    """
    for label, prop in EXTRACTION_CONSTRAINTS:
        records, _, _ = driver.execute_query(
            """
            SHOW CONSTRAINTS
            YIELD name, type, labelsOrTypes, properties
            WHERE type IN $types
              AND labelsOrTypes = [$label]
              AND properties = [$property]
            RETURN name
            """,
            label=label,
            property=prop,
            types=UNIQUENESS_CONSTRAINT_TYPES,
            database_=database,
        )
        for record in records:
            driver.execute_query(
                f"DROP CONSTRAINT {_quote_identifier(record['name'])} IF EXISTS", database_=database
            )
            logger.info("  [OK] Dropped constraint: %s.%s", label, prop)


def create_embedding_indexes(driver: Driver, database: str, dimensions: int) -> None:
    """Create vector and fulltext indexes for Chunk embeddings (idempotent).

    Imports neo4j_graphrag lazily so that other commands don't require it.
    """
    from neo4j_graphrag.indexes import create_fulltext_index, create_vector_index

    create_vector_index(
        driver,
        name="maintenanceChunkEmbeddings",
        label="Chunk",
        embedding_property="embedding",
        dimensions=dimensions,
        similarity_fn="cosine",
        neo4j_database=database,
    )
    logger.info("  [OK] Vector index: maintenanceChunkEmbeddings")

    create_fulltext_index(
        driver,
        name="maintenanceChunkText",
        label="Chunk",
        node_properties=["text"],
        neo4j_database=database,
    )
    logger.info("  [OK] Fulltext index: maintenanceChunkText")


def build_extraction_schema():
    """Build a GraphSchema for SimpleKGPipeline entity extraction.

    Extracts model-level manual knowledge into labels that do not collide with
    the operational graph loaded from CSV.  Entity names are qualified with the
    aircraft type where appropriate so entity resolution stays model-scoped.
    """
    from neo4j_graphrag.components.schema import (
        ConstraintType,
        GraphConstraintType,
        GraphSchema,
        NodeType,
        Pattern,
        PropertyType,
        RelationshipType,
    )

    node_types = [
        NodeType(
            label="AircraftModel",
            description="An aircraft model covered by a maintenance manual.",
            properties=[
                PropertyType(
                    name="name",
                    type="STRING",
                    description="Aircraft model, e.g. A320-200, A321neo, B737-800.",
                ),
                PropertyType(
                    name="manufacturer",
                    type="STRING",
                    description="Aircraft manufacturer when stated.",
                ),
            ],
            additional_properties=False,
        ),
        NodeType(
            label="SystemReference",
            description="A manual-described aircraft system or subsystem.",
            properties=[
                PropertyType(
                    name="name",
                    type="STRING",
                    description="System name qualified by aircraft type.",
                ),
                PropertyType(
                    name="systemType",
                    type="STRING",
                    description=(
                        f"Fleet system type, exactly one of: {SYSTEM_TYPES_TEXT}. "
                        "Omit it for any other system."
                    ),
                ),
                PropertyType(
                    name="aircraftType",
                    type="STRING",
                    description="Aircraft model from document context.",
                ),
            ],
            additional_properties=False,
        ),
        NodeType(
            label="ComponentReference",
            description="A component, part, sensor, or LRU described in a manual.",
            properties=[
                PropertyType(
                    name="name",
                    type="STRING",
                    description="Component name qualified by aircraft type.",
                ),
                PropertyType(
                    name="componentType",
                    type="STRING",
                    description=(
                        "Fleet component type, exactly one of the types listed "
                        f"for the part's system ({COMPONENT_TYPES_TEXT}). "
                        f"Use these types for the manuals' own part names: "
                        f"{COMPONENT_ALIASES_TEXT}. "
                        "Omit it when no listed type fits."
                    ),
                ),
                PropertyType(
                    name="partNumber",
                    type="STRING",
                    description="Part number when explicitly stated.",
                ),
                PropertyType(
                    name="aircraftType",
                    type="STRING",
                    description="Aircraft model from document context.",
                ),
            ],
            additional_properties=False,
        ),
        NodeType(
            label="Fault",
            description="A fault, warning, symptom, or failure condition.",
            properties=[
                PropertyType(
                    name="name",
                    type="STRING",
                    description="Fault name qualified by aircraft type.",
                ),
                PropertyType(
                    name="faultCode",
                    type="STRING",
                    description="Fault or message code when explicitly stated.",
                ),
                PropertyType(
                    name="severity",
                    type="STRING",
                    description="Severity or urgency when stated.",
                ),
                PropertyType(
                    name="aircraftType",
                    type="STRING",
                    description="Aircraft model from document context.",
                ),
            ],
            additional_properties=False,
        ),
        NodeType(
            label="MaintenanceProcedure",
            description="A maintenance, inspection, removal, or troubleshooting action.",
            properties=[
                PropertyType(
                    name="name",
                    type="STRING",
                    description="Procedure name qualified by aircraft type.",
                ),
                PropertyType(
                    name="procedureType",
                    type="STRING",
                    description=(
                        "Inspection, troubleshooting, removal, replacement, test, or reset."
                    ),
                ),
                PropertyType(
                    name="interval",
                    type="STRING",
                    description="Maintenance interval when explicitly stated.",
                ),
                PropertyType(
                    name="aircraftType",
                    type="STRING",
                    description="Aircraft model from document context.",
                ),
            ],
            additional_properties=False,
        ),
        NodeType(
            label="OperatingLimit",
            description="An operating parameter limit for an aircraft system.",
            properties=[
                PropertyType(
                    name="name",
                    type="STRING",
                    description=(
                        "Unique identifier combining parameter, regime, and aircraft "
                        "type, e.g. 'EGT Takeoff - A320-200' for the hard limit and "
                        "'EGT Takeoff Normal - A320-200' for the normal range. "
                        "Use the regime value word for word. "
                        "Always append ' - <aircraft type>'."
                    ),
                ),
                PropertyType(
                    name="parameterName",
                    type="STRING",
                    description=(
                        f"Fleet sensor type when the limit is for one: {SENSOR_PARAMETER_NAMES}. "
                        "Use Vibration for N1 and N2 vibration. "
                        "Otherwise a short sensor-style parameter name."
                    ),
                ),
                PropertyType(name="unit", type="STRING", description="Unit of measurement"),
                PropertyType(
                    name="regime",
                    type="STRING",
                    description=(
                        f"Operating regime or level, exactly one of: "
                        f"{OPERATING_LIMIT_REGIMES_TEXT}. "
                        "Use All when the text names no regime."
                    ),
                ),
                PropertyType(
                    name="minValue",
                    type="STRING",
                    description=(
                        "Lowest allowed value, a number from the text. "
                        "Set minValue or maxValue on every limit."
                    ),
                ),
                PropertyType(
                    name="maxValue",
                    type="STRING",
                    description=(
                        "Highest allowed value, a number from the text. For Takeoff, "
                        "Max Continuous, and Start it is the hard limit from the "
                        "Operating Limits table's Maximum column. A Normal Operating "
                        "Parameters bound uses a '<regime> Normal' regime instead."
                    ),
                ),
                PropertyType(
                    name="aircraftType",
                    type="STRING",
                    description="Aircraft type, e.g. A320-200",
                ),
            ],
            additional_properties=False,
        ),
    ]
    relationship_types = [
        RelationshipType(label="HAS_SYSTEM"),
        RelationshipType(label="HAS_COMPONENT"),
        RelationshipType(label="HAS_FAULT"),
        RelationshipType(label="HAS_PROCEDURE"),
        RelationshipType(label="HAS_LIMIT"),
        RelationshipType(label="CORRECTED_BY"),
    ]
    patterns = [
        Pattern(
            source="AircraftModel",
            relationship="HAS_SYSTEM",
            target="SystemReference",
        ),
        Pattern(
            source="SystemReference",
            relationship="HAS_COMPONENT",
            target="ComponentReference",
        ),
        Pattern(source="SystemReference", relationship="HAS_FAULT", target="Fault"),
        Pattern(source="ComponentReference", relationship="HAS_FAULT", target="Fault"),
        Pattern(
            source="SystemReference",
            relationship="HAS_PROCEDURE",
            target="MaintenanceProcedure",
        ),
        Pattern(
            source="ComponentReference",
            relationship="HAS_PROCEDURE",
            target="MaintenanceProcedure",
        ),
        Pattern(source="Fault", relationship="CORRECTED_BY", target="MaintenanceProcedure"),
        Pattern(source="SystemReference", relationship="HAS_LIMIT", target="OperatingLimit"),
        Pattern(
            source="ComponentReference",
            relationship="HAS_LIMIT",
            target="OperatingLimit",
        ),
    ]
    constraints = [
        ConstraintType(
            type=GraphConstraintType.EXISTENCE,
            node_type=label,
            property_names=("name",),
            relationship_type=None,
        )
        for label in (
            "AircraftModel",
            "SystemReference",
            "ComponentReference",
            "Fault",
            "MaintenanceProcedure",
            "OperatingLimit",
        )
    ]
    # Entity resolution merges same-name limits and discards the later
    # properties, so a limit needs its regime to keep a name of its own.
    constraints.append(
        ConstraintType(
            type=GraphConstraintType.EXISTENCE,
            node_type="OperatingLimit",
            property_names=("regime",),
            relationship_type=None,
        )
    )

    return GraphSchema(
        node_types=tuple(node_types),
        relationship_types=tuple(relationship_types),
        patterns=tuple(patterns),
        constraints=tuple(constraints),
        additional_node_types=False,
        additional_relationship_types=False,
        additional_patterns=False,
    )
