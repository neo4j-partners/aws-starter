#!/usr/bin/env python3
"""
OAuth2 Demo Client with RBAC

This script demonstrates OAuth2 authentication with role-based access control
(RBAC) using AgentCore Gateway and Cognito. It supports two authentication modes:

1. M2M Mode (client_credentials): Machine-to-machine authentication
   - No user context, no cognito:groups in token
   - Good for service-to-service communication

2. User Mode (password): User authentication with groups
   - Includes cognito:groups claim in token
   - Enables group-based access control (RBAC)

Usage:
    python demo.py                              # M2M mode (default)
    python demo.py --mode user --username admin@example.com  # User mode
    python demo.py --mode user                  # User mode (prompts for username)
"""

import argparse
import asyncio
import base64
import getpass
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timedelta

import boto3
import requests
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


# =============================================================================
# DEFAULTS
# =============================================================================

DEFAULT_STACK_NAME = "SimpleOAuthDemo"
DEFAULT_SCOPE = "simple-oauth/invoke"


def get_default_region() -> str:
    """Get the default AWS region from environment or boto3 session."""
    if os.environ.get("AWS_REGION"):
        return os.environ["AWS_REGION"]
    if os.environ.get("AWS_DEFAULT_REGION"):
        return os.environ["AWS_DEFAULT_REGION"]

    session = boto3.Session()
    if session.region_name:
        return session.region_name

    return "us-west-2"


# =============================================================================
# TOKEN CACHE
# =============================================================================

_token_cache: Optional[str] = None
_token_expiry: Optional[datetime] = None
TOKEN_REFRESH_BUFFER_SECONDS = 600


def _clear_token_cache():
    """Clear the token cache (used when switching auth modes)."""
    global _token_cache, _token_expiry
    _token_cache = None
    _token_expiry = None


# =============================================================================
# M2M AUTHENTICATION (client_credentials flow)
# =============================================================================

def get_m2m_token(
    user_pool_id: str,
    client_id: str,
    scope: str,
    region: str
) -> str:
    """
    Get OAuth2 access token using client credentials flow (M2M).

    This flow is for machine-to-machine authentication. The token
    does NOT include cognito:groups because there is no user context.

    Args:
        user_pool_id: Cognito User Pool ID
        client_id: Machine client ID
        scope: OAuth scope
        region: AWS region

    Returns:
        Access token string
    """
    global _token_cache, _token_expiry

    # Check cache
    if _token_cache and _token_expiry:
        time_remaining = (_token_expiry - datetime.now()).total_seconds()
        if time_remaining > TOKEN_REFRESH_BUFFER_SECONDS:
            print(f"    Using cached token ({int(time_remaining)}s remaining)")
            return _token_cache

    print("\n[Auth] Acquiring M2M token (client_credentials)...")

    cognito = boto3.client("cognito-idp", region_name=region)

    # Get client secret
    response = cognito.describe_user_pool_client(
        UserPoolId=user_pool_id,
        ClientId=client_id
    )
    client_secret = response["UserPoolClient"]["ClientSecret"]

    # Get domain
    pool_response = cognito.describe_user_pool(UserPoolId=user_pool_id)
    domain = pool_response["UserPool"].get("Domain")
    if not domain:
        raise ValueError("No Cognito domain configured")

    token_url = f"https://{domain}.auth.{region}.amazoncognito.com/oauth2/token"
    print(f"    Token URL: {token_url}")

    # Request token
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
    expires_in = data.get("expires_in", 3600)
    _token_expiry = datetime.now() + timedelta(seconds=expires_in)

    print(f"    M2M token acquired (expires in {expires_in}s)")
    print("    Note: M2M tokens do NOT include cognito:groups")

    return _token_cache


# =============================================================================
# USER AUTHENTICATION (password flow)
# =============================================================================

def get_user_token(
    user_pool_id: str,
    client_id: str,
    username: str,
    password: str,
    region: str
) -> str:
    """
    Get OAuth2 access token using USER_PASSWORD_AUTH flow.

    This flow authenticates a user and includes cognito:groups in the
    token, enabling role-based access control.

    Args:
        user_pool_id: Cognito User Pool ID
        client_id: User client ID (with USER_PASSWORD_AUTH enabled)
        username: User's email/username
        password: User's password
        region: AWS region

    Returns:
        Access token string (includes cognito:groups claim)
    """
    global _token_cache, _token_expiry

    # Check cache
    if _token_cache and _token_expiry:
        time_remaining = (_token_expiry - datetime.now()).total_seconds()
        if time_remaining > TOKEN_REFRESH_BUFFER_SECONDS:
            print(f"    Using cached token ({int(time_remaining)}s remaining)")
            return _token_cache

    print(f"\n[Auth] Acquiring user token for: {username}")

    cognito = boto3.client("cognito-idp", region_name=region)

    # Get client secret
    response = cognito.describe_user_pool_client(
        UserPoolId=user_pool_id,
        ClientId=client_id
    )
    client_secret = response["UserPoolClient"]["ClientSecret"]

    # Calculate SECRET_HASH (required for clients with secrets)
    message = username + client_id
    dig = hmac.new(
        client_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).digest()
    secret_hash = base64.b64encode(dig).decode()

    # Authenticate
    try:
        auth_response = cognito.initiate_auth(
            ClientId=client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": username,
                "PASSWORD": password,
                "SECRET_HASH": secret_hash
            }
        )
    except cognito.exceptions.NotAuthorizedException as e:
        raise Exception(f"Authentication failed: {e}")
    except cognito.exceptions.UserNotFoundException as e:
        raise Exception(f"User not found: {username}")

    result = auth_response.get("AuthenticationResult", {})
    _token_cache = result.get("AccessToken")

    if not _token_cache:
        # May require additional challenge (e.g., NEW_PASSWORD_REQUIRED)
        challenge = auth_response.get("ChallengeName")
        raise Exception(f"Authentication requires challenge: {challenge}")

    expires_in = result.get("ExpiresIn", 3600)
    _token_expiry = datetime.now() + timedelta(seconds=expires_in)

    # Decode token to show groups
    groups = _extract_groups_from_token(_token_cache)
    print(f"    User token acquired (expires in {expires_in}s)")
    print(f"    User groups: {groups or '(none)'}")

    return _token_cache


def _extract_groups_from_token(token: str) -> list:
    """Extract cognito:groups from JWT token payload."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return []

        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        return claims.get("cognito:groups", [])
    except Exception:
        return []


# =============================================================================
# MCP CLIENT
# =============================================================================

async def call_mcp_tools(
    gateway_url: str,
    token: str,
    test_admin: bool = False,
    is_admin: bool = False
) -> bool:
    """
    Connect to Gateway and call MCP tools.

    Args:
        gateway_url: AgentCore Gateway URL
        token: OAuth2 bearer token
        test_admin: Whether to test admin_action tool
        is_admin: Whether the user is expected to have admin access

    Returns:
        True if successful
    """
    print(f"\n[MCP] Connecting to Gateway...")
    print(f"    URL: {gateway_url}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        async with streamablehttp_client(
            gateway_url,
            headers,
            timeout=timedelta(seconds=60),
            terminate_on_close=False
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("    Session initialized!")

                # List tools
                tools = await session.list_tools()
                tool_names = {}
                print("\n    Available Tools:")
                print("    " + "-" * 50)
                for tool in tools.tools:
                    base_name = tool.name.split("___")[-1] if "___" in tool.name else tool.name
                    tool_names[base_name] = tool.name
                    # Truncate description for display
                    desc = tool.description[:50] + "..." if len(tool.description) > 50 else tool.description
                    print(f"    - {base_name}: {desc}")

                # Test echo (public tool)
                print("\n[Test] Calling echo tool (public)...")
                echo_tool = tool_names.get("echo", "echo")
                result = await session.call_tool(
                    name=echo_tool,
                    arguments={"message": "Hello from RBAC demo!"}
                )
                print(f"    Result: {result.content[0].text}")

                # Test get_user_info
                print("\n[Test] Calling get_user_info tool...")
                user_info_tool = tool_names.get("get_user_info", "get_user_info")
                result = await session.call_tool(name=user_info_tool, arguments={})
                print(f"    Result: {result.content[0].text}")

                # Test admin_action (protected tool)
                if test_admin:
                    print("\n[Test] Calling admin_action tool (requires admin group)...")
                    admin_tool = tool_names.get("admin_action", "admin_action")
                    try:
                        result = await session.call_tool(
                            name=admin_tool,
                            arguments={"action": "test_admin_operation"}
                        )
                        response_text = result.content[0].text
                        print(f"    Result: {response_text}")

                        if not is_admin and "success" in response_text.lower():
                            print("    WARNING: Non-admin user should have been blocked!")
                    except Exception as e:
                        error_msg = str(e)
                        if "admin" in error_msg.lower() or "access denied" in error_msg.lower():
                            print(f"    Access denied (expected for non-admin): {error_msg}")
                        else:
                            print(f"    Error: {error_msg}")

                return True

    except ExceptionGroup as eg:
        # Handle asyncio ExceptionGroup to show actual errors
        print(f"    Connection error:")
        for exc in eg.exceptions:
            print(f"      - {type(exc).__name__}: {exc}")
        return False
    except Exception as e:
        print(f"    Error: {type(e).__name__}: {e}")
        return False


# =============================================================================
# DEMO RUNNERS
# =============================================================================

async def run_m2m_demo(
    user_pool_id: str,
    client_id: str,
    gateway_url: str,
    scope: str,
    region: str
):
    """Run the M2M authentication demo."""
    print("=" * 60)
    print("OAuth2 Demo - M2M Mode (client_credentials)")
    print("=" * 60)
    print(f"\nConfiguration:")
    print(f"  User Pool ID: {user_pool_id}")
    print(f"  Client ID: {client_id}")
    print(f"  Gateway URL: {gateway_url}")
    print(f"  Mode: M2M (client_credentials)")

    token = get_m2m_token(user_pool_id, client_id, scope, region)
    await call_mcp_tools(gateway_url, token, test_admin=True, is_admin=False)

    print("\n" + "=" * 60)
    print("M2M Demo Complete")
    print("=" * 60)
    print("\nKey Points:")
    print("  - M2M tokens do NOT include cognito:groups")
    print("  - Admin tools are blocked by the Gateway interceptor")
    print("  - Suitable for service-to-service communication")


async def run_user_demo(
    user_pool_id: str,
    client_id: str,
    gateway_url: str,
    username: str,
    password: str,
    region: str
):
    """Run the user authentication demo."""
    print("=" * 60)
    print("OAuth2 Demo - User Mode (password)")
    print("=" * 60)
    print(f"\nConfiguration:")
    print(f"  User Pool ID: {user_pool_id}")
    print(f"  Client ID: {client_id}")
    print(f"  Gateway URL: {gateway_url}")
    print(f"  Username: {username}")
    print(f"  Mode: User (password)")

    token = get_user_token(user_pool_id, client_id, username, password, region)

    # Check if user is admin
    groups = _extract_groups_from_token(token)
    is_admin = "admin" in groups

    await call_mcp_tools(gateway_url, token, test_admin=True, is_admin=is_admin)

    print("\n" + "=" * 60)
    print("User Demo Complete")
    print("=" * 60)
    print(f"\nKey Points:")
    print(f"  - User: {username}")
    print(f"  - Groups: {groups or '(none)'}")
    if is_admin:
        print("  - Admin access: GRANTED (member of 'admin' group)")
    else:
        print("  - Admin access: DENIED (not in 'admin' group)")
    print("  - User tokens include cognito:groups for RBAC")


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
        description="OAuth2 Demo with RBAC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Authentication Modes:
  m2m   - Machine-to-machine (client_credentials flow)
          No user context, no groups, admin tools blocked

  user  - User authentication (password flow)
          Includes cognito:groups for RBAC

Examples:
  python demo.py                                      # M2M mode
  python demo.py --mode user --username admin@example.com
  python demo.py --mode user                          # Prompts for username

Test Users (after running setup_users.py):
  admin@example.com / AdminPass123!  -> groups: admin, users
  user@example.com  / UserPass123!   -> groups: users
        """
    )

    parser.add_argument(
        "--stack",
        default=DEFAULT_STACK_NAME,
        help=f"CloudFormation stack name (default: {DEFAULT_STACK_NAME})"
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS region (default: from AWS config)"
    )
    parser.add_argument(
        "--mode",
        choices=["m2m", "user"],
        default="m2m",
        help="Authentication mode: m2m or user (default: m2m)"
    )
    parser.add_argument(
        "--username",
        help="Username for user mode authentication"
    )
    parser.add_argument(
        "--scope",
        default=DEFAULT_SCOPE,
        help=f"OAuth scope (default: {DEFAULT_SCOPE})"
    )

    args = parser.parse_args()
    region = args.region or get_default_region()

    # Get stack outputs
    print(f"Loading configuration from stack: {args.stack} (region: {region})")
    try:
        outputs = get_stack_outputs(args.stack, region)
    except Exception as e:
        print(f"\nError: Could not get stack outputs: {e}")
        print(f"\nMake sure '{args.stack}' is deployed. Run: ./deploy.sh")
        sys.exit(1)

    user_pool_id = outputs.get("CognitoUserPoolId")
    gateway_url = outputs.get("GatewayUrl")

    if not user_pool_id or not gateway_url:
        print("\nError: Missing required stack outputs")
        sys.exit(1)

    # Run appropriate demo
    if args.mode == "m2m":
        client_id = outputs.get("CognitoMachineClientId")
        if not client_id:
            print("\nError: Missing CognitoMachineClientId output")
            sys.exit(1)

        asyncio.run(run_m2m_demo(
            user_pool_id=user_pool_id,
            client_id=client_id,
            gateway_url=gateway_url,
            scope=args.scope,
            region=region
        ))

    else:  # user mode
        client_id = outputs.get("CognitoUserClientId")
        if not client_id:
            print("\nError: Missing CognitoUserClientId output")
            print("Make sure you've deployed the updated stack with user client.")
            sys.exit(1)

        # Get username
        username = args.username
        if not username:
            username = input("Username: ")

        # Get password
        password = getpass.getpass("Password: ")

        asyncio.run(run_user_demo(
            user_pool_id=user_pool_id,
            client_id=client_id,
            gateway_url=gateway_url,
            username=username,
            password=password,
            region=region
        ))


if __name__ == "__main__":
    main()
