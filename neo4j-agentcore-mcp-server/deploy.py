#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "boto3>=1.35.0",
#     "httpx>=0.27.0",
#     "botocore[crt]",
# ]
# ///
"""Neo4j MCP Server - AgentCore Deployment Script (CDK).

Builds the Neo4j MCP server image, pushes to ECR, and deploys via AWS CDK.

Self-contained uv script (PEP 723); uv resolves the dependencies above
on first run. Invoke it directly or via uv:

    ./deploy.py [command] [options]
    uv run deploy.py [command] [options]

Commands:
    (none)       Full deployment (build, push, stack)
    redeploy     Fast redeploy (build, push, update runtime)
    stack        Deploy CDK stack only (assumes image in ECR)
    synth        Synthesize CloudFormation template (dry run)
    status       Show stack status and outputs
    credentials  Generate .mcp-credentials.json with Gateway URL and JWT token
    stack-name   Print the resolved stack name on stdout (for scripts)
    cleanup      Delete stack, ECR repository, and password secret
    help         Show this help

Multiple deployments:
    --env NAME selects .env.NAME instead of .env, and writes credentials to
    .mcp-credentials.NAME.json. The suffix is the only selector, so the
    config and its credentials can never be paired up wrongly.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3
import httpx
from botocore.exceptions import ClientError, WaiterError

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
# NEO4J_MCP_REPO is read from .env (path to the local Neo4j MCP server repo).
CDK_DIR = SCRIPT_DIR / "cdk"

# An optional --env suffix selects which deployment to act on, so several
# Neo4j instances can be deployed side by side from this directory. The
# suffix names both files, which is what keeps a config and its generated
# credentials from drifting apart.
#
# The suffix is appended to the stack name, so it has to leave the result valid
# for every resource derived from it: alphanumeric runs joined by single
# hyphens, and no underscores. Constrained to that here so "--env _foo" is
# reported against the value the caller typed rather than against a derived
# stack name they never wrote.
ENV_SUFFIX_PATTERN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")

DEFAULT_REGION = "us-east-1"
DEFAULT_STACK_NAME = "neo4j-agentcore-mcp-server"
DEFAULT_ECR_REPO_NAME = "neo4j-mcp-server"

# Every resource in the stack derives its name from STACK_NAME, so the shortest
# per-resource budget caps the stack name itself. The table of derived names is
# shared with the CDK stack (cdk/naming.py) so this script and the synth it
# eventually runs cannot disagree about what a usable stack name is, and so the
# length budget stays computed from the suffixes rather than written down.
# Checked here as well as at synth because CloudFormation only complains once a
# deploy is already underway, after the image has been built and pushed.
# Appended rather than prepended: cdk/ only has to be searched after the
# standard library, and putting it first would let a future cdk/<stdlib>.py
# shadow a real import in this script.
sys.path.append(str(CDK_DIR))
from naming import (  # noqa: E402  (needs CDK_DIR on sys.path first)
    MAX_STACK_NAME_LEN,
    STACK_NAME_PATTERN,
    STACK_NAME_RESERVED_WORDS,
    binding_length_constraint,
)

# CDK bootstrap normally attaches AdministratorAccess to the cfn-exec-role.
# Org SCPs commonly deny attaching AdministratorAccess (anti-privilege-
# escalation guardrail), so bootstrap with scoped policies instead. These
# cover the full stack (all services + IAM role creation) without using the
# AdministratorAccess ARN. Override via CDK_BOOTSTRAP_EXECUTION_POLICIES.
DEFAULT_CDK_BOOTSTRAP_EXECUTION_POLICIES = (
    "arn:aws:iam::aws:policy/PowerUserAccess,"
    "arn:aws:iam::aws:policy/IAMFullAccess"
)

# Commands that do not need Neo4j connectivity tested up front.
NO_NEO4J_CHECK = {"status", "cleanup", "credentials", "redeploy", "help", "stack-name"}


class DeployError(Exception):
    """Raised for any handled failure; main() prints it and exits 1."""


# ============================================================================
# Helper Functions
# ============================================================================


# Progress goes to stderr so stdout carries only what a caller asked for. That
# is what lets `./deploy.py stack-name` be captured with $(...) without picking
# up log lines, and it leaves the terminal output unchanged.
def log_info(message: str) -> None:
    print(f"INFO  {message}", file=sys.stderr)


def log_error(message: str) -> None:
    print(f"ERROR {message}", file=sys.stderr)


def log_success(message: str) -> None:
    print(f"OK    {message}", file=sys.stderr)


def log_step(message: str) -> None:
    print(file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(message, file=sys.stderr)
    print("=" * 70, file=sys.stderr)


def env_file(suffix: str) -> Path:
    """Path to the .env this invocation reads (.env, or .env.<suffix>)."""
    return SCRIPT_DIR / (f".env.{suffix}" if suffix else ".env")


def credentials_file(suffix: str) -> Path:
    """Path to the credentials file paired with this invocation's .env."""
    name = f".mcp-credentials.{suffix}.json" if suffix else ".mcp-credentials.json"
    return SCRIPT_DIR / name


@dataclass
class Config:
    """Resolved configuration loaded from .env plus defaults."""

    env_suffix: str
    neo4j_uri: str
    neo4j_database: str
    neo4j_username: str
    neo4j_password: str
    neo4j_mcp_repo: str
    aws_region: str
    stack_name: str
    ecr_repo_name: str
    image_tag: str
    cdk_bootstrap_execution_policies: str
    # Set by ensure_password_secret() before the stack deploy.
    neo4j_password_secret_arn: str = ""


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file.

    Supports `export KEY=VALUE`, `#` comments, blank lines, and optional
    surrounding single/double quotes. Shell expansion is not performed
    (the project's .env uses only literal values).
    """
    env: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env[key] = value
    return env


def load_env(suffix: str = "") -> Config:
    """Load .env into os.environ and resolve defaults (mirrors set -a; source)."""
    env_path = env_file(suffix)
    if not env_path.is_file():
        log_error(f"{env_path.name} file not found in {SCRIPT_DIR}")
        log_error(f"Copy .env.sample to {env_path.name} and fill in your credentials")
        raise DeployError(f"{env_path.name} not found")

    for key, value in _parse_env_file(env_path).items():
        os.environ[key] = value

    region = os.environ.get("AWS_REGION") or DEFAULT_REGION
    # Each deployment needs its own stack name - it namespaces the Cognito
    # domain, the IAM roles, the Gateway, and the Secrets Manager path. Deriving
    # it from the --env suffix makes that automatic, so a new .env.NAME cannot
    # silently deploy over an existing stack the way three hand-copied files
    # once did. An explicit STACK_NAME still wins.
    default_stack_name = f"{DEFAULT_STACK_NAME}-{suffix}" if suffix else DEFAULT_STACK_NAME
    stack_name = os.environ.get("STACK_NAME") or default_stack_name
    ecr_repo_name = os.environ.get("ECR_REPO_NAME") or DEFAULT_ECR_REPO_NAME
    neo4j_mcp_repo = os.environ.get("NEO4J_MCP_REPO", "")
    bootstrap_policies = (
        os.environ.get("CDK_BOOTSTRAP_EXECUTION_POLICIES")
        or DEFAULT_CDK_BOOTSTRAP_EXECUTION_POLICIES
    )

    image_tag = os.environ.get("IMAGE_TAG", "")
    if not image_tag:
        if neo4j_mcp_repo and (Path(neo4j_mcp_repo) / ".git").is_dir():
            image_tag = subprocess.run(
                ["git", "-C", neo4j_mcp_repo, "rev-parse", "--short=7", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            log_info(f"Image tag from git SHA: {image_tag}")
        else:
            image_tag = "latest"
            log_info(f"No git repo found at {neo4j_mcp_repo}, using tag: latest")

    return Config(
        env_suffix=suffix,
        neo4j_uri=os.environ.get("NEO4J_URI", ""),
        neo4j_database=os.environ.get("NEO4J_DATABASE", ""),
        neo4j_username=os.environ.get("NEO4J_USERNAME", ""),
        neo4j_password=os.environ.get("NEO4J_PASSWORD", ""),
        neo4j_mcp_repo=neo4j_mcp_repo,
        aws_region=region,
        stack_name=stack_name,
        ecr_repo_name=ecr_repo_name,
        image_tag=image_tag,
        cdk_bootstrap_execution_policies=bootstrap_policies,
    )


def validate_env(cfg: Config) -> None:
    """Ensure all required values are present and the stack name is usable."""
    required = {
        "NEO4J_URI": cfg.neo4j_uri,
        "NEO4J_DATABASE": cfg.neo4j_database,
        "NEO4J_USERNAME": cfg.neo4j_username,
        "NEO4J_PASSWORD": cfg.neo4j_password,
        "NEO4J_MCP_REPO": cfg.neo4j_mcp_repo,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        log_error("Missing required environment variables in .env:")
        for name in missing:
            log_error(f"  - {name}")
        raise DeployError("missing required environment variables")

    validate_stack_name(cfg.stack_name)


def validate_stack_name(stack_name: str) -> None:
    """Reject stack names that any derived resource name cannot accommodate."""
    if STACK_NAME_PATTERN.fullmatch(stack_name) is None:
        log_error(f"STACK_NAME '{stack_name}' is not a valid stack name")
        log_error(
            "It must start with a letter and hold only letters, digits, and "
            "single separating hyphens (no leading, trailing, or doubled hyphen)"
        )
        raise DeployError("invalid STACK_NAME")

    reserved = [w for w in STACK_NAME_RESERVED_WORDS if w in stack_name.lower()]
    if reserved:
        log_error(f"STACK_NAME '{stack_name}' contains {', '.join(reserved)}")
        log_error(
            "Cognito rejects those words in a domain prefix, and this stack's "
            f"prefix is '{stack_name.lower()}-<account-id>'"
        )
        raise DeployError("STACK_NAME contains a Cognito reserved word")

    if len(stack_name) > MAX_STACK_NAME_LEN:
        # Named from the table, so this keeps pointing at whichever resource is
        # actually the tightest if a suffix is ever renamed.
        binding = binding_length_constraint()
        log_error(
            f"STACK_NAME '{stack_name}' is {len(stack_name)} characters; "
            f"the limit is {MAX_STACK_NAME_LEN}"
        )
        log_error(
            f"'{binding.render(stack_name)}' would exceed the "
            f"{binding.max_length}-character limit on the {binding.resource}"
        )
        raise DeployError("STACK_NAME too long")


def test_neo4j_connection(cfg: Config) -> None:
    """Verify Neo4j connectivity with cypher-shell if it is available."""
    log_info("Testing Neo4j connectivity...")

    if shutil.which("cypher-shell") is None:
        log_error("cypher-shell not found - cannot verify Neo4j connectivity")
        log_error("Install with: brew install cypher-shell")
        log_error("Continuing without connectivity check...")
        return

    result = subprocess.run(
        [
            "cypher-shell",
            "-a", cfg.neo4j_uri,
            "-u", cfg.neo4j_username,
            "-p", cfg.neo4j_password,
            "-d", cfg.neo4j_database,
            "--non-interactive",
            "--format", "plain",
        ],
        input="RETURN 1 AS test;",
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        log_success("Neo4j connection successful")
        return

    log_error("Cannot connect to Neo4j database")
    log_error(f"  URI:      {cfg.neo4j_uri}")
    log_error(f"  Database: {cfg.neo4j_database}")
    log_error(f"  Username: {cfg.neo4j_username}")
    log_error("")
    log_error("Please verify:")
    log_error("  - Neo4j credentials are correct")
    log_error("  - Neo4j database is running and accessible")
    log_error("  - Network connectivity (firewall, VPN, etc.)")
    log_error("")
    log_error("Test manually with: ./test-neo4j-connection.sh")
    raise DeployError("Neo4j connection failed")


# --- AWS clients (one boto3 session; honours AWS_PROFILE / AWS_REGION) -------


# Error codes that mean "the resource is simply absent" (vs. an auth /
# throttling / permissions failure, which must not be silently swallowed).
_NOT_FOUND_CODES = {
    "ResourceNotFoundException",
    "RepositoryNotFoundException",
    "ValidationError",  # CloudFormation returns this when a stack is absent
}


def _exists(describe) -> bool:
    """True if describe() succeeds, False if it 404s, re-raise otherwise."""
    try:
        describe()
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in _NOT_FOUND_CODES:
            return False
        raise


class Aws:
    """Memoized boto3 clients bound to the configured region."""

    def __init__(self, region: str) -> None:
        self._session = boto3.Session(region_name=region)
        self.region = region
        self._clients: dict[str, object] = {}
        self._account_id: str | None = None

    def client(self, service: str):
        client = self._clients.get(service)
        if client is None:
            client = self._session.client(service)
            self._clients[service] = client
        return client

    @property
    def account_id(self) -> str:
        if self._account_id is None:
            self._account_id = self.client("sts").get_caller_identity()[
                "Account"
            ]
        return self._account_id


def get_ecr_uri(account_id: str, cfg: Config) -> str:
    return (
        f"{account_id}.dkr.ecr.{cfg.aws_region}.amazonaws.com/{cfg.ecr_repo_name}"
    )


def secret_name(cfg: Config) -> str:
    return f"{cfg.stack_name}/neo4j-password"


def ecr_repo_exists(aws: Aws, cfg: Config) -> bool:
    return _exists(
        lambda: aws.client("ecr").describe_repositories(
            repositoryNames=[cfg.ecr_repo_name]
        )
    )


def stack_exists(aws: Aws, cfg: Config) -> bool:
    return _exists(
        lambda: aws.client("cloudformation").describe_stacks(
            StackName=cfg.stack_name
        )
    )


def _stack_outputs(aws: Aws, stack_name: str) -> dict[str, str]:
    stacks = aws.client("cloudformation").describe_stacks(StackName=stack_name)
    outputs = stacks["Stacks"][0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}


def ensure_password_secret(aws: Aws, cfg: Config) -> None:
    """Store the Neo4j password in Secrets Manager and set the ARN on cfg.

    The password is never passed as a CloudFormation parameter or on the
    cdk CLI; the stack receives only the secret ARN and resolves the value
    via a CloudFormation {{resolve:secretsmanager}} dynamic reference.
    """
    sm = aws.client("secretsmanager")
    name = secret_name(cfg)

    if _exists(lambda: sm.describe_secret(SecretId=name)):
        log_info(f"Updating Secrets Manager secret: {name}")
        result = sm.put_secret_value(
            SecretId=name, SecretString=cfg.neo4j_password
        )
    else:
        log_info(f"Creating Secrets Manager secret: {name}")
        result = sm.create_secret(
            Name=name,
            Description=(
                f"Neo4j password for {cfg.stack_name} MCP server runtime"
            ),
            SecretString=cfg.neo4j_password,
        )

    arn = result.get("ARN", "")
    if not arn:
        log_error(f"Failed to resolve ARN for secret: {name}")
        raise DeployError("could not resolve secret ARN")
    cfg.neo4j_password_secret_arn = arn
    log_success("Neo4j password stored in Secrets Manager")


def setup_cdk_deps() -> None:
    log_info("Installing CDK dependencies...")
    subprocess.run(["uv", "sync", "--quiet"], cwd=CDK_DIR, check=True)


def _cdk_env(cfg: Config) -> dict[str, str]:
    env = os.environ.copy()
    env["JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION"] = "1"
    env["STACK_NAME"] = cfg.stack_name
    env["AWS_REGION"] = cfg.aws_region
    return env


# ============================================================================
# Build / Push
# ============================================================================


def cmd_build(cfg: Config) -> None:
    log_step("Building Neo4j MCP Server Image (ARM64)")

    repo = Path(cfg.neo4j_mcp_repo)
    if not repo.is_dir():
        log_error(f"Neo4j MCP repository not found at {cfg.neo4j_mcp_repo}")
        raise DeployError("MCP repository not found")
    if not (repo / "Dockerfile").is_file():
        log_error(f"Dockerfile not found in {cfg.neo4j_mcp_repo}")
        raise DeployError("Dockerfile not found")

    log_info(f"Repository: {cfg.neo4j_mcp_repo}")
    log_info(f"Image: {cfg.ecr_repo_name}:{cfg.image_tag} + latest")
    log_info("Platform: linux/arm64")
    print()

    subprocess.run(
        [
            "docker", "buildx", "build",
            "--platform", "linux/arm64",
            "--tag", f"{cfg.ecr_repo_name}:{cfg.image_tag}",
            "--tag", f"{cfg.ecr_repo_name}:latest",
            "--load",
            cfg.neo4j_mcp_repo,
        ],
        check=True,
    )
    log_success("Image built successfully")


# Unresolvable host used only to keep docker off the platform credential
# helper; see _isolated_docker_env(). Never contacted.
NO_CREDSTORE_MARKER = "deploy-py-no-credstore.invalid"


def _docker_context_host() -> str | None:
    """Endpoint of the user's active docker context, or None if undiscoverable.

    Read from the real config (no DOCKER_CONFIG override), because the throwaway
    config dir below has no contexts/ store.
    """
    try:
        result = subprocess.run(
            ["docker", "context", "inspect", "--format",
             "{{.Endpoints.docker.Host}}"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


@contextlib.contextmanager
def _isolated_docker_env() -> Iterator[dict[str, str]]:
    """Subprocess env pointing docker at a throwaway config with no credsStore.

    `docker login` does not just authenticate; it saves the credential through
    the `credsStore` named in ~/.docker/config.json (osxkeychain here). A stale
    keychain item for the registry makes that save fail with errSecDuplicateItem
    (-25299) even though the ECR token is perfectly good, and the helper's exit 1
    fails the whole push. Pointing DOCKER_CONFIG at a temp dir with no credsStore
    keeps the token in that dir for the life of the push, and never reads or
    writes the user's config or keychain.
    """
    with tempfile.TemporaryDirectory(prefix="deploy-docker-") as tmp_dir:
        config = Path(tmp_dir) / "config.json"
        # An empty "auths" map is not enough: the docker CLI treats a config
        # with no credentials at all as unconfigured and auto-detects the
        # platform helper (osxkeychain), putting us right back in the keychain.
        # One inert placeholder entry makes the config count as configured, so
        # the CLI stays on its plain-file store.
        config.write_text(json.dumps({"auths": {NO_CREDSTORE_MARKER: {}}}))
        config.chmod(0o600)  # briefly holds the ECR token in plaintext
        env = os.environ.copy()
        env["DOCKER_CONFIG"] = tmp_dir
        # Without contexts/, docker would silently fall back to the default
        # socket and miss OrbStack/Colima/etc. Carry the endpoint over instead.
        if host := _docker_context_host():
            env["DOCKER_HOST"] = host
        yield env


def _docker_ecr_login(
    aws: Aws, account_id: str, cfg: Config, env: dict[str, str]
) -> None:
    log_info("Authenticating with ECR...")
    token = aws.client("ecr").get_authorization_token()
    auth = token["authorizationData"][0]["authorizationToken"]
    username, password = base64.b64decode(auth).decode().split(":", 1)
    registry = f"{account_id}.dkr.ecr.{cfg.aws_region}.amazonaws.com"
    try:
        subprocess.run(
            ["docker", "login", "--username", username, "--password-stdin", registry],
            input=password,
            text=True,
            check=True,
            capture_output=True,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        log_error(f"docker login failed for {registry} (exit {exc.returncode})")
        for stream in (exc.stdout, exc.stderr):
            if stream and stream.strip():
                log_error(stream.strip())
        log_error(
            "ECR issued the authorization token, so the AWS side is fine - this "
            "is docker failing to use it. The local credential store is already "
            "bypassed for this login, so it is not a keychain/credsStore "
            "problem. Check that the docker daemon is running at "
            f"{env.get('DOCKER_HOST', 'the default socket')} (`docker version`) "
            f"and that {registry} is reachable."
        )
        raise DeployError("docker login failed") from exc
    log_success("Authenticated with ECR")


def cmd_push(aws: Aws, cfg: Config) -> None:
    log_step("Pushing Image to ECR")

    account_id = aws.account_id
    ecr_uri = get_ecr_uri(account_id, cfg)

    log_info(f"Account: {account_id}")
    log_info(f"Region: {cfg.aws_region}")
    log_info(f"Repository: {cfg.ecr_repo_name}")
    log_info(f"ECR URI: {ecr_uri}")
    print()

    if not ecr_repo_exists(aws, cfg):
        log_info(f"Creating ECR repository: {cfg.ecr_repo_name}")
        aws.client("ecr").create_repository(
            repositoryName=cfg.ecr_repo_name,
            imageScanningConfiguration={"scanOnPush": True},
        )
        log_success("ECR repository created")
    else:
        log_info("ECR repository already exists")

    # Login, tag and push all share one throwaway docker config, so the token
    # written by `docker login` is visible to `docker push` and is deleted with
    # the temp dir when the push finishes.
    with _isolated_docker_env() as docker_env:
        _docker_ecr_login(aws, account_id, cfg, docker_env)

        log_info("Tagging image...")
        subprocess.run(
            ["docker", "tag", f"{cfg.ecr_repo_name}:{cfg.image_tag}",
             f"{ecr_uri}:{cfg.image_tag}"],
            check=True,
            env=docker_env,
        )
        subprocess.run(
            ["docker", "tag", f"{cfg.ecr_repo_name}:{cfg.image_tag}",
             f"{ecr_uri}:latest"],
            check=True,
            env=docker_env,
        )

        log_info("Pushing image to ECR...")
        subprocess.run(
            ["docker", "push", f"{ecr_uri}:{cfg.image_tag}"],
            check=True,
            env=docker_env,
        )
        subprocess.run(
            ["docker", "push", f"{ecr_uri}:latest"], check=True, env=docker_env
        )

    log_success(
        f"Image pushed successfully: {ecr_uri}:{cfg.image_tag} + latest"
    )


# ============================================================================
# Stack (CDK Deploy)
# ============================================================================


def _cdk_deploy(cfg: Config, full_image_uri: str) -> int:
    proc = subprocess.run(
        [
            "cdk", "deploy", cfg.stack_name,
            "--require-approval", "never",
            "--parameters", f"ECRImageUri={full_image_uri}",
            "--parameters", f"Neo4jUri={cfg.neo4j_uri}",
            "--parameters", f"Neo4jDatabase={cfg.neo4j_database}",
            "--parameters", f"Neo4jUsername={cfg.neo4j_username}",
            "--parameters",
            f"Neo4jPasswordSecretArn={cfg.neo4j_password_secret_arn}",
        ],
        cwd=CDK_DIR,
        env=_cdk_env(cfg),
    )
    return proc.returncode


def cmd_stack(aws: Aws, cfg: Config) -> None:
    log_step("Deploying CDK Stack")

    account_id = aws.account_id
    ecr_uri = get_ecr_uri(account_id, cfg)
    full_image_uri = f"{ecr_uri}:{cfg.image_tag}"

    log_info(f"Stack Name: {cfg.stack_name}")
    log_info(f"Region: {cfg.aws_region}")
    log_info(f"Image URI: {full_image_uri}")
    log_info(f"Neo4j URI: {cfg.neo4j_uri}")
    print()

    # Store the Neo4j password in Secrets Manager (sets the ARN on cfg).
    ensure_password_secret(aws, cfg)

    setup_cdk_deps()

    cfn = aws.client("cloudformation")
    if not _exists(lambda: cfn.describe_stacks(StackName="CDKToolkit")):
        log_info("CDK not bootstrapped in this region, bootstrapping...")
        log_info(
            "CFN execution policies: "
            f"{cfg.cdk_bootstrap_execution_policies}"
        )
        bootstrap_cmd = [
            "cdk", "bootstrap", f"aws://{account_id}/{cfg.aws_region}",
        ]
        if cfg.cdk_bootstrap_execution_policies:
            bootstrap_cmd += [
                "--cloudformation-execution-policies",
                cfg.cdk_bootstrap_execution_policies,
            ]
        subprocess.run(
            bootstrap_cmd,
            cwd=CDK_DIR,
            env=_cdk_env(cfg),
            check=True,
        )

    log_info("Deploying CDK stack (this may take 5-10 minutes)...")

    if _cdk_deploy(cfg, full_image_uri) == 0:
        log_success("Stack deployment complete")
    else:
        try:
            stacks = cfn.describe_stacks(StackName=cfg.stack_name)
            stack_status = stacks["Stacks"][0]["StackStatus"]
        except ClientError:
            stack_status = "DOES_NOT_EXIST"

        if stack_status == "ROLLBACK_COMPLETE":
            log_info(
                "First deployment failed (Runtime may need time to "
                "stabilize). Cleaning up and retrying..."
            )
            cfn.delete_stack(StackName=cfg.stack_name)
            cfn.get_waiter("stack_delete_complete").wait(
                StackName=cfg.stack_name
            )

            log_info("Waiting 30 seconds for services to stabilize...")
            time.sleep(30)

            log_info("Retrying deployment...")
            if _cdk_deploy(cfg, full_image_uri) != 0:
                log_error("Deployment failed on retry")
                raise DeployError("deployment failed on retry")
            log_success("Stack deployment complete (on retry)")
        else:
            log_error(f"Deployment failed with status: {stack_status}")
            raise DeployError(f"deployment failed: {stack_status}")
    print()

    cmd_status(aws, cfg)


# ============================================================================
# Synth (Dry Run)
# ============================================================================


def cmd_synth(aws: Aws, cfg: Config) -> None:
    log_step("Synthesizing CloudFormation Template")

    _ = aws.account_id  # Mirror original: validate credentials early.

    setup_cdk_deps()

    subprocess.run(
        ["cdk", "synth", cfg.stack_name],
        cwd=CDK_DIR,
        env=_cdk_env(cfg),
        check=True,
    )

    log_success("Template synthesized successfully")
    log_info("Output is in cdk/cdk.out/")


# ============================================================================
# Status
# ============================================================================


def cmd_status(aws: Aws, cfg: Config) -> None:
    log_step("Stack Status and Outputs")

    try:
        stacks = aws.client("cloudformation").describe_stacks(
            StackName=cfg.stack_name
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] in _NOT_FOUND_CODES:
            log_error(
                f"Stack '{cfg.stack_name}' does not exist in region "
                f"'{cfg.aws_region}'"
            )
            raise DeployError("stack does not exist") from exc
        raise

    stack = stacks["Stacks"][0]
    status = stack["StackStatus"]

    log_info(f"Stack Status: {status}")
    print()

    if "COMPLETE" in status and "DELETE" not in status:
        outputs = {
            o["OutputKey"]: o["OutputValue"]
            for o in stack.get("Outputs", [])
        }
        print("Stack Outputs:")
        print("-" * 68)
        print(f"  Gateway URL: {outputs.get('GatewayUrl', '')}")
        print(
            f"  Cognito Client ID: {outputs.get('CognitoMachineClientId', '')}"
        )
        print(f"  Token URL: {outputs.get('CognitoTokenUrl', '')}")
        print(f"  Runtime ARN: {outputs.get('MCPServerRuntimeArn', '')}")
        print()
        env_flag = f" --env {cfg.env_suffix}" if cfg.env_suffix else ""
        print("Next steps:")
        print(f"  1. Generate credentials:  ./deploy.py{env_flag} credentials")
        print(f"  2. Test the deployment:   ./cloud.sh{env_flag}")


# ============================================================================
# Cleanup
# ============================================================================


def _find_runtime_id(aws: Aws, cfg: Config) -> str:
    """Runtime ID for this stack, or "" if there is no such runtime.

    Prefers the stack output and falls back to a name lookup, since a stack
    left in DELETE_FAILED may no longer report its outputs.
    """
    with contextlib.suppress(ClientError):
        runtime_id = _stack_outputs(aws, cfg.stack_name).get("MCPServerRuntimeId")
        if runtime_id:
            return runtime_id

    # Same derivation as the stack's _create_agent_runtime().
    runtime_name = cfg.stack_name.replace("-", "_")
    client = aws.client("bedrock-agentcore-control")
    kwargs: dict = {}
    while True:
        page = client.list_agent_runtimes(**kwargs)
        for runtime in page.get("agentRuntimes", []):
            if runtime.get("agentRuntimeName") == runtime_name:
                return runtime.get("agentRuntimeId", "")
        token = page.get("nextToken")
        if not token:
            return ""
        kwargs["nextToken"] = token


def _delete_agent_runtime(
    aws: Aws, cfg: Config, timeout: int = 600, delay: int = 10
) -> None:
    """Delete the AgentCore runtime out of band and wait for it to disappear.

    CloudFormation's AWS::BedrockAgentCore::Runtime handler gives up with
    NotStabilized before AgentCore finishes deleting a runtime, which drops the
    whole stack into DELETE_FAILED. Deleting the runtime here first (and waiting
    as long as it actually takes) leaves the stack's own delete a no-op.
    """
    runtime_id = _find_runtime_id(aws, cfg)
    if not runtime_id:
        log_info("No AgentCore runtime found, skipping")
        return

    client = aws.client("bedrock-agentcore-control")
    log_info(f"Deleting AgentCore runtime: {runtime_id}")
    try:
        client.delete_agent_runtime(agentRuntimeId=runtime_id)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in _NOT_FOUND_CODES:
            raise
        return

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _exists(lambda: client.get_agent_runtime(agentRuntimeId=runtime_id)):
            log_success("Runtime deleted")
            return
        log_info(f"Runtime still deleting, waiting {delay}s...")
        time.sleep(delay)

    # Not fatal: cdk destroy runs next and may still finish the job.
    log_error(f"Runtime {runtime_id} still present after {timeout}s")


def _retry_stack_delete(aws: Aws, cfg: Config) -> bool:
    """Delete the stack directly after cdk destroy failed. True if it is gone."""
    if not stack_exists(aws, cfg):
        return True

    log_info("cdk destroy failed; retrying the stack delete directly...")
    cfn = aws.client("cloudformation")
    try:
        cfn.delete_stack(StackName=cfg.stack_name)
        cfn.get_waiter("stack_delete_complete").wait(
            StackName=cfg.stack_name,
            WaiterConfig={"Delay": 15, "MaxAttempts": 80},
        )
    except (ClientError, WaiterError) as exc:
        log_error(f"Stack delete retry failed: {exc}")
        return False
    return True


def cmd_cleanup(aws: Aws, cfg: Config) -> None:
    log_step("Cleanup: Delete Stack and ECR Repository")

    log_info("This will delete:")
    log_info(f"  - AgentCore runtime and CDK stack: {cfg.stack_name}")
    log_info(f"  - Secrets Manager secret: {secret_name(cfg)}")
    log_info(f"  - ECR repository: {cfg.ecr_repo_name} (confirmed separately)")
    print()

    reply = input("Are you sure you want to proceed? (y/N): ")
    if reply[:1] not in ("y", "Y"):
        log_info("Cleanup cancelled")
        return

    stack_deleted = True
    if stack_exists(aws, cfg):
        _delete_agent_runtime(aws, cfg)

        log_info(f"Deleting CDK stack: {cfg.stack_name}")
        setup_cdk_deps()
        result = subprocess.run(
            ["cdk", "destroy", cfg.stack_name, "--force"],
            cwd=CDK_DIR,
            env=_cdk_env(cfg),
        )
        # A failed destroy must not strand the ECR and secret cleanup below, so
        # this reports at the end rather than raising here.
        stack_deleted = result.returncode == 0 or _retry_stack_delete(aws, cfg)
        if stack_deleted:
            log_success("Stack deleted")
    else:
        log_info("Stack does not exist, skipping")

    if ecr_repo_exists(aws, cfg):
        log_info(
            f"ECR repository '{cfg.ecr_repo_name}' is shared by every env suffix - "
            "deleting it removes the image other deployments run on."
        )
        reply = input(f"Delete ECR repository '{cfg.ecr_repo_name}'? (y/N): ")
        if reply[:1] in ("y", "Y"):
            aws.client("ecr").delete_repository(
                repositoryName=cfg.ecr_repo_name, force=True
            )
            log_success("ECR repository deleted")
        else:
            log_info("Leaving ECR repository in place")
    else:
        log_info("ECR repository does not exist, skipping")

    sm = aws.client("secretsmanager")
    name = secret_name(cfg)
    if _exists(lambda: sm.describe_secret(SecretId=name)):
        log_info(f"Deleting Secrets Manager secret: {name}")
        sm.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
        log_success("Secret deleted")
    else:
        log_info("Secret does not exist, skipping")

    if not stack_deleted:
        log_error(f"Stack '{cfg.stack_name}' was not deleted.")
        log_error("Everything else was cleaned up. Check the stack events with:")
        log_error(
            f"  aws cloudformation describe-stack-events "
            f"--stack-name {cfg.stack_name} --max-items 20"
        )
        raise DeployError("stack delete failed")

    log_success("Cleanup complete")


# ============================================================================
# Redeploy (build + push + update runtime)
# ============================================================================


def cmd_redeploy(aws: Aws, cfg: Config) -> None:
    log_step("Redeploying MCP Server (build + push + update runtime)")

    if not stack_exists(aws, cfg):
        log_error(
            f"Stack '{cfg.stack_name}' does not exist. Run './deploy.py' "
            "for initial deployment."
        )
        raise DeployError("stack does not exist")

    cmd_build(cfg)
    cmd_push(aws, cfg)

    log_info("Getting runtime configuration from stack...")
    outputs = _stack_outputs(aws, cfg.stack_name)
    runtime_id = outputs.get("MCPServerRuntimeId", "")
    role_arn = outputs.get("AgentExecutionRoleArn", "")

    if not runtime_id or not role_arn:
        log_error("Could not retrieve runtime info from stack outputs")
        raise DeployError("missing runtime outputs")

    account_id = aws.account_id
    ecr_uri = get_ecr_uri(account_id, cfg)
    full_image_uri = f"{ecr_uri}:{cfg.image_tag}"

    log_step("Updating AgentCore Runtime")
    log_info(f"Runtime ID: {runtime_id}")
    log_info(f"New Image: {full_image_uri}")
    print()

    # NOTE: faithful port of the original script - this updates only the
    # container image, role, and network mode (UpdateAgentRuntime is a full
    # replacement, so env vars / authorizer / protocol are NOT re-sent here).
    aws.client("bedrock-agentcore-control").update_agent_runtime(
        agentRuntimeId=runtime_id,
        agentRuntimeArtifact={
            "containerConfiguration": {"containerUri": full_image_uri}
        },
        roleArn=role_arn,
        networkConfiguration={"networkMode": "PUBLIC"},
    )

    log_success("Runtime update initiated")
    log_info("The runtime will redeploy with the new image.")
    log_info("Check status with: ./deploy.py status")


# ============================================================================
# Credentials
# ============================================================================


def _wait_for_dns(hostname: str, max_attempts: int = 30, delay: int = 10) -> bool:
    print(f"   Waiting for DNS propagation for {hostname}...")
    for attempt in range(max_attempts):
        try:
            socket.gethostbyname(hostname)
            print("   DNS resolved successfully")
            return True
        except socket.gaierror:
            if attempt < max_attempts - 1:
                print(
                    f"   DNS not ready, waiting {delay}s... "
                    f"(attempt {attempt + 1}/{max_attempts})"
                )
                time.sleep(delay)
    return False


def cmd_credentials(aws: Aws, cfg: Config) -> None:
    log_step("Generating MCP Credentials")

    if not stack_exists(aws, cfg):
        log_error(
            f"Stack '{cfg.stack_name}' does not exist. Run ./deploy.py first."
        )
        raise DeployError("stack does not exist")

    log_info("Retrieving stack outputs...")
    outputs = _stack_outputs(aws, cfg.stack_name)
    gateway_url = outputs.get("GatewayUrl", "")
    user_pool_id = outputs.get("CognitoUserPoolId", "")
    client_id = outputs.get("CognitoMachineClientId", "")
    token_url = outputs.get("CognitoTokenUrl", "")
    scope = outputs.get("CognitoScope", "")

    if not gateway_url or not client_id:
        log_error("Could not retrieve required stack outputs")
        raise DeployError("missing required stack outputs")

    log_info(f"Gateway URL: {gateway_url}")
    log_info(f"Client ID: {client_id}")
    log_info("Fetching client secret and JWT token...")

    print("   Getting client secret from Cognito...")
    cognito = aws.client("cognito-idp")
    response = cognito.describe_user_pool_client(
        UserPoolId=user_pool_id, ClientId=client_id
    )
    client_secret = response["UserPoolClient"]["ClientSecret"]
    print(f"   Client secret retrieved ({len(client_secret)} chars)")

    parsed = urlparse(token_url)
    if not _wait_for_dns(parsed.hostname):
        print(
            f"   ERROR: DNS did not resolve for {parsed.hostname} after "
            "multiple attempts"
        )
        print(
            "   The Cognito domain may still be propagating. Try again in a "
            "few minutes:"
        )
        print("   ./deploy.py credentials")
        raise DeployError("Cognito DNS did not resolve")

    print("   Requesting JWT token...")
    creds = base64.b64encode(
        f"{client_id}:{client_secret}".encode()
    ).decode()
    headers = {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials", "scope": scope}

    max_retries = 3
    token_response: dict | None = None
    for retry in range(max_retries):
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(token_url, headers=headers, data=data)
                resp.raise_for_status()
                token_response = resp.json()
            break
        except httpx.ConnectError as exc:
            if retry < max_retries - 1:
                print(
                    f"   Connection error, retrying in 10s... "
                    f"({retry + 1}/{max_retries})"
                )
                time.sleep(10)
            else:
                print(
                    "   ERROR: Failed to connect to token endpoint after "
                    f"{max_retries} attempts"
                )
                print(f"   Error: {exc}")
                raise DeployError("token endpoint connection failed") from exc

    if token_response is None:
        raise DeployError("token endpoint did not return a response")
    access_token = token_response["access_token"]
    expires_in = token_response.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    print(f"   Token retrieved (expires in {expires_in}s)")

    credentials_data = {
        "gateway_url": gateway_url,
        "token_url": token_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope,
        "access_token": access_token,
        "token_expires_at": expires_at.isoformat(),
        "region": cfg.aws_region,
        "stack_name": cfg.stack_name,
    }
    output_path = credentials_file(cfg.env_suffix)
    output_path.write_text(json.dumps(credentials_data, indent=2))
    print(f"   Credentials written to {output_path.name}")

    log_success("Credentials file generated")
    print()
    print("Usage:")
    print(f"  - File: {output_path.name}")
    print("  - Token expires at the time shown in token_expires_at")
    print("  - Run './deploy.py credentials' to refresh the token")


# ============================================================================
# Help
# ============================================================================

HELP_TEXT = f"""\
Neo4j MCP Server - AgentCore Deployment Script (CDK)

Usage: ./deploy.py [command] [options]

Commands:
  (none)       Full deployment: build image, push to ECR, deploy stack
  redeploy     Fast redeploy: build, push, and update runtime (no stack changes)
  stack        Deploy CDK stack only (assumes image in ECR)
  synth        Synthesize CloudFormation template (dry run)
  status       Show stack status and outputs
  credentials  Generate .mcp-credentials.json with Gateway URL and JWT token
  stack-name   Print the resolved stack name (for scripts)
  cleanup      Delete the stack and ECR repository
  help         Show this help message

Options:
  --skip-build    Skip Docker build, just push existing image and deploy
  --env NAME      Act on the deployment configured in .env.NAME instead of
                  .env, writing its credentials to .mcp-credentials.NAME.json.
                  May also be given as MCP_ENV=NAME in the environment.

Multiple Deployments:
  Each deployment is one .env.NAME file, and the NAME suffix picks both the
  config and its credentials file, so the two cannot drift apart:

    .env.fleet    ->  ./deploy.py --env fleet     ->  .mcp-credentials.fleet.json
    .env.finance  ->  ./deploy.py --env finance   ->  .mcp-credentials.finance.json
    .env          ->  ./deploy.py                 ->  .mcp-credentials.json

  The stack name is derived from the suffix, so each deployment is namespaced
  automatically and no .env.NAME file needs to set STACK_NAME:

    ./deploy.py --env fleet   ->  neo4j-agentcore-mcp-server-fleet
    ./deploy.py               ->  neo4j-agentcore-mcp-server

  That name namespaces the Cognito domain, the IAM roles, the Gateway, and the
  Secrets Manager password path. Setting STACK_NAME in a .env.NAME file
  overrides the derived name; it must stay unique per deployment, since a
  shared name means the second deployment overwrites the first.

  Deployments sharing one MCP server image can keep the same ECR_REPO_NAME and
  NEO4J_MCP_REPO; the image is built and pushed once per deploy either way.

Environment Variables (from .env):
  Required:
    NEO4J_URI          Neo4j connection string
    NEO4J_DATABASE     Database name
    NEO4J_USERNAME     Neo4j username (passed to container)
    NEO4J_PASSWORD     Neo4j password (stored in Secrets Manager)

  Optional:
    AWS_REGION         AWS region (default: us-east-1)
    STACK_NAME         CDK stack name (default: neo4j-agentcore-mcp-server,
                       plus -NAME when --env NAME is given; max {MAX_STACK_NAME_LEN} chars,
                       letters and digits joined by single hyphens, must start
                       with a letter, and may not contain aws/amazon/cognito,
                       which Cognito forbids in the derived domain prefix)
    ECR_REPO_NAME      ECR repository name (default: neo4j-mcp-server)
    IMAGE_TAG          Docker image tag (default: git short SHA from MCP repo)
    CDK_BOOTSTRAP_EXECUTION_POLICIES
                       Comma-separated managed policy ARNs for the CDK
                       cfn-exec-role (default: PowerUserAccess + IAMFullAccess;
                       avoids AdministratorAccess, which org SCPs often deny)

Examples:
  ./deploy.py                   # Full deployment (build + push + stack)
  ./deploy.py redeploy          # Fast redeploy (build + push + update runtime)
  ./deploy.py --skip-build      # Push existing image and deploy stack
  ./deploy.py stack             # Deploy stack only
  ./deploy.py synth             # Generate CloudFormation template
  ./deploy.py status            # Check deployment status
  ./deploy.py credentials       # Generate credentials file for MCP clients
  ./deploy.py cleanup           # Remove everything

  ./deploy.py --env fleet              # Deploy the .env.fleet deployment
  ./deploy.py --env fleet credentials  # Write .mcp-credentials.fleet.json
  ./deploy.py --env fleet status       # Status of the .env.fleet stack
"""


def cmd_help() -> None:
    print(HELP_TEXT)


# ============================================================================
# Main Entry Point
# ============================================================================


def _extract_env_suffix(args: list[str]) -> tuple[str, list[str]]:
    """Split `--env NAME` / `--env=NAME` out of the argument list.

    Defaults to the MCP_ENV variable so the shell wrappers can forward a
    selection they already parsed. Returns the suffix and the args with the
    flag removed, leaving command detection unchanged.
    """
    suffix = os.environ.get("MCP_ENV", "")
    remaining: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--env":
            if i + 1 >= len(args):
                log_error("--env requires a name, for example: --env fleet")
                raise DeployError("--env is missing its value")
            suffix = args[i + 1]
            i += 2
        elif arg.startswith("--env="):
            suffix = arg[len("--env=") :]
            i += 1
        else:
            remaining.append(arg)
            i += 1

    if suffix and ENV_SUFFIX_PATTERN.fullmatch(suffix) is None:
        log_error(f"Invalid --env name: {suffix!r}")
        log_error(
            "Use letters and digits joined by single hyphens. The name becomes "
            "part of the stack name, which permits nothing else."
        )
        raise DeployError("invalid --env name")

    return suffix, remaining


def main(argv: list[str]) -> int:
    suffix, args = _extract_env_suffix(argv[1:])
    skip_build = "--skip-build" in args
    command = args[0] if args else ""

    if command in ("help", "--help", "-h"):
        cmd_help()
        return 0

    cfg = load_env(suffix)

    # Bare stack name on stdout, nothing else, so the shell scripts can resolve
    # a deployment the same way this script does instead of keeping their own
    # copy of the naming rule. Ahead of validate_env because the resolved name
    # is all this command reports: failing it over an unset NEO4J_MCP_REPO would
    # break a caller's $(...) on a value the answer does not depend on.
    if command == "stack-name":
        validate_stack_name(cfg.stack_name)
        print(cfg.stack_name)
        return 0

    validate_env(cfg)

    if command not in NO_NEO4J_CHECK:
        test_neo4j_connection(cfg)

    log_info("Configuration:")
    log_info(f"  Env File: {env_file(cfg.env_suffix).name}")
    log_info(f"  Region: {cfg.aws_region}")
    log_info(f"  Stack Name: {cfg.stack_name}")
    log_info(f"  ECR Repository: {cfg.ecr_repo_name}")

    aws = Aws(cfg.aws_region)

    if command in ("", "--skip-build"):
        if skip_build:
            log_info("Skipping Docker build (--skip-build)")
        else:
            cmd_build(cfg)
        cmd_push(aws, cfg)
        cmd_stack(aws, cfg)
    elif command == "redeploy":
        cmd_redeploy(aws, cfg)
    elif command == "stack":
        cmd_stack(aws, cfg)
    elif command == "synth":
        cmd_synth(aws, cfg)
    elif command == "status":
        cmd_status(aws, cfg)
    elif command == "credentials":
        cmd_credentials(aws, cfg)
    elif command == "cleanup":
        cmd_cleanup(aws, cfg)
    else:
        log_error(f"Unknown command: {command}")
        print()
        cmd_help()
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except DeployError:
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    except subprocess.CalledProcessError as exc:
        log_error(
            f"Command failed (exit {exc.returncode}): "
            f"{' '.join(map(str, exc.cmd))}"
        )
        # Only set when the caller captured output; otherwise the child already
        # printed its own error straight to the terminal.
        for stream in (exc.stdout, exc.stderr):
            if isinstance(stream, str) and stream.strip():
                log_error(stream.strip())
        sys.exit(exc.returncode or 1)
