"""Resource names derived from the stack name, and the limits they have to meet.

Imported by both deploy.py and neo4j_mcp_stack.py so the constraint is stated
once. deploy.py needs it before anything is built, to reject an unusable
STACK_NAME in milliseconds; the stack needs it at synth, because CDK validates
only the two L2 names it owns (the IAM role and the Lambda function) and leaves
every AgentCore and Cognito L1 name unchecked until CloudFormation is already
running, by which point the image has been built and pushed.

MAX_STACK_NAME_LEN is computed from the table rather than written down, so the
budget cannot drift from the suffixes it is derived from. Rename a suffix and
the binding constraint moves on its own.

Deliberately free of third-party imports (re and dataclasses only): deploy.py is
a self-contained PEP 723 script resolved against its own dependency set, and it
must be able to import this without pulling in aws_cdk.

Limits and patterns come from the service API models (botocore service-2.json
for iam, lambda, cognito-idp, and bedrock-agentcore-control), plus the Cognito
reserved-term rule documented at
https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-assign-domain.html
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Account IDs are always 12 digits, so the Cognito domain prefix budget is
# checkable even when the account is still an unresolved token at synth.
_ACCOUNT_ID_WIDTH = 12

_IAM_ROLE_NAME = re.compile(r"[\w+=,.@-]+")
_LAMBDA_FUNCTION_NAME = re.compile(r"[a-zA-Z0-9-_]+")
_COGNITO_NAME = re.compile(r"[\w\s+=,.@-]+")


@dataclass(frozen=True)
class DerivedName:
    """One resource name built from the stack name, with the limits it must meet."""

    resource: str
    pattern: re.Pattern[str]
    # None where the pattern already bounds the length. The AgentCore gateway
    # name caps repetitions rather than characters, so a character count would
    # reject names the service accepts.
    max_length: int | None = None
    suffix: str = ""
    lowercase: bool = False
    underscores: bool = False
    # Substrings the service refuses whatever the pattern allows.
    forbidden: tuple[str, ...] = ()

    def render(self, stack_name: str) -> str:
        base = stack_name.lower() if self.lowercase else stack_name
        if self.underscores:
            base = base.replace("-", "_")
        return f"{base}{self.suffix}"

    def stack_name_budget(self) -> int | None:
        """Longest stack name this name can hold, or None if length is unbounded."""
        if self.max_length is None:
            return None
        return self.max_length - len(self.render(""))


DERIVED_NAMES: tuple[DerivedName, ...] = (
    DerivedName("Cognito user pool name", _COGNITO_NAME, 128, suffix="-user-pool"),
    DerivedName(
        "Cognito domain prefix (stack name plus the 12-digit account ID)",
        re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"),
        63,
        suffix="-" + "0" * _ACCOUNT_ID_WIDTH,
        lowercase=True,
        forbidden=("aws", "amazon", "cognito"),
    ),
    DerivedName(
        "Cognito resource server identifier",
        re.compile(r"[\x21\x23-\x5B\x5D-\x7E]+"),
        256,
        suffix="-mcp",
        lowercase=True,
    ),
    DerivedName(
        "Cognito machine client name", _COGNITO_NAME, 128, suffix="-machine-client"
    ),
    DerivedName(
        "IAM custom resource role name",
        _IAM_ROLE_NAME,
        64,
        suffix="-custom-resource-role",
    ),
    DerivedName(
        "IAM agent execution role name",
        _IAM_ROLE_NAME,
        64,
        suffix="-agent-execution-role",
    ),
    DerivedName(
        "IAM gateway execution role name",
        _IAM_ROLE_NAME,
        64,
        suffix="-gateway-execution-role",
    ),
    DerivedName(
        "Lambda OAuth provider function name",
        _LAMBDA_FUNCTION_NAME,
        64,
        suffix="-oauth-provider",
    ),
    DerivedName(
        "Lambda runtime health check function name",
        _LAMBDA_FUNCTION_NAME,
        64,
        suffix="-runtime-health-check",
    ),
    DerivedName(
        "AgentCore OAuth2 credential provider name",
        re.compile(r"[a-zA-Z0-9\-_]+"),
        128,
        suffix="_oauth_provider",
        lowercase=True,
        underscores=True,
    ),
    DerivedName(
        "AgentCore gateway name",
        re.compile(r"([0-9a-zA-Z][-]?){1,100}"),
        suffix="-gateway",
        lowercase=True,
    ),
    DerivedName(
        "AgentCore runtime name",
        re.compile(r"[a-zA-Z][a-zA-Z0-9_]{0,47}"),
        48,
        underscores=True,
    ),
)
# Two derived names are omitted because neither can ever bind. The Secrets
# Manager secret "{stack}/neo4j-password" has a 512-character limit (budget
# 496), and the longest CfnOutput export name adds 24 characters
# ("-GatewayExecutionRoleArn") against a 255-character quota (budget 231).
# CloudFormation caps a stack name at 128 well below both.


def binding_length_constraint() -> DerivedName:
    """The derived name with the least room, i.e. the one that caps the stack name."""
    bounded = [d for d in DERIVED_NAMES if d.max_length is not None]
    return min(bounded, key=lambda d: d.stack_name_budget())


# Computed, never written down: the tightest per-resource budget in the table.
# Currently 41, from 64 - len("-gateway-execution-role").
MAX_STACK_NAME_LEN = binding_length_constraint().stack_name_budget()

# CloudFormation takes a leading letter then letters, digits, and hyphens, and
# so do the IAM, Lambda, and Cognito names. The AgentCore gateway name is
# stricter: ([0-9a-zA-Z][-]?){1,100} permits no two hyphens in a row, so
# "{stack}-gateway" breaks on a stack name that doubles or trails a hyphen.
# Alphanumeric runs joined by single hyphens satisfy every consumer at once.
STACK_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")

# Collected from the table so a new forbidden substring only has to be declared
# on the row that forbids it.
STACK_NAME_RESERVED_WORDS: tuple[str, ...] = tuple(
    sorted({word for derived in DERIVED_NAMES for word in derived.forbidden})
)


def validate_derived_names(stack_name: str) -> None:
    """Raise ValueError if any name derived from the stack name is unusable."""
    for derived in DERIVED_NAMES:
        name = derived.render(stack_name)

        if derived.max_length is not None and len(name) > derived.max_length:
            raise ValueError(
                f"Stack name {stack_name!r} makes the {derived.resource} "
                f"{name!r}, which is {len(name)} characters against a limit of "
                f"{derived.max_length}. Shorten the stack name by "
                f"{len(name) - derived.max_length} character(s)."
            )

        if derived.pattern.fullmatch(name) is None:
            raise ValueError(
                f"Stack name {stack_name!r} makes the invalid "
                f"{derived.resource} {name!r}, which has to match "
                f"{derived.pattern.pattern!r}."
            )

        reserved = [word for word in derived.forbidden if word in name]
        if reserved:
            raise ValueError(
                f"Stack name {stack_name!r} makes the {derived.resource} "
                f"{name!r}, which may not contain {', '.join(reserved)}."
            )
