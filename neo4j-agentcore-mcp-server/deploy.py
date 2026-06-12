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
    cleanup      Delete stack, ECR repository, and password secret
    help         Show this help
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3
import httpx
from botocore.exceptions import ClientError

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"
# NEO4J_MCP_REPO is read from .env (path to the local Neo4j MCP server repo).
CDK_DIR = SCRIPT_DIR / "cdk"
CREDENTIALS_FILE = SCRIPT_DIR / ".mcp-credentials.json"

DEFAULT_REGION = "us-east-1"
DEFAULT_STACK_NAME = "neo4j-agentcore-mcp-server"
DEFAULT_ECR_REPO_NAME = "neo4j-mcp-server"

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
NO_NEO4J_CHECK = {"status", "cleanup", "credentials", "redeploy", "help"}


class DeployError(Exception):
    """Raised for any handled failure; main() prints it and exits 1."""


# ============================================================================
# Helper Functions
# ============================================================================


def log_info(message: str) -> None:
    print(f"INFO  {message}")


def log_error(message: str) -> None:
    print(f"ERROR {message}", file=sys.stderr)


def log_success(message: str) -> None:
    print(f"OK    {message}")


def log_step(message: str) -> None:
    print()
    print("=" * 70)
    print(message)
    print("=" * 70)


@dataclass
class Config:
    """Resolved configuration loaded from .env plus defaults."""

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


def load_env() -> Config:
    """Load .env into os.environ and resolve defaults (mirrors set -a; source)."""
    if not ENV_FILE.is_file():
        log_error(".env file not found in current directory")
        log_error("Copy .env.sample to .env and fill in your credentials")
        raise DeployError(".env not found")

    for key, value in _parse_env_file(ENV_FILE).items():
        os.environ[key] = value

    region = os.environ.get("AWS_REGION") or DEFAULT_REGION
    stack_name = os.environ.get("STACK_NAME") or DEFAULT_STACK_NAME
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
    """Ensure all required values are present."""
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


def _docker_ecr_login(aws: Aws, account_id: str, cfg: Config) -> None:
    log_info("Authenticating with ECR...")
    token = aws.client("ecr").get_authorization_token()
    auth = token["authorizationData"][0]["authorizationToken"]
    username, password = base64.b64decode(auth).decode().split(":", 1)
    registry = f"{account_id}.dkr.ecr.{cfg.aws_region}.amazonaws.com"
    subprocess.run(
        ["docker", "login", "--username", username, "--password-stdin", registry],
        input=password,
        text=True,
        check=True,
    )


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

    _docker_ecr_login(aws, account_id, cfg)

    log_info("Tagging image...")
    subprocess.run(
        ["docker", "tag", f"{cfg.ecr_repo_name}:{cfg.image_tag}",
         f"{ecr_uri}:{cfg.image_tag}"],
        check=True,
    )
    subprocess.run(
        ["docker", "tag", f"{cfg.ecr_repo_name}:{cfg.image_tag}",
         f"{ecr_uri}:latest"],
        check=True,
    )

    log_info("Pushing image to ECR...")
    subprocess.run(["docker", "push", f"{ecr_uri}:{cfg.image_tag}"], check=True)
    subprocess.run(["docker", "push", f"{ecr_uri}:latest"], check=True)

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
        print("Next steps:")
        print("  1. Generate credentials:  ./deploy.py credentials")
        print("  2. Test the deployment:   ./cloud.sh")


# ============================================================================
# Cleanup
# ============================================================================


def cmd_cleanup(aws: Aws, cfg: Config) -> None:
    log_step("Cleanup: Delete Stack and ECR Repository")

    log_info("This will delete:")
    log_info(f"  - CDK stack: {cfg.stack_name}")
    log_info(f"  - ECR repository: {cfg.ecr_repo_name}")
    print()

    reply = input("Are you sure you want to proceed? (y/N): ")
    if reply[:1] not in ("y", "Y"):
        log_info("Cleanup cancelled")
        return

    if stack_exists(aws, cfg):
        log_info(f"Deleting CDK stack: {cfg.stack_name}")
        setup_cdk_deps()
        subprocess.run(
            ["cdk", "destroy", cfg.stack_name, "--force"],
            cwd=CDK_DIR,
            env=_cdk_env(cfg),
            check=True,
        )
        log_success("Stack deleted")
    else:
        log_info("Stack does not exist, skipping")

    if ecr_repo_exists(aws, cfg):
        log_info(f"Deleting ECR repository: {cfg.ecr_repo_name}")
        aws.client("ecr").delete_repository(
            repositoryName=cfg.ecr_repo_name, force=True
        )
        log_success("ECR repository deleted")
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
    CREDENTIALS_FILE.write_text(json.dumps(credentials_data, indent=2))
    print("   Credentials written to .mcp-credentials.json")

    log_success("Credentials file generated")
    print()
    print("Usage:")
    print("  - File: .mcp-credentials.json")
    print("  - Token expires at the time shown in token_expires_at")
    print("  - Run './deploy.py credentials' to refresh the token")


# ============================================================================
# Help
# ============================================================================

HELP_TEXT = """\
Neo4j MCP Server - AgentCore Deployment Script (CDK)

Usage: ./deploy.py [command] [options]

Commands:
  (none)       Full deployment: build image, push to ECR, deploy stack
  redeploy     Fast redeploy: build, push, and update runtime (no stack changes)
  stack        Deploy CDK stack only (assumes image in ECR)
  synth        Synthesize CloudFormation template (dry run)
  status       Show stack status and outputs
  credentials  Generate .mcp-credentials.json with Gateway URL and JWT token
  cleanup      Delete the stack and ECR repository
  help         Show this help message

Options:
  --skip-build    Skip Docker build, just push existing image and deploy

Environment Variables (from .env):
  Required:
    NEO4J_URI          Neo4j connection string
    NEO4J_DATABASE     Database name
    NEO4J_USERNAME     Neo4j username (passed to container)
    NEO4J_PASSWORD     Neo4j password (stored in Secrets Manager)

  Optional:
    AWS_REGION         AWS region (default: us-east-1)
    STACK_NAME         CDK stack name (default: neo4j-agentcore-mcp-server)
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
"""


def cmd_help() -> None:
    print(HELP_TEXT)


# ============================================================================
# Main Entry Point
# ============================================================================


def main(argv: list[str]) -> int:
    args = argv[1:]
    skip_build = "--skip-build" in args
    command = args[0] if args else ""

    if command in ("help", "--help", "-h"):
        cmd_help()
        return 0

    cfg = load_env()
    validate_env(cfg)

    if command not in NO_NEO4J_CHECK:
        test_neo4j_connection(cfg)

    log_info("Configuration:")
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
        log_error(f"Command failed: {' '.join(map(str, exc.cmd))}")
        sys.exit(exc.returncode or 1)
