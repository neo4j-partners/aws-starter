"""
Neo4j MCP Server

MCP server that provides tools for querying Neo4j graph databases.
Credentials are loaded from AWS Secrets Manager (if NEO4J_SECRET_ARN is set)
or from environment variables (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD).
"""

import json
import os
from functools import lru_cache
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP(host="0.0.0.0", stateless_http=True)

# Cache for credentials
_credentials_cache = None


def get_credentials():
    """Get Neo4j credentials from Secrets Manager or environment variables."""
    global _credentials_cache

    if _credentials_cache is not None:
        return _credentials_cache

    secret_arn = os.environ.get("NEO4J_SECRET_ARN")

    if secret_arn:
        # Fetch from Secrets Manager
        try:
            import boto3
            region = os.environ.get("AWS_REGION", "us-west-2")
            client = boto3.client("secretsmanager", region_name=region)
            response = client.get_secret_value(SecretId=secret_arn)
            _credentials_cache = json.loads(response["SecretString"])
            return _credentials_cache
        except Exception as e:
            print(f"Failed to fetch credentials from Secrets Manager: {e}")
            return None
    else:
        # Fall back to environment variables
        uri = os.environ.get("NEO4J_URI", "")
        password = os.environ.get("NEO4J_PASSWORD", "")
        if not uri or not password:
            return None
        _credentials_cache = {
            "uri": uri,
            "username": os.environ.get("NEO4J_USERNAME", "neo4j"),
            "password": password,
            "database": os.environ.get("NEO4J_DATABASE", "neo4j")
        }
        return _credentials_cache


def get_neo4j_driver():
    """Get Neo4j driver using credentials."""
    from neo4j import GraphDatabase

    creds = get_credentials()
    if not creds:
        return None

    uri = creds.get("uri", "")
    username = creds.get("username", "neo4j")
    password = creds.get("password", "")

    if not uri or not password:
        return None

    return GraphDatabase.driver(uri, auth=(username, password))


@mcp.tool()
def echo(message: str) -> str:
    """Echo back the provided message. Useful for testing connectivity."""
    return f"Echo: {message}"


@mcp.tool()
def server_info() -> dict:
    """Get information about this MCP server and Neo4j connection status."""
    creds = get_credentials()
    uri = creds.get("uri", "not configured") if creds else "not configured"
    has_credentials = creds is not None and creds.get("password")
    secret_arn = os.environ.get("NEO4J_SECRET_ARN", "not configured")

    return {
        "name": "Neo4j MCP Server",
        "version": "1.0.0",
        "neo4j_uri": uri,
        "credentials_configured": bool(has_credentials),
        "secret_arn": secret_arn,
        "tools": ["echo", "server_info", "get_schema", "run_cypher"]
    }


@mcp.tool()
def get_schema() -> dict:
    """Get the Neo4j database schema including node labels, relationship types, and properties."""
    driver = get_neo4j_driver()
    if not driver:
        return {"error": "Neo4j credentials not configured"}

    try:
        with driver.session() as session:
            # Get node labels
            labels_result = session.run("CALL db.labels()")
            labels = [record["label"] for record in labels_result]

            # Get relationship types
            rel_result = session.run("CALL db.relationshipTypes()")
            relationships = [record["relationshipType"] for record in rel_result]

            # Get property keys
            props_result = session.run("CALL db.propertyKeys()")
            properties = [record["propertyKey"] for record in props_result]

            return {
                "node_labels": labels,
                "relationship_types": relationships,
                "property_keys": properties
            }
    except Exception as e:
        return {"error": str(e)}
    finally:
        driver.close()


@mcp.tool()
def run_cypher(query: str, parameters: dict = None) -> dict:
    """
    Execute a Cypher query against the Neo4j database.

    Args:
        query: The Cypher query to execute
        parameters: Optional dictionary of query parameters

    Returns:
        Query results as a list of records
    """
    driver = get_neo4j_driver()
    if not driver:
        return {"error": "Neo4j credentials not configured"}

    if parameters is None:
        parameters = {}

    try:
        with driver.session() as session:
            result = session.run(query, parameters)
            records = [dict(record) for record in result]

            # Convert Neo4j types to JSON-serializable types
            def serialize(obj):
                if hasattr(obj, '__dict__'):
                    return {k: serialize(v) for k, v in obj.__dict__.items() if not k.startswith('_')}
                elif isinstance(obj, (list, tuple)):
                    return [serialize(item) for item in obj]
                elif isinstance(obj, dict):
                    return {k: serialize(v) for k, v in obj.items()}
                else:
                    return str(obj) if not isinstance(obj, (str, int, float, bool, type(None))) else obj

            return {
                "records": [serialize(r) for r in records],
                "count": len(records)
            }
    except Exception as e:
        return {"error": str(e)}
    finally:
        driver.close()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
