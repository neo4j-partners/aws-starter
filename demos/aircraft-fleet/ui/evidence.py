"""Look up the fleet graph paths named by a supervisor tool result."""

from typing import Any

from neo4j import Driver, Query
from neo4j.graph import Node

# Start each path at a returned ID. An aircraft ID alone provides no evidence
# about which of its systems or maintenance events the tool found.
EVIDENCE_QUERY = """
CALL () {
    MATCH path = (:Aircraft)-[:HAS_SYSTEM]->(:System)-[:HAS_COMPONENT]->(:Component)
                 -[:HAS_EVENT]->(m:MaintenanceEvent)
    WHERE m.event_id IN $ids
    RETURN path
    UNION ALL
    MATCH path = (:Aircraft)-[:HAS_SYSTEM]->(:System)-[:HAS_COMPONENT]->(c:Component)
    WHERE c.component_id IN $ids
    RETURN path
    UNION ALL
    MATCH path = (:Aircraft)-[:HAS_SYSTEM]->(s:System)
    WHERE s.system_id IN $ids
    RETURN path
    UNION ALL
    MATCH path = (:Aircraft)-[:OPERATES_FLIGHT]->(f:Flight)
    WHERE f.flight_id IN $ids
    RETURN path
    UNION ALL
    MATCH path = (a:Aircraft)
    WHERE a.aircraft_id IN $ids OR a.tail_number IN $ids
    RETURN path
}
RETURN path LIMIT 30
"""

NODE_FIELDS = {
    "Aircraft": ("aircraft_id", "tail_number", ("model", "operator")),
    "System": ("system_id", "name", ("type",)),
    "Component": ("component_id", "name", ("type",)),
    "MaintenanceEvent": ("event_id", "fault", ("severity", "corrective_action")),
    "Flight": ("flight_id", "flight_number", ("origin", "destination")),
}


def _node_id(node: Node) -> str:
    return next(
        str(node[key]) for label, (key, _, _) in NODE_FIELDS.items() if label in node.labels
    )


def load_evidence(driver: Driver, database: str, ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Read a bounded projection with only the fields the canvas displays."""
    records, _, _ = driver.execute_query(
        Query(EVIDENCE_QUERY, timeout=5), ids=ids[:30], database_=database, routing_="r"
    )
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    for record in records:
        path = record["path"]
        for node in path.nodes:
            node_id = _node_id(node)
            if node_id in nodes:
                continue
            kind = next(label for label in NODE_FIELDS if label in node.labels)
            _, title, details = NODE_FIELDS[kind]
            nodes[node_id] = {
                "id": node_id,
                "kind": kind,
                "label": node.get(title) or node_id,
                "details": {key: node[key] for key in details if node.get(key) is not None},
            }
        for relationship in path.relationships:
            source = _node_id(relationship.start_node)
            target = _node_id(relationship.end_node)
            edge_id = f"{source}:{relationship.type}:{target}"
            edges[edge_id] = {
                "id": edge_id,
                "from": source,
                "to": target,
                "label": relationship.type,
            }
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}
