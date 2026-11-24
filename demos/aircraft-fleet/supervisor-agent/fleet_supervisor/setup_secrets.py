"""Create or update the two Secrets Manager secrets that the supervisor deploy reads.

``./agent.sh deploy`` passes the Runtime two secret ARNs instead of passwords:

- ``NEO4J_PASSWORD_SECRET_ARN`` names ``fleet/neo4j-reader``, the read-only
  login for the fleet graph. It comes from ``NEO4J_READER_USERNAME`` and
  ``NEO4J_READER_PASSWORD``, so ``NEO4J_USERNAME`` can stay the admin user the
  pipeline writes as.
- ``MEM_NEO4J_PASSWORD_SECRET_ARN`` names ``fleet/memory-neo4j``, the memory
  graph login. It comes from ``MEM_NEO4J_USERNAME``, default ``neo4j``, and
  ``MEM_NEO4J_PASSWORD``.

Each secret holds a JSON object with ``username`` and ``password`` keys, the
shape :mod:`fleet_supervisor.core.secrets` reads. The settings come from the
shared ``demos/aircraft-fleet/.env``, or the file ``FLEET_ENV_FILE`` names. A
non-empty value exported in the shell wins, as in ``agent.sh``.

The run is idempotent. A missing secret is created, a secret whose value
differs gets a new version, and a secret that already holds the value is left
alone. ``--dry-run`` reads the secrets and reports what a run would do,
without writing. The secrets use the AWS managed key and get no tags or
resource policies. The deploy grants the Runtime ``GetSecretValue`` on the
two exact ARNs, so it needs nothing more. The output never includes a
username or a password. At the end the run prints the two ARN lines to add to
``.env``. It does not write ``.env``.

Run it from ``supervisor-agent/`` with ``uv run fleet-supervisor-secrets``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, TextIO

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import dotenv_values

# agent.sh deploys to us-east-1 unless AWS_REGION is set.
DEFAULT_REGION = "us-east-1"


@dataclass(frozen=True)
class SecretSpec:
    """One deploy secret and the settings its value comes from."""

    name: str
    arn_var: str
    username_var: str
    password_var: str
    # The username when ``username_var`` is unset. None makes it required.
    default_username: str | None
    description: str


FLEET_SECRET = SecretSpec(
    name="fleet/neo4j-reader",
    arn_var="NEO4J_PASSWORD_SECRET_ARN",
    username_var="NEO4J_READER_USERNAME",
    password_var="NEO4J_READER_PASSWORD",
    default_username=None,
    description="Read-only Neo4j login for the aircraft fleet graph",
)
MEMORY_SECRET = SecretSpec(
    name="fleet/memory-neo4j",
    arn_var="MEM_NEO4J_PASSWORD_SECRET_ARN",
    username_var="MEM_NEO4J_USERNAME",
    password_var="MEM_NEO4J_PASSWORD",
    default_username="neo4j",
    description="Neo4j login for the aircraft fleet supervisor's memory graph",
)
SECRETS = (FLEET_SECRET, MEMORY_SECRET)

# Every setting the script reads.
SETTING_NAMES = (
    *(var for spec in SECRETS for var in (spec.username_var, spec.password_var)),
    "AWS_REGION",
)


class SetupError(RuntimeError):
    """A setting is missing or a secret is in a state the script will not change.

    The message names settings and secrets, never a value.
    """


class Action(StrEnum):
    """What a run does to one secret."""

    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class Outcome:
    """The action for one secret and its ARN. The ARN is None until it exists."""

    spec: SecretSpec
    action: Action
    arn: str | None


def default_env_file() -> Path:
    """The shared aircraft-fleet .env, or the file ``FLEET_ENV_FILE`` names."""
    if override := os.environ.get("FLEET_ENV_FILE"):
        return Path(override)
    return Path(__file__).resolve().parents[2] / ".env"


def load_settings(env_file: Path, environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Read :data:`SETTING_NAMES` from ``env_file``. A non-empty ``environ`` value wins.

    Unset and empty settings are left out. Raises :class:`SetupError` when the
    file does not exist.
    """
    if not env_file.is_file():
        raise SetupError(f"{env_file} not found. Copy ../.env.sample to ../.env and set it.")
    from_file = dotenv_values(env_file)
    settings: dict[str, str] = {}
    for name in SETTING_NAMES:
        value = (environ.get(name) or from_file.get(name) or "").strip()
        if value:
            settings[name] = value
    return settings


def secret_values(settings: Mapping[str, str]) -> dict[str, str]:
    """Return the JSON ``SecretString`` for each secret, keyed by secret name.

    Raises :class:`SetupError` that names every missing setting.
    """
    missing: list[str] = []
    values: dict[str, str] = {}
    for spec in SECRETS:
        username = settings.get(spec.username_var) or spec.default_username
        password = settings.get(spec.password_var)
        if username is None:
            missing.append(spec.username_var)
        if password is None:
            missing.append(spec.password_var)
        if username is not None and password is not None:
            values[spec.name] = json.dumps({"username": username, "password": password})
    if missing:
        raise SetupError(f"Set {', '.join(missing)} in the env file.")
    return values


def plan(client: Any, spec: SecretSpec, value: str) -> Outcome:
    """Compare the secret in AWS with ``value`` and return the action a run takes."""
    try:
        described = client.describe_secret(SecretId=spec.name)
    except ClientError as error:
        if _error_code(error) == "ResourceNotFoundException":
            return Outcome(spec, Action.CREATE, None)
        raise
    if "DeletedDate" in described:
        raise SetupError(
            f"{spec.name} is scheduled for deletion. Restore it with "
            f"`aws secretsmanager restore-secret --secret-id {spec.name}`, "
            "or wait for the deletion to finish, then run this again."
        )
    arn = described["ARN"]
    current = client.get_secret_value(SecretId=arn).get("SecretString")
    action = Action.UNCHANGED if _same_json(current, value) else Action.UPDATE
    return Outcome(spec, action, arn)


def apply(client: Any, outcome: Outcome, value: str) -> Outcome:
    """Carry out ``outcome`` and return it with the secret's ARN."""
    match outcome.action:
        case Action.CREATE:
            response = client.create_secret(
                Name=outcome.spec.name,
                Description=outcome.spec.description,
                SecretString=value,
            )
            return Outcome(outcome.spec, outcome.action, response["ARN"])
        case Action.UPDATE:
            client.put_secret_value(SecretId=outcome.arn, SecretString=value)
    return outcome


def run(client: Any, settings: Mapping[str, str], dry_run: bool, out: TextIO) -> list[Outcome]:
    """Plan every secret, then apply each change unless ``dry_run`` is set."""
    values = secret_values(settings)
    outcomes = [plan(client, spec, values[spec.name]) for spec in SECRETS]
    done: list[Outcome] = []
    for outcome in outcomes:
        if dry_run:
            verb = (
                "would stay unchanged"
                if outcome.action is Action.UNCHANGED
                else f"would {outcome.action}"
            )
        else:
            outcome = apply(client, outcome, values[outcome.spec.name])
            verb = {
                Action.CREATE: "created",
                Action.UPDATE: "updated with a new version",
                Action.UNCHANGED: "unchanged",
            }[outcome.action]
        print(f"{outcome.spec.name}: {verb} (from {_sources(outcome.spec, settings)})", file=out)
        done.append(outcome)
    return done


def print_env_lines(outcomes: list[Outcome], env_file: Path, dry_run: bool, out: TextIO) -> None:
    """Print the ARN lines to add to ``env_file``."""
    print("", file=out)
    when = "After a run without --dry-run, set" if dry_run else "Set"
    print(f"{when} these lines in {env_file}:", file=out)
    for outcome in outcomes:
        if outcome.arn is None:
            print(f"# {outcome.spec.arn_var}= is known once {outcome.spec.name} exists", file=out)
        else:
            print(f"{outcome.spec.arn_var}={outcome.arn}", file=out)


def main(argv: list[str] | None = None) -> int:
    """Create or update the deploy secrets. Returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="fleet-supervisor-secrets",
        description=(
            "Create or update the fleet/neo4j-reader and fleet/memory-neo4j secrets "
            "from the shared .env, then print the ARN lines to add to it."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="read the secrets and report changes without writing"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="env file to read (default: FLEET_ENV_FILE or ../.env)",
    )
    args = parser.parse_args(argv)
    env_file = args.env_file or default_env_file()
    try:
        settings = load_settings(env_file)
        region = settings.get("AWS_REGION", DEFAULT_REGION)
        print(f"Region: {region}{' (dry run)' if args.dry_run else ''}")
        client = boto3.client("secretsmanager", region_name=region)
        outcomes = run(client, settings, args.dry_run, sys.stdout)
    except SetupError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (ClientError, BotoCoreError) as error:
        # The botocore message can name the account and the role, so only the
        # error code is shown. No AWS call carries a value in its message.
        print(f"ERROR: Secrets Manager call failed ({_error_code(error)}).", file=sys.stderr)
        return 1
    print_env_lines(outcomes, env_file, args.dry_run, sys.stdout)
    return 0


def _sources(spec: SecretSpec, settings: Mapping[str, str]) -> str:
    """Name the settings a secret's value came from, without their values."""
    username = spec.username_var if spec.username_var in settings else "the default username"
    return f"{username} and {spec.password_var}"


def _same_json(current: str | None, value: str) -> bool:
    """True when ``current`` parses to the same JSON object as ``value``."""
    if not current:
        return False
    try:
        return json.loads(current) == json.loads(value)
    except json.JSONDecodeError:
        return False


def _error_code(error: ClientError | BotoCoreError) -> str:
    """The AWS error code, such as AccessDeniedException, or the class name."""
    if isinstance(error, ClientError):
        return error.response.get("Error", {}).get("Code") or type(error).__name__
    return type(error).__name__


if __name__ == "__main__":
    sys.exit(main())
