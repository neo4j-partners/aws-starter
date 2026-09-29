#!/usr/bin/env python3
"""Fetch a fresh M2M access token for the deployed MCP server.

Reads the client ID, client secret, scope, and token URL from the credentials
file written by ``./deploy.py credentials``, then requests a new token from
Cognito with the client_credentials flow. The token works for both the
Gateway and the direct Runtime endpoint.

The token is printed alone on stdout, so scripts can capture it. Status
messages go to stderr.

Usage (from neo4j-mcp-server/):
    uv run python client/get_token.py                 # .mcp-credentials.json
    uv run python client/get_token.py --env finance   # .mcp-credentials.finance.json
    uv run python client/get_token.py --credentials path/to/creds.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

SERVER_DIR = Path(__file__).resolve().parent.parent


def credentials_path(env_name: str | None) -> Path:
    """Return the credentials file that deploy.py writes for this env."""
    suffix = f".{env_name}" if env_name else ""
    return SERVER_DIR / f".mcp-credentials{suffix}.json"


def get_token(credentials: dict[str, str]) -> tuple[str, int]:
    """Request a client_credentials token and return it with its lifetime."""
    response = httpx.post(
        credentials["token_url"],
        auth=(credentials["client_id"], credentials["client_secret"]),
        data={"grant_type": "client_credentials", "scope": credentials["scope"]},
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    return body["access_token"], body.get("expires_in", 3600)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--env",
        help="Named deployment. Reads .mcp-credentials.NAME.json.",
    )
    source.add_argument(
        "--credentials",
        type=Path,
        help="Path to a credentials file.",
    )
    return parser.parse_args()


def main() -> None:
    args = arguments()
    path = args.credentials or credentials_path(args.env)
    if not path.is_file():
        env_flag = f" --env {args.env}" if args.env else ""
        sys.exit(
            f"Credentials file not found: {path}\n"
            f"Run ./deploy.py{env_flag} credentials first."
        )

    try:
        credentials = json.loads(path.read_text())
        token, expires_in = get_token(credentials)
    except KeyError as error:
        sys.exit(f"{path.name} is missing {error}. Re-run ./deploy.py credentials.")
    except httpx.HTTPError as error:
        sys.exit(f"Token request failed: {error}")

    print(f"Token from {path.name} expires in {expires_in}s.", file=sys.stderr)
    print(token)


if __name__ == "__main__":
    main()
