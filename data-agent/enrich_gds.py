#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "neo4j>=5.28.0",
#   "python-dotenv>=1.0.1",
# ]
# ///
"""Add sample GDS fraud-investigation signals to an existing finance graph.

Set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, and optionally NEO4J_DATABASE
before running this script. The graph must already contain the Account,
Merchant, TRANSFERRED_TO, and TRANSACTED_WITH data described in this README.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from neo4j import GraphDatabase


def _connection_settings() -> tuple[str, str, str, str]:
    load_dotenv()
    required = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"Missing {joined}. Set them in .env or the environment.")
    return (
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
        os.environ.get("NEO4J_DATABASE", "neo4j"),
    )


def _drop_graph(session, name: str) -> None:
    try:
        session.run("CALL gds.graph.drop($name)", name=name).consume()
    except Exception as error:  # GDS raises when a named projection is absent.
        message = str(error).lower()
        if "not found" not in message and "does not exist" not in message:
            raise


def _project_graph(
    session,
    name: str,
    node_labels: str | list[str],
    relationship_types: str | list[str],
    *,
    undirected_relationship_types: list[str] | None = None,
) -> None:
    """Project a graph using the Aura Graph Analytics native projection API."""
    configuration: dict[str, object] = {
        # Aura Graph Analytics creates an implicit session for this projection.
        # A session size is mandatory; 2GB is the smallest supported tier for
        # this demonstration graph.
        "memory": os.environ.get("GDS_SESSION_MEMORY", "2GB"),
    }
    if undirected_relationship_types:
        configuration["undirectedRelationshipTypes"] = undirected_relationship_types
    session.run(
        "CALL gds.graph.project($name, $node_labels, $relationship_types, "
        "$configuration)",
        name=name,
        node_labels=node_labels,
        relationship_types=relationship_types,
        configuration=configuration,
    ).consume()


def main() -> None:
    uri, username, password, database = _connection_settings()
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            _drop_graph(session, "finance_account_transfers")
            _drop_graph(session, "finance_account_merchants")

            _project_graph(
                session,
                name="finance_account_transfers",
                node_labels="Account",
                relationship_types="TRANSFERRED_TO",
                undirected_relationship_types=["TRANSFERRED_TO"],
            )
            session.run(
                "CALL gds.pageRank.write($name, {maxIterations: 20, "
                "dampingFactor: 0.85, writeProperty: 'risk_score'})",
                name="finance_account_transfers",
            ).consume()
            session.run(
                "CALL gds.louvain.write($name, {writeProperty: 'community_id'})",
                name="finance_account_transfers",
            ).consume()
            session.run(
                "CALL gds.betweenness.write($name, {writeProperty: "
                "'betweenness_centrality', samplingSize: 1000, samplingSeed: 42})",
                name="finance_account_transfers",
            ).consume()
            _drop_graph(session, "finance_account_transfers")

            _project_graph(
                session,
                name="finance_account_merchants",
                node_labels=["Account", "Merchant"],
                relationship_types="TRANSACTED_WITH",
            )
            session.run("MATCH ()-[r:SIMILAR_TO]->() DELETE r").consume()
            session.run(
                "CALL gds.nodeSimilarity.write($name, {similarityMetric: 'JACCARD', "
                "topK: 10, degreeCutoff: 5, writeRelationshipType: 'SIMILAR_TO', "
                "writeProperty: 'similarity_score'})",
                name="finance_account_merchants",
            ).consume()
            _drop_graph(session, "finance_account_merchants")
            session.run(
                "MATCH (a:Account)-[s:SIMILAR_TO]-() "
                "WITH a, max(s.similarity_score) AS score SET a.similarity_score = score"
            ).consume()
            session.run(
                "MATCH (a:Account) WHERE NOT (a)-[:SIMILAR_TO]-() "
                "SET a.similarity_score = 0.0"
            ).consume()
            session.run(
                "CREATE INDEX account_community_id IF NOT EXISTS "
                "FOR (a:Account) ON (a.community_id)"
            ).consume()
            session.run(
                "CREATE INDEX account_risk_score IF NOT EXISTS "
                "FOR (a:Account) ON (a.risk_score)"
            ).consume()
    finally:
        driver.close()
    print("GDS enrichment complete: risk_score, community_id, "
          "betweenness_centrality, and SIMILAR_TO are ready.")


if __name__ == "__main__":
    main()
