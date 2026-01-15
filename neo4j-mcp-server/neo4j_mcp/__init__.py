"""
Neo4j MCP Server CDK Package

This package contains CDK constructs and Lambda handlers for deploying
a Neo4j MCP server to AWS Bedrock AgentCore.
"""

from neo4j_mcp.stack import Neo4jMcpStack

__all__ = ["Neo4jMcpStack"]
