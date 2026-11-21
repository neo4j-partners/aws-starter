"""Neo4j passwords from Secrets Manager, with a plain env var fallback.

In AgentCore Runtime, each password lives in Secrets Manager and the Runtime
gets only the secret ARN, for example ``MEM_NEO4J_PASSWORD_SECRET_ARN``. Local
runs set the password itself, for example ``MEM_NEO4J_PASSWORD``.
:func:`password_from` reads the secret when the ARN variable is set and falls
back to the password variable otherwise.

The secret value is a JSON object with a ``password`` key, the same shape as
an AWS database credentials secret. Other keys are ignored. Each secret is read
once per process, until :func:`forget_secrets` drops the cached values.
"""

from __future__ import annotations

import json
import logging
import os
from functools import cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from fleet_supervisor.core.config import ConfigError

logger = logging.getLogger(__name__)


def password_from(secret_arn_var: str, password_var: str) -> str:
    """Return the password named by ``secret_arn_var`` or ``password_var``.

    The secret ARN wins when both are set. Raises :class:`ConfigError` when
    neither is set or the secret cannot be read.
    """
    if secret_arn := os.environ.get(secret_arn_var, "").strip():
        return _read_secret(secret_arn, secret_arn_var)
    if password := os.environ.get(password_var):
        return password
    raise ConfigError(
        f"Set {secret_arn_var} to a Secrets Manager secret ARN, or set "
        f"{password_var} for a local run."
    )


@cache
def _read_secret(secret_arn: str, secret_arn_var: str) -> str:
    """Fetch one secret once per process. A failure is not cached."""
    region = _arn_region(secret_arn, secret_arn_var)
    logger.info("Reading %s from Secrets Manager", secret_arn_var)
    try:
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_arn)
    except (ClientError, BotoCoreError) as e:
        # The botocore message can name the role, the account, and the secret
        # ARN, so neither the log nor the error includes it. Both name only
        # the variable and the AWS error code. "from None" keeps the botocore
        # error out of the traceback that a startup failure prints.
        failure = _failure_class(e)
        logger.error("Could not read the secret in %s (%s)", secret_arn_var, failure)
        raise ConfigError(f"Could not read the secret in {secret_arn_var} ({failure}).") from None
    return _parse_secret(response.get("SecretString"), secret_arn_var)


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


def _parse_secret(value: str | None, secret_arn_var: str) -> str:
    """Return the ``password`` key of a JSON ``SecretString``.

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
    return password
