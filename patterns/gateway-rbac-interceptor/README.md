# Gateway RBAC with a Lambda Interceptor

This pattern adds role-based access control to an Amazon Bedrock AgentCore
Gateway. Amazon Cognito issues the tokens, and a Lambda interceptor checks
each tool call.

## Overview

- **OAuth2 authentication:** Clients log in two ways. Machines use the client credentials flow. Users use the password flow.
- **Role-based access control:** Cognito groups decide which tools a caller can use. The groups arrive in the `cognito:groups` token claim.
- **Lambda interceptor:** A Lambda runs on every Gateway request. It reads the token claims and blocks admin tools for callers outside the `admin` group.
- **Header injection:** The interceptor adds `X-User-Id`, `X-User-Groups`, and `X-Client-Id` headers. The MCP tools read these headers to know who is calling.
- **Token caching:** The demo client reuses its token. It gets a new token 10 minutes before the old one expires.

## Quick start

Run these commands from `patterns/gateway-rbac-interceptor/`:

```bash
uv sync
uv run cdk bootstrap          # first time only
./deploy.sh                   # takes about 5 to 7 minutes
uv run python setup_users.py  # create the test users
./test.sh                     # run all tests
./deploy.sh --destroy         # delete everything when done
```

## Prerequisites

- **AWS CLI:** Configure it with credentials for your account.
- **uv:** [uv](https://docs.astral.sh/uv/) installs Python and the project dependencies.
- **Docker:** Docker builds the ARM64 container image.
- **Node.js:** Install Node.js 18 or later with npm.
- **AWS CDK CLI:** Install version 2.220.0 or later with `npm install -g aws-cdk`.

## Step 1: Set up the Python environment

```bash
uv sync   # installs the dependencies and Python toolchain from uv.lock
```

## Step 2: Deploy the stack

```bash
uv run cdk bootstrap  # first time only
./deploy.sh
```

Deployment takes about 5 to 7 minutes. `deploy.sh` accepts these flags:

- **`--region REGION`:** This flag sets the AWS region. The default is `us-east-1`.
- **`--skip-build`:** This flag skips the Docker build and reuses the existing image.
- **`--destroy`:** This flag deletes the stack instead of deploying it.
- **`--help`:** This flag prints the usage message.

## Step 3: Create the test users

```bash
uv run python setup_users.py
```

This script creates two users:

- **`admin@example.com`:** This user belongs to the `admin` and `users` groups.
- **`user@example.com`:** This user belongs to the `users` group only.

Both users share one password. The stack generates it at deploy time and stores
it in Secrets Manager. The script finds the secret through the stack's
`TestUserSecretName` output. The password is never committed to source.

## Step 4: Run the tests

```bash
./test.sh               # create users and test all modes
./test.sh --skip-users  # skip user creation
./test.sh --m2m         # M2M mode only
./test.sh --admin       # admin user only
./test.sh --user        # regular user only
./test.sh --region us-east-1  # target a region (default: us-east-1)
```

You can also run the demo client by hand:

```bash
# M2M mode: no groups, so admin tools are blocked
uv run python client/demo.py

# User mode as admin: full access
uv run python client/demo.py --mode user --username admin@example.com

# User mode as a regular user: admin tools are blocked
uv run python client/demo.py --mode user --username user@example.com
```

## Step 5: Clean up

```bash
./deploy.sh --destroy
```

This command runs `cdk destroy` and deletes the ECR repository. The stack
deletion also removes the Lambda log groups, the Cognito user pool, and the
test-user secret.

AgentCore creates its own runtime log groups under
`/aws/bedrock-agentcore/runtimes/*`. CDK does not manage them. Delete them by
hand for a fully clean account:

```bash
aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/runtimes/ \
  --query 'logGroups[].logGroupName' --output text
# then: aws logs delete-log-group --log-group-name <name>
```

## Architecture

```
                                         AWS Cloud
    ┌──────────┐        ┌─────────────────────────────────────────────────────────┐
    │          │        │                                                         │
    │  Python  │        │  ┌─────────────────┐                                    │
    │  Client  │───────────▶  Cognito User   │ ← Users in groups (admin/users)   │
    │          │   1    │  │     Pool        │                                    │
    │ demo.py  │◀──────────│ (Token Issuer)  │                                    │
    │          │   2    │  └─────────────────┘                                    │
    │          │        │           │ JWT with cognito:groups                     │
    │          │        │           ▼                                             │
    │          │        │  ┌─────────────────┐                                    │
    │          │───────────▶    AgentCore    │                                    │
    │          │   3    │  │    Gateway      │                                    │
    │          │        │  │ (JWT Inbound)   │                                    │
    │          │        │  └────────┬────────┘                                    │
    │          │        │           │                                             │
    │          │        │           ▼ REQUEST Interceptor                         │
    │          │        │  ┌─────────────────┐                                    │
    │          │        │  │ Auth Interceptor│ ← Extracts groups from JWT        │
    │          │        │  │    Lambda       │ ← Injects X-User-Id, X-User-Groups│
    │          │        │  │                 │ ← Blocks admin tools if not admin │
    │          │        │  └────────┬────────┘                                    │
    │          │        │           │                                             │
    │          │        │           ▼                                             │
    │          │        │  ┌─────────────────┐                                    │
    │          │◀───────────│  MCP Server    │ ← Auth-aware tools                │
    │          │   4    │  │ (echo, admin,   │ ← Reads identity headers          │
    │          │        │  │  get_user_info) │                                    │
    └──────────┘        │  └─────────────────┘                                    │
                        │                                                         │
                        └─────────────────────────────────────────────────────────┘

    Flow:
    1. Client authenticates (M2M or user password)
    2. Cognito returns JWT (user tokens include cognito:groups)
    3. Client calls Gateway with Bearer token
    4. Interceptor extracts groups, injects headers, enforces RBAC
    5. MCP Server receives request with identity headers
    6. Response returned to client
```

## Authentication modes

| Mode | OAuth flow | Groups | Admin access |
|------|------------|--------|--------------|
| M2M | client_credentials | None | Blocked |
| User (admin) | USER_PASSWORD_AUTH | admin, users | Allowed |
| User (regular) | USER_PASSWORD_AUTH | users | Blocked |

## Demo options

```bash
# M2M mode (default)
uv run python client/demo.py

# User mode with a specific user
uv run python client/demo.py --mode user --username admin@example.com

# User mode, prompts for the username
uv run python client/demo.py --mode user

# A different stack or region
uv run python client/demo.py --stack MyStack --region us-east-1
```

`client/demo.py` accepts these flags:

- **`--stack`:** This flag sets the CloudFormation stack name. The default is `SimpleOAuthDemo`.
- **`--region`:** This flag sets the AWS region. The default comes from your AWS config.
- **`--mode`:** This flag picks `m2m` or `user`. The default is `m2m`.
- **`--username`:** This flag sets the user to log in as in user mode.
- **`--password`:** This flag sets the test user password. By default, the client reads it from Secrets Manager.
- **`--scope`:** This flag sets the OAuth scope.

## What gets deployed

| Resource | Purpose |
|----------|---------|
| Cognito User Pool | OAuth2 identity provider |
| User Pool Groups | `admin` and `users` groups for RBAC |
| Machine Client | M2M authentication (client_credentials) |
| User Client | User authentication (password flow) |
| Auth Interceptor Lambda | Reads JWT claims and enforces RBAC |
| AgentCore Gateway | Routes requests through the interceptor |
| AgentCore Runtime | Hosts the MCP server with auth-aware tools |
| OAuth2 Credential Provider | Authenticates the Gateway to the Runtime |

## MCP tools

| Tool | Access | Description |
|------|--------|-------------|
| `echo` | Public | Echoes back a message |
| `get_user_info` | Public | Returns the caller identity from the headers |
| `admin_action` | Admin only | Performs an admin operation |
| `server_info` | Public | Returns server information |

## Cost estimate

| Service | Monthly cost |
|---------|--------------|
| AgentCore Runtime | ~$5-10 |
| AgentCore Gateway | ~$1-2 |
| Lambda Interceptor | ~$0.01 |
| ECR Repository | ~$0.10 |
| Cognito | ~$0.01 |
| **Total** | **~$7-13/month** |

**Tip:** Delete the stack when you are not using it. Run `./deploy.sh --destroy`.

## Documentation

- [`patterns/gateway-rbac-interceptor/docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): This page covers the architecture in depth, with a code walkthrough and lessons learned.
- [`patterns/gateway-rbac-interceptor/docs/troubleshooting.md`](docs/troubleshooting.md): This page lists common problems and fixes.

## Next steps

The [AgentCore samples repo](https://github.com/awslabs/amazon-bedrock-agentcore-samples)
has related examples:

- **Bearer token injection:** See `01-tutorials/02-AgentCore-gateway/07-bearer-token-injection/`.
- **Agents as tools:** See `01-tutorials/02-AgentCore-gateway/12-agents-as-tools-using-mcp/` for more interceptor patterns.
- **Travel Concierge blueprint:** See `05-blueprints/travel-concierge-agent/` for a full production example.
