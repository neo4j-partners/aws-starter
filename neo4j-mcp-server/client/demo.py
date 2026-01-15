#!/usr/bin/env python3
"""
Neo4j MCP Server Demo Client

This script demonstrates:
1. OAuth2 client credentials (M2M) authentication with AgentCore Gateway
2. Per-request Neo4j credentials via X-Neo4j-Authorization header
3. Testing the official Neo4j MCP server tools

The X-Neo4j-Authorization header is transformed to Authorization by the
Gateway REQUEST interceptor, enabling the official Neo4j MCP server to
receive per-request Basic auth credentials.

Usage:
    # Default (uses neo4j-mcp-server stack in us-west-2):
    # Requires .env file with NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
    python demo.py

    # Custom stack:
    python demo.py --stack my-stack --region us-east-1
"""

import argparse
import asyncio
import base64
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

import boto3
import requests
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Load environment variables from .env file
load_dotenv()


# =============================================================================
# NEO4J CREDENTIALS - Read from environment variables
# =============================================================================


def get_neo4j_basic_auth() -> str:
    """
    Build Base64-encoded Basic auth string for Neo4j credentials.

    Reads NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD from environment.
    This is sent as X-Neo4j-Authorization header and transformed by
    the Gateway interceptor to Authorization header.

    Returns:
        Base64-encoded "Basic username:password" string
    """
    neo4j_uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")

    if not neo4j_uri or not password:
        print("\nError: Neo4j credentials not found in environment.")
        print("Please create a .env file with:")
        print("  NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io")
        print("  NEO4J_USERNAME=neo4j")
        print("  NEO4J_PASSWORD=your-password")
        sys.exit(1)

    # Build Basic auth string: "username:password" base64 encoded
    credentials = f"{username}:{password}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


# =============================================================================
# TOKEN CACHE - Reuse tokens to minimize Cognito calls
# =============================================================================

_token_cache: Optional[str] = None
_token_expiry: Optional[datetime] = None
TOKEN_REFRESH_BUFFER_SECONDS = 600


def get_oauth_token(
    user_pool_id: str,
    client_id: str,
    scope: str,
    region: str
) -> str:
    """Get OAuth2 access token using client credentials flow."""
    global _token_cache, _token_expiry

    if _token_cache and _token_expiry:
        time_remaining = (_token_expiry - datetime.now()).total_seconds()
        if time_remaining > TOKEN_REFRESH_BUFFER_SECONDS:
            print(f"    Using cached token ({int(time_remaining)}s remaining)")
            return _token_cache

    print("\n[Token] Acquiring OAuth2 token from Cognito...")

    cognito = boto3.client("cognito-idp", region_name=region)
    response = cognito.describe_user_pool_client(
        UserPoolId=user_pool_id,
        ClientId=client_id
    )
    client_secret = response["UserPoolClient"]["ClientSecret"]

    pool_response = cognito.describe_user_pool(UserPoolId=user_pool_id)
    domain = pool_response["UserPool"].get("Domain")
    if not domain:
        raise ValueError("No Cognito domain configured for this User Pool")

    token_url = f"https://{domain}.auth.{region}.amazoncognito.com/oauth2/token"
    token_response = requests.post(
        token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        },
        timeout=30
    )

    if not token_response.ok:
        raise Exception(f"Token request failed: {token_response.text}")

    data = token_response.json()
    _token_cache = data["access_token"]
    _token_expiry = datetime.now() + timedelta(seconds=data.get("expires_in", 3600))
    print(f"    Token acquired, expires in {data.get('expires_in', 3600)}s")

    return _token_cache


# =============================================================================
# NEO4J MCP TESTS
# =============================================================================

async def run_neo4j_tests(gateway_url: str, token: str, neo4j_auth: str) -> bool:
    """Connect to Gateway and run comprehensive Neo4j MCP tests.

    Args:
        gateway_url: The AgentCore Gateway URL
        token: OAuth2 JWT token for Gateway authentication
        neo4j_auth: Basic auth string for Neo4j database authentication
    """
    print(f"\n{'='*60}")
    print("OFFICIAL NEO4J MCP SERVER TESTS")
    print(f"{'='*60}")
    print(f"\nGateway URL: {gateway_url}")
    print("Authentication: OAuth2 JWT (Gateway) + Basic Auth (Neo4j)")

    # Two-header authentication:
    # 1. Authorization: Bearer <jwt> - for Gateway authentication
    # 2. X-Neo4j-Authorization: Basic <creds> - transformed by interceptor
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Neo4j-Authorization": neo4j_auth,
        "Content-Type": "application/json",
    }

    passed = 0
    failed = 0

    try:
        async with streamablehttp_client(
            gateway_url,
            headers,
            timeout=timedelta(seconds=120),
            terminate_on_close=False
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                print("\nInitializing MCP session...")
                await session.initialize()
                print("Session initialized!")

                # List available tools
                print(f"\n{'='*60}")
                print("AVAILABLE TOOLS")
                print(f"{'='*60}")
                tools = await session.list_tools()
                tool_names = {}
                for tool in tools.tools:
                    base_name = tool.name.split("___")[-1] if "___" in tool.name else tool.name
                    tool_names[base_name] = tool.name
                    desc = tool.description.split('\n')[0].strip() if tool.description else "No description"
                    print(f"\n  {tool.name}")
                    print(f"    {desc}")

                # Run tests for official Neo4j MCP server
                # Reference: https://github.com/neo4j/mcp
                # Tools: get-schema, read-cypher, write-cypher (with hyphens)
                print(f"\n{'='*60}")
                print("RUNNING TESTS (Official Neo4j MCP Server)")
                print(f"{'='*60}")

                # Test 1: get-schema - Retrieve database schema
                print("\n[Test 1] get-schema - Retrieve database schema")
                try:
                    schema_tool = tool_names.get("get-schema", "get-schema")
                    result = await session.call_tool(
                        name=schema_tool,
                        arguments={}
                    )
                    content = result.content[0].text if result.content else "No content"
                    print(f"  Schema retrieved ({len(content)} chars)")
                    # Official server returns schema as text
                    if content and len(content) > 0:
                        # Show first few lines
                        lines = content.split('\n')[:5]
                        for line in lines:
                            print(f"    {line}")
                        if len(content.split('\n')) > 5:
                            print("    ...")
                        print("  PASSED")
                        passed += 1
                    else:
                        print("  FAILED - Empty schema")
                        failed += 1
                except Exception as e:
                    print(f"  FAILED: {e}")
                    failed += 1

                # Test 2: read-cypher - Simple read query
                print("\n[Test 2] read-cypher - Simple read query (RETURN 1 as test)")
                try:
                    read_tool = tool_names.get("read-cypher", "read-cypher")
                    result = await session.call_tool(
                        name=read_tool,
                        arguments={"query": "RETURN 1 as test"}
                    )
                    content = result.content[0].text if result.content else "No content"
                    print(f"  Result: {content[:200]}..." if len(content) > 200 else f"  Result: {content}")
                    print("  PASSED")
                    passed += 1
                except Exception as e:
                    print(f"  FAILED: {e}")
                    failed += 1

                # Test 3: read-cypher - Count nodes
                print("\n[Test 3] read-cypher - Count nodes (MATCH (n) RETURN count(n))")
                try:
                    read_tool = tool_names.get("read-cypher", "read-cypher")
                    result = await session.call_tool(
                        name=read_tool,
                        arguments={"query": "MATCH (n) RETURN count(n) as nodeCount"}
                    )
                    content = result.content[0].text if result.content else "No content"
                    print(f"  Result: {content}")
                    print("  PASSED")
                    passed += 1
                except Exception as e:
                    print(f"  FAILED: {e}")
                    failed += 1

                # Test 4: read-cypher - Get sample data
                print("\n[Test 4] read-cypher - Sample data (MATCH (n) RETURN labels, properties)")
                try:
                    read_tool = tool_names.get("read-cypher", "read-cypher")
                    result = await session.call_tool(
                        name=read_tool,
                        arguments={"query": "MATCH (n) RETURN labels(n) as labels, keys(n) as properties LIMIT 3"}
                    )
                    content = result.content[0].text if result.content else "No content"
                    print(f"  Result: {content[:300]}..." if len(content) > 300 else f"  Result: {content}")
                    print("  PASSED")
                    passed += 1
                except Exception as e:
                    print(f"  FAILED: {e}")
                    failed += 1

                # Summary
                print(f"\n{'='*60}")
                print("TEST SUMMARY")
                print(f"{'='*60}")
                total = passed + failed
                print(f"\n  Passed: {passed}/{total}")
                print(f"  Failed: {failed}/{total}")

                if failed == 0:
                    print("\n  All tests passed! Neo4j MCP server is working correctly.")
                elif passed > 0:
                    print("\n  Some tests failed. Check Neo4j credentials and database connectivity.")
                else:
                    print("\n  All tests failed. Ensure .env has valid Neo4j credentials.")

                return failed == 0

    except Exception as e:
        print(f"\nConnection error: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# MAIN
# =============================================================================

async def run_demo(
    user_pool_id: str,
    client_id: str,
    gateway_url: str,
    scope: str,
    region: str
):
    """Run the full Neo4j MCP demo."""
    print("="*60)
    print("OFFICIAL NEO4J MCP SERVER - OAUTH2 M2M DEMO")
    print("="*60)
    print(f"\nConfiguration:")
    print(f"  User Pool ID: {user_pool_id}")
    print(f"  Client ID: {client_id}")
    print(f"  Gateway URL: {gateway_url}")
    print(f"  Scope: {scope}")
    print(f"  Region: {region}")
    print(f"  Neo4j URI: {os.environ.get('NEO4J_URI', 'NOT SET')}")

    # Get credentials
    token = get_oauth_token(user_pool_id, client_id, scope, region)
    neo4j_auth = get_neo4j_basic_auth()

    print(f"\n  Neo4j credentials: [from .env file]")

    success = await run_neo4j_tests(gateway_url, token, neo4j_auth)

    print(f"\n{'='*60}")
    print("Demo complete!")
    print("="*60)

    return success


def get_stack_outputs(stack_name: str, region: str) -> dict:
    """Get outputs from CloudFormation stack."""
    cf = boto3.client("cloudformation", region_name=region)
    response = cf.describe_stacks(StackName=stack_name)
    outputs = {}
    for output in response["Stacks"][0]["Outputs"]:
        outputs[output["OutputKey"]] = output["OutputValue"]
    return outputs


def main():
    parser = argparse.ArgumentParser(
        description="Neo4j MCP Server OAuth2 M2M Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use defaults (neo4j-mcp-server stack in us-west-2):
  python demo.py

  # Custom stack:
  python demo.py --stack my-stack --region us-east-1
        """
    )

    parser.add_argument("--user-pool-id", help="Cognito User Pool ID")
    parser.add_argument("--client-id", help="Cognito Machine Client ID")
    parser.add_argument("--gateway-url", help="AgentCore Gateway URL")
    parser.add_argument("--scope", default="neo4j-mcp/invoke", help="OAuth scope")
    parser.add_argument("--region", default="us-west-2", help="AWS region")
    parser.add_argument("--stack", default="neo4j-mcp-server", help="CloudFormation stack name")

    args = parser.parse_args()

    # Get values from stack
    if not all([args.user_pool_id, args.client_id, args.gateway_url]):
        print(f"Getting configuration from stack: {args.stack}")
        try:
            outputs = get_stack_outputs(args.stack, args.region)
            args.user_pool_id = outputs.get("CognitoUserPoolId")
            args.client_id = outputs.get("CognitoMachineClientId")
            args.gateway_url = outputs.get("GatewayUrl")
        except Exception as e:
            print(f"Error getting stack outputs: {e}")
            sys.exit(1)

    if not all([args.user_pool_id, args.client_id, args.gateway_url]):
        print("Error: Could not get configuration from stack")
        parser.print_help()
        sys.exit(1)

    success = asyncio.run(run_demo(
        user_pool_id=args.user_pool_id,
        client_id=args.client_id,
        gateway_url=args.gateway_url,
        scope=args.scope,
        region=args.region
    ))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
