"""Start mcp-neo4j-cypher with its Neo4j password read from Secrets Manager.

On AgentCore Runtime the stack sets NEO4J_PASSWORD_SECRET_ARN instead of
NEO4J_PASSWORD, so the password never appears in the Runtime configuration.
This script reads the secret with the Runtime role, sets NEO4J_PASSWORD in
this process, and then runs the server in the same process.

When NEO4J_PASSWORD_SECRET_ARN is unset, as with local.sh, the server reads
NEO4J_PASSWORD from the environment as before.

The script also adds a GET /ping route to the server. AgentCore Runtime
health-checks every live session. Without /ping it falls back to an MCP
``ping`` POST to /mcp every two seconds per session, and each of those runs
a full stateless MCP request. With /ping it uses that route instead.
"""

import json
import os
import sys
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from starlette.requests import Request
from starlette.responses import JSONResponse

SECRET_ARN_VAR = "NEO4J_PASSWORD_SECRET_ARN"
PASSWORD_VAR = "NEO4J_PASSWORD"

# AgentCore Runtime looks for /ping at the root path on the serving port,
# whatever the MCP path is. See "MCP protocol contract" in the AgentCore
# developer guide.
PING_PATH = "/ping"


class SecretError(RuntimeError):
    """The password secret is missing, malformed, or empty."""


def region_from_arn(secret_arn: str) -> str:
    """Return the region named in a Secrets Manager secret ARN."""
    parts = secret_arn.split(":")
    # Any partition works (aws, aws-cn, aws-us-gov), as in the agents.
    if len(parts) < 7 or parts[0] != "arn" or parts[2] != "secretsmanager" or not parts[3]:
        raise SecretError(f"{secret_arn!r} is not a Secrets Manager secret ARN.")
    return parts[3]


def fetch_secret_string(secret_arn: str) -> str:
    """Read the secret's string value with the container's AWS credentials.

    An AWS failure becomes a SecretError that names only the error code. The
    full botocore message names the role and the secret ARN, so it stays out
    of the container log.
    """
    client = boto3.client("secretsmanager", region_name=region_from_arn(secret_arn))
    # "from None" drops the botocore error from the traceback context.
    try:
        response = client.get_secret_value(SecretId=secret_arn)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "ClientError")
        raise SecretError(f"Reading the secret failed with {code}.") from None
    except BotoCoreError as error:
        raise SecretError(f"Reading the secret failed with {type(error).__name__}.") from None
    if "SecretString" not in response:
        raise SecretError("The secret holds binary data, not a string.")
    return response["SecretString"]


def password_from_secret(secret_string: str) -> str:
    """Return the password from a secret value.

    deploy.py stores the password as a plain string. A JSON object with a
    ``password`` key also works, which is the format the fleet agents use.
    """
    try:
        parsed = json.loads(secret_string)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        password = parsed.get("password")
        if not isinstance(password, str) or not password:
            raise SecretError("The secret is a JSON object without a non-empty 'password' key.")
        return password
    if not secret_string:
        raise SecretError("The secret is empty.")
    return secret_string


def load_password() -> bool:
    """Set NEO4J_PASSWORD from the secret when NEO4J_PASSWORD_SECRET_ARN is set.

    Returns True when the password came from the secret.
    """
    secret_arn = os.environ.get(SECRET_ARN_VAR, "").strip()
    if not secret_arn:
        return False
    os.environ[PASSWORD_VAR] = password_from_secret(fetch_secret_string(secret_arn))
    return True


async def ping(request: Request) -> JSONResponse:
    """Report the server as healthy to the AgentCore Runtime health check.

    The body follows the Runtime's /ping contract. It leaves out
    ``time_of_last_update``, so the platform tracks status changes itself and
    idle sessions still time out.
    """
    return JSONResponse({"status": "Healthy"})


def add_ping_route(server: Any) -> Any:
    """Register GET /ping on a FastMCP server and return the same server."""
    server.custom_route(PING_PATH, methods=["GET"], include_in_schema=False)(ping)
    return server


def with_ping_route(create_server: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a server factory so that every server it builds serves GET /ping."""

    def create_server_with_ping(*args: Any, **kwargs: Any) -> Any:
        return add_ping_route(create_server(*args, **kwargs))

    return create_server_with_ping


def main() -> None:
    try:
        from_secret = load_password()
    except SecretError as error:
        sys.exit(f"{SECRET_ARN_VAR}: {error}")
    if from_secret:
        print(f"Read {PASSWORD_VAR} from the secret in {SECRET_ARN_VAR}.", file=sys.stderr)

    # Imported here because only the image installs the server package.
    from mcp_neo4j_cypher import main as server_main
    from mcp_neo4j_cypher import server as server_module

    # server.main builds its FastMCP instance through this module-level
    # factory, so wrapping it adds /ping without changing the upstream server.
    server_module.create_mcp_server = with_ping_route(server_module.create_mcp_server)
    server_main()


if __name__ == "__main__":
    main()
