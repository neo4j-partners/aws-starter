"""Add the GDS properties expected by the Finance Agent to the loaded graph."""

from __future__ import annotations

from neo4j import GraphDatabase

from finance_graph.load_neo4j import _connection_settings


def _drop_graph(session, name: str) -> None:
    try:
        session.run("CALL gds.graph.drop($name)", name=name).consume()
    except Exception as error:  # GDS raises when a named projection is absent.
        message = str(error).lower()
        if "not found" not in message and "does not exist" not in message:
            raise


def main() -> None:
    uri, username, password, database = _connection_settings()
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            _drop_graph(session, "finance_account_transfers")
            _drop_graph(session, "finance_account_merchants")

            session.run(
                "CALL gds.graph.project($name, 'Account', "
                "{TRANSFERRED_TO: {orientation: 'UNDIRECTED'}})",
                name="finance_account_transfers",
            ).consume()
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

            session.run(
                "CALL gds.graph.project($name, ['Account', 'Merchant'], "
                "{TRANSACTED_WITH: {orientation: 'NATURAL'}})",
                name="finance_account_merchants",
            ).consume()
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
