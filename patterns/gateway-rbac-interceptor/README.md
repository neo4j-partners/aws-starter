# OAuth2 Demo with RBAC and Lambda Interceptor

A comprehensive example demonstrating OAuth2 authentication with role-based access control (RBAC) using Amazon Bedrock AgentCore Gateway, Lambda Interceptor, and Amazon Cognito.

## What This Demonstrates

- **OAuth2 Authentication** - Both M2M (client_credentials) and user (password) flows
- **Role-Based Access Control** - Group-based tool access via `cognito:groups` claims
- **Lambda Interceptor** - JWT claim extraction and authorization enforcement at the Gateway
- **Header Injection** - Propagating user identity to downstream MCP tools
- **Token Caching** - Efficient token reuse with automatic refresh

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

## Quick Start

### Prerequisites

- AWS CLI configured with appropriate credentials
- [uv](https://docs.astral.sh/uv/) (manages Python and dependencies)
- Docker (for building ARM64 container image)
- Node.js 18+ and npm
- AWS CDK CLI v2.220.0+ (`npm install -g aws-cdk`)

### 1. Set Up Python Environment

```bash
uv sync   # Installs deps and the Python toolchain from uv.lock
```

### 2. Deploy the Stack

```bash
uv run cdk bootstrap  # First time only
./deploy.sh
```

Deployment takes approximately 5-7 minutes.

### 3. Create Test Users

```bash
uv run python setup_users.py
```

This creates two users that share one password generated at deploy time and
stored in Secrets Manager (read automatically from the stack's
`TestUserSecretName` output, never committed to source):
- `admin@example.com` → groups: admin, users
- `user@example.com` → groups: users

### 4. Run the Tests

```bash
# Run full test suite (creates users + tests all modes)
./test.sh

# Skip user creation if already done
./test.sh --skip-users

# Run individual tests
./test.sh --m2m      # M2M mode only
./test.sh --admin    # Admin user only
./test.sh --user     # Regular user only
```

Or run the demo manually:

```bash
# M2M mode (no groups, admin tools blocked)
uv run python client/demo.py

# User mode - as admin (full access)
uv run python client/demo.py --mode user --username admin@example.com

# User mode - as regular user (admin tools blocked)
uv run python client/demo.py --mode user --username user@example.com
```

### 5. Cleanup

```bash
./deploy.sh --destroy
```

This runs `cdk destroy` and removes the ECR repository. The Lambda log groups,
Cognito user pool, and the generated test-user secret are destroyed with the
stack. AgentCore creates its own runtime log groups under
`/aws/bedrock-agentcore/runtimes/*` that CDK does not manage; delete these
manually if you want a fully clean account:

```bash
aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/runtimes/ \
  --query 'logGroups[].logGroupName' --output text
# then: aws logs delete-log-group --log-group-name <name>
```

## Authentication Modes

| Mode | OAuth Flow | Groups | Admin Access |
|------|------------|--------|--------------|
| M2M | client_credentials | None | Blocked |
| User (admin) | USER_PASSWORD_AUTH | admin, users | Allowed |
| User (regular) | USER_PASSWORD_AUTH | users | Blocked |

## Demo Options

```bash
# M2M mode (default)
uv run python client/demo.py

# User mode with specific user
uv run python client/demo.py --mode user --username admin@example.com

# User mode (prompts for username)
uv run python client/demo.py --mode user

# Different stack or region
uv run python client/demo.py --stack MyStack --region us-east-1
```

## What Gets Deployed

| Resource | Purpose |
|----------|---------|
| Cognito User Pool | OAuth2 identity provider |
| User Pool Groups | `admin` and `users` groups for RBAC |
| Machine Client | M2M authentication (client_credentials) |
| User Client | User authentication (password flow) |
| Auth Interceptor Lambda | JWT claim extraction and RBAC enforcement |
| AgentCore Gateway | Routes requests with interceptor |
| AgentCore Runtime | Hosts MCP server with auth-aware tools |
| OAuth2 Credential Provider | Gateway to Runtime authentication |

## MCP Tools

| Tool | Access | Description |
|------|--------|-------------|
| `echo` | Public | Echo back a message |
| `get_user_info` | Public | Return caller identity from headers |
| `admin_action` | Admin only | Perform admin operation |
| `server_info` | Public | Server information |

## Cost Estimate

| Service | Monthly Cost |
|---------|--------------|
| AgentCore Runtime | ~$5-10 |
| AgentCore Gateway | ~$1-2 |
| Lambda Interceptor | ~$0.01 |
| ECR Repository | ~$0.10 |
| Cognito | ~$0.01 |
| **Total** | **~$7-13/month** |

**Tip**: Delete the stack when not in use with `./deploy.sh --destroy`.

## Documentation

- [Architecture Details](docs/ARCHITECTURE.md) - In-depth architecture, code walkthrough, lessons learned, and troubleshooting

## Next Steps

After understanding this sample, explore:

1. **Bearer Token Injection** - `01-tutorials/02-AgentCore-gateway/07-bearer-token-injection/`
2. **Agents as Tools** - `01-tutorials/02-AgentCore-gateway/12-agents-as-tools-using-mcp/` for advanced interceptor patterns
3. **Travel Concierge Blueprint** - `05-blueprints/travel-concierge-agent/` for a full production example
