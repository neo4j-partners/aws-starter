#!/usr/bin/env python3
"""
Neo4j MCP Server CDK App

Deploys Neo4j MCP server to AWS Bedrock AgentCore with:
- OAuth2 M2M authentication
- AgentCore Gateway for public HTTPS access
- Per-request Neo4j credentials via header transformation

Configuration is read from environment variables (set via .env file):
- STACK_NAME: CloudFormation stack name (default: neo4j-mcp-server)
- AWS_REGION: AWS region (default: us-west-2)
"""

import os

import aws_cdk as cdk
from neo4j_mcp import Neo4jMcpStack

# Read configuration from environment (set by deploy.sh from .env)
STACK_NAME = os.environ.get("STACK_NAME", "neo4j-mcp-server")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

app = cdk.App()

Neo4jMcpStack(
    app,
    STACK_NAME,
    env=cdk.Environment(
        account=None,  # Uses AWS_ACCOUNT_ID or current credentials
        region=AWS_REGION,
    ),
    description="Neo4j MCP Server on AWS Bedrock AgentCore with OAuth2 M2M authentication",
)

app.synth()
