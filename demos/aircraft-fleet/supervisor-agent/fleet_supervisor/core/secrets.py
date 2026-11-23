"""Neo4j logins from Secrets Manager, with plain env var fallbacks.

In AgentCore Runtime, each password lives in Secrets Manager and the Runtime
gets only the secret ARN, for example ``MEM_NEO4J_PASSWORD_SECRET_ARN``. Local
runs set the password itself, for example ``MEM_NEO4J_PASSWORD``.
:func:`login_from` reads the secret when the ARN variable is set and falls
back to the user name and password variables otherwise.

The secret value is a JSON object with a ``password`` key, the same shape as
an AWS database credentials secret. An optional ``username`` key names the
Neo4j user, so the user and its password always come from the same place.
Without it, the user name variable applies. Other keys are ignored. Each
secret is read once per process, until :func:`forget_secrets` drops the cached
values.
"""

from __future__ import annotations

import json
import logging
import os
from functools import cache
from typing import NamedTuple

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from fleet_supervisor.core.config import ConfigError

logger = logging.getLogger(__name__)

# The env var that holds the fleet graph's password secret ARN.
NEO4J_PASSWORD_SECRET_ARN = "NEO4J_PASSWORD_SECRET_ARN"


class Neo4jLogin(NamedTuple):
    """A Neo4j user name and password."""

    username: str
    password: str


class _SecretLogin(NamedTuple):
    """The keys read from a secret. ``username`` is None when the secret has none."""

    username: str | None
    password: str


def login_from(secret_arn_var: str, username_var: str, password_var: str) -> Neo4jLogin:
    """Return the Neo4j login named by ``secret_arn_var`` or the plain variables.

    The secret ARN wins when it is set. Its ``password`` key is the password,
    and its ``username`` key, when present, is the user name. A secret with no
    ``username`` key, or a local run, uses ``username_var``, then ``neo4j``.
    Raises :class:`ConfigError` when neither the ARN nor ``password_var`` is
    set, or the secret cannot be read.
    """
    username = os.environ.get(username_var) or "neo4j"
    if secret_arn := os.environ.get(secret_arn_var, "").strip():
        secret = _read_secret(secret_arn, secret_arn_var)
        return Neo4jLogin(secret.username or username, secret.password)
    if password := os.environ.get(password_var):
        return Neo4jLogin(username, password)
    raise ConfigError(
        f"Set {secret_arn_var} to a Secrets Manager secret ARN, or set "
        f"{password_var} for a local run."
    )


def neo4j_login() -> Neo4jLogin:
    """Return the login for the fleet graph that the graph tools query.

    Reads ``NEO4J_PASSWORD_SECRET_ARN``, then ``NEO4J_USERNAME`` and
    ``NEO4J_PASSWORD``. Raises :class:`ConfigError` when neither the ARN nor
    the password is set.
    """
    return login_from(NEO4J_PASSWORD_SECRET_ARN, "NEO4J_USERNAME", "NEO4J_PASSWORD")


@cache
def _read_secret(secret_arn: str, secret_arn_var: str) -> _SecretLogin:
    """Fetch one secret once per process. A failure is not cached."""
    region = _arn_region(secret_arn, secret_arn_var)
    logger.info("Reading %s from Secrets Manager", secret_arn_var)
    try:
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_arn)
    except (ClientError, BotoCoreError) as e:
        failure = _failure_class(e)
    else:
        return _parse_secret(response.get("SecretString"), secret_arn_var)
    # The botocore message can name the role, the account, and the secret
    # ARN, so neither the log nor the error includes it. Both name only the
    # variable and the AWS error code. The raise is outside the except block,
    # so the botocore error is neither the cause nor the context of the
    # ConfigError, and no traceback prints it.
    logger.error("Could not read the secret in %s (%s)", secret_arn_var, failure)
    raise ConfigError(f"Could not read the secret in {secret_arn_var} ({failure}).")


def forget_secrets() -> None:
    """Drop the cached secrets, so the next read fetches each one again.

    Call it when a database rejects a password, in case the secret was
    rotated after it was cached.
    """
    _read_secret.cache_clear()


def _failure_class(error: ClientError | BotoCoreError) -> str:
    """The AWS error code, such as AccessDeniedException, or the class name."""
    if isinstance(error, ClientError):
        return error.response.get("Error", {}).get("Code") or type(error).__name__
    return type(error).__name__


def _arn_region(secret_arn: str, secret_arn_var: str) -> str:
    """Return the region field of a Secrets Manager ARN."""
    parts = secret_arn.split(":")
    if len(parts) < 7 or parts[0] != "arn" or parts[2] != "secretsmanager" or not parts[3]:
        raise ConfigError(f"{secret_arn_var} is not a Secrets Manager secret ARN.")
    return parts[3]


def _parse_secret(value: str | None, secret_arn_var: str) -> _SecretLogin:
    """Return the ``username`` and ``password`` keys of a JSON ``SecretString``.

    Error messages name the variable and never include the secret value.
    """
    if not value:
        raise ConfigError(f"The secret in {secret_arn_var} has no SecretString.")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    password = parsed.get("password") if isinstance(parsed, dict) else None
    if not isinstance(password, str) or not password:
        raise ConfigError(
            f"The secret in {secret_arn_var} must be a JSON object with a non-empty 'password' key."
        )
    username = parsed.get("username")
    if username is not None and (not isinstance(username, str) or not username):
        raise ConfigError(
            f"The 'username' key in the secret in {secret_arn_var} must be a non-empty string."
        )
    return _SecretLogin(username, password)
