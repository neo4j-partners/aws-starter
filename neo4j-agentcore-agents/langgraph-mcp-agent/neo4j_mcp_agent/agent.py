#!/usr/bin/env python3
"""Production Neo4j MCP Agent.

A ReAct agent that connects to the Neo4j MCP server via AgentCore Gateway and
answers natural language questions about the database. The OAuth2 access token
is refreshed automatically before it expires, so the agent can run for
arbitrarily long sessions.

Usage:
    python -m neo4j_mcp_agent.agent                    # Run demo queries
    python -m neo4j_mcp_agent.agent "your question"    # Ask a specific question

Examples (Aircraft Maintenance Database):
    python -m neo4j_mcp_agent.agent "What is the database schema?"
    python -m neo4j_mcp_agent.agent "How many aircraft are in the database?"
    python -m neo4j_mcp_agent.agent "What sensors monitor engine components?"
"""

import json
import sys
from datetime import datetime, timedelta, timezone

import httpx

from neo4j_mcp_agent.core import CREDENTIALS_FILE, load_credentials, main


def _token_is_valid(credentials: dict) -> bool:
    """Return True if the token exists and is not expiring within 5 minutes."""
    expires_at_str = credentials.get("token_expires_at")
    if not expires_at_str:
        return False

    try:
        expires_at = datetime.fromisoformat(expires_at_str)
    except (ValueError, TypeError):
        return False

    now = datetime.now(timezone.utc)
    return now < (expires_at - timedelta(minutes=5))


def _refresh_token(credentials: dict) -> dict:
    """Refresh the OAuth2 access token using the client credentials grant."""
    token_url = credentials.get("token_url")
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    scope = credentials.get("scope")

    if not all([token_url, client_id, client_secret]):
        print("ERROR: Missing token refresh credentials (token_url, client_id, client_secret)")
        print("       Cannot auto-refresh token.")
        sys.exit(1)

    print("Refreshing OAuth2 token...")

    try:
        response = httpx.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Token refresh failed: {e.response.status_code}")
        print(f"       {e.response.text}")
        sys.exit(1)
    except httpx.HTTPError as e:
        print(f"ERROR: Token refresh failed: {e}")
        sys.exit(1)

    expires_in = token_data.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    credentials["access_token"] = token_data["access_token"]
    credentials["token_expires_at"] = expires_at.isoformat()

    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(credentials, f, indent=2)

    print(f"Token refreshed. New expiry: {expires_at.isoformat()}")
    return credentials


def load_with_refresh() -> dict:
    """Load credentials, refreshing the token if it is expired or expiring."""
    credentials = load_credentials()
    if not _token_is_valid(credentials):
        credentials = _refresh_token(credentials)
        print()
    return credentials


if __name__ == "__main__":
    main(load_with_refresh)
