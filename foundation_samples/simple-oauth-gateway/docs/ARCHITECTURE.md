# Architecture Details

This document provides in-depth technical details about the OAuth2 Demo with RBAC and Lambda Interceptor, including architecture diagrams, code walkthrough, lessons learned, and troubleshooting guidance.

## Table of Contents

- [High-Level Flow](#high-level-flow)
- [Authentication Modes](#authentication-modes)
- [Lambda Interceptor Architecture](#lambda-interceptor-architecture)
- [Role-Based Access Control (RBAC)](#role-based-access-control-rbac)
- [Infrastructure Architecture](#infrastructure-architecture)
- [Key Authentication Components](#key-authentication-components)
- [IAM Role Permissions](#iam-role-permissions)
- [Understanding the Code](#understanding-the-code)
- [Lessons Learned and Best Practices](#lessons-learned-and-best-practices)
- [Troubleshooting](#troubleshooting)
- [Comparison with Travel Concierge Sample](#comparison-with-travel-concierge-sample)

---

## High-Level Flow

The following diagram shows the complete request flow including the Lambda interceptor:

```mermaid
flowchart LR
    subgraph Client
        A[Python Client<br/>demo.py]
    end

    subgraph AWS
        subgraph Cognito
            B[User Pool]
            C[Token Endpoint]
            G1[admin group]
            G2[users group]
        end

        subgraph AgentCore
            D[Gateway<br/>JWT Inbound Auth]
            INT[Lambda Interceptor<br/>RBAC Enforcement]
            E[OAuth Provider<br/>Outbound Auth]
            F[Runtime<br/>MCP Server]
        end
    end

    A -->|1. Auth Request| C
    C -->|2. JWT with groups| A
    A -->|3. Bearer Token| D
    D -->|4. Intercept| INT
    INT -->|5. Inject Headers| D
    D -->|6. Get OAuth Token| E
    E -->|7. Token| D
    D -->|8. Forward + Token| F
    F -->|9. MCP Response| D
    D -->|10. Response| A
```

---

## Authentication Modes

This sample supports two OAuth2 authentication flows:

### M2M Mode (client_credentials)

Machine-to-machine authentication without user context.

```mermaid
sequenceDiagram
    participant Client as Python Client
    participant Cognito as Cognito User Pool
    participant Gateway as AgentCore Gateway

    Client->>Cognito: POST /oauth2/token<br/>grant_type=client_credentials
    Cognito-->>Client: access_token (no groups)
    Client->>Gateway: MCP Request<br/>Authorization: Bearer {token}
    Note over Gateway: No cognito:groups claim<br/>Admin tools blocked
```

**Characteristics**:
- No user context (no `cognito:groups` in token)
- Good for service-to-service communication
- Admin-only tools are blocked by interceptor

### User Mode (password)

User authentication with group memberships for RBAC.

```mermaid
sequenceDiagram
    participant Client as Python Client
    participant Cognito as Cognito User Pool
    participant Gateway as AgentCore Gateway

    Client->>Cognito: InitiateAuth<br/>AuthFlow=USER_PASSWORD_AUTH
    Note over Cognito: User belongs to<br/>'admin' and 'users' groups
    Cognito-->>Client: access_token (with cognito:groups)
    Client->>Gateway: MCP Request<br/>Authorization: Bearer {token}
    Note over Gateway: Token includes cognito:groups<br/>Interceptor extracts for RBAC
```

**Characteristics**:
- Includes `cognito:groups` claim in JWT
- Enables role-based access control
- Requires SECRET_HASH calculation (see code walkthrough)

---

## Lambda Interceptor Architecture

The Lambda interceptor sits between the Gateway and Runtime, providing RBAC enforcement and header injection.

```mermaid
flowchart TB
    subgraph "Gateway Receives Request"
        A[Incoming Request<br/>with JWT]
    end

    subgraph "Lambda Interceptor"
        B[Extract JWT Claims]
        C{Admin Tool<br/>Requested?}
        D{User in<br/>Admin Group?}
        E[Inject Identity Headers]
        F[Return JSON-RPC Error]
    end

    subgraph "Runtime"
        G[MCP Server<br/>Receives Headers]
    end

    A --> B
    B --> C
    C -->|No| E
    C -->|Yes| D
    D -->|Yes| E
    D -->|No| F
    E --> G
```

### Interceptor Input/Output

**Input Event Structure** (from Gateway):
```json
{
  "mcp": {
    "gatewayRequest": {
      "headers": {
        "authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
      },
      "body": "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"params\":{\"name\":\"admin_action\"}}"
    }
  }
}
```

**Output Event Structure** (to Runtime):
```json
{
  "interceptorOutputVersion": "1.0",
  "mcp": {
    "transformedGatewayRequest": {
      "headers": {
        "authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
        "X-User-Id": "abc123-def456",
        "X-User-Groups": "admin,users",
        "X-Client-Id": "3a2b1c4d5e6f..."
      },
      "body": "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"params\":{\"name\":\"admin_action\"}}"
    }
  }
}
```

### Error Response (Access Denied)

When a non-admin user attempts to call an admin-only tool:
```json
{
  "interceptorOutputVersion": "1.0",
  "mcp": {
    "immediateGatewayResponse": {
      "statusCode": 200,
      "body": "{\"jsonrpc\":\"2.0\",\"id\":1,\"error\":{\"code\":-32600,\"message\":\"Access denied: 'admin_action' requires admin group membership\"}}"
    }
  }
}
```

---

## Role-Based Access Control (RBAC)

### Cognito User Groups

Two groups control access:

| Group | Precedence | Access Level |
|-------|------------|--------------|
| `admin` | 5 (higher priority) | Full access to all tools |
| `users` | 10 | Public tools only |

### Tool Access Matrix

| Tool | Required Group | Description |
|------|----------------|-------------|
| `echo` | Any authenticated | Echo back a message |
| `get_user_info` | Any authenticated | Return caller identity |
| `server_info` | Any authenticated | Server information |
| `admin_action` | `admin` | Perform admin operations |

### Defense in Depth

RBAC is enforced at two levels:

1. **Lambda Interceptor (Primary)**: Blocks unauthorized requests before they reach the MCP server
2. **MCP Server (Secondary)**: Additional check in `admin_action` tool as fallback

```mermaid
flowchart LR
    A[Request] --> B{Interceptor<br/>Check}
    B -->|Denied| C[JSON-RPC Error]
    B -->|Allowed| D{Server<br/>Check}
    D -->|Denied| E[Tool Error]
    D -->|Allowed| F[Success]
```

---

## Infrastructure Architecture

The following diagram shows all AWS resources created by this CDK stack:

```mermaid
graph TB
    subgraph "Local Build (deploy.sh)"
        LB[Docker buildx<br/>ARM64 image]
    end

    subgraph "CDK Stack: SimpleOAuthDemo"
        subgraph "Identity & Auth"
            UP[Cognito User Pool]
            UPD[User Pool Domain]
            RS[Resource Server<br/>simple-oauth/invoke]
            MC[Machine Client<br/>client_credentials]
            UC[User Client<br/>USER_PASSWORD_AUTH]
            UG[Users Group]
            AG[Admin Group]
            OAP[OAuth2 Credential Provider]
        end

        subgraph "Container Registry"
            ECR[ECR Repository]
        end

        subgraph "AgentCore Resources"
            GW[Gateway<br/>CUSTOM_JWT Auth]
            INT[Auth Interceptor<br/>Lambda]
            GT[Gateway Target<br/>OAuth Outbound]
            RT[Runtime<br/>MCP Server]
        end

        subgraph "IAM Roles"
            GWR[Gateway Role]
            RTR[Runtime Role]
        end
    end

    LB -->|push| ECR
    ECR --> RT

    UP --> UPD
    UP --> RS
    UP --> UG
    UP --> AG
    RS --> MC
    RS --> UC
    MC --> OAP

    GW --> INT
    INT --> GT
    GT --> RT
    GT -.->|uses| OAP

    GWR -->|assumed by| GW
    RTR -->|assumed by| RT
```

---

## Key Authentication Components

| Component | Role | Configuration |
|-----------|------|---------------|
| **Cognito User Pool** | Identity provider | Issues JWT tokens with group claims |
| **Machine Client** | M2M authentication | `client_credentials` flow |
| **User Client** | User authentication | `USER_PASSWORD_AUTH` flow with SECRET_HASH |
| **User Groups** | RBAC membership | `admin` (precedence 5), `users` (precedence 10) |
| **Auth Interceptor Lambda** | RBAC enforcement | Extracts groups, injects headers, blocks unauthorized |
| **Gateway JWT Authorizer** | Inbound auth | Validates tokens via OIDC discovery |
| **OAuth Credential Provider** | Outbound auth | Gateway to Runtime authentication |
| **Runtime JWT Authorizer** | Runtime auth | Validates Gateway's outbound tokens |

---

## IAM Role Permissions

### Gateway Role

The Gateway Role requires permissions for OAuth, Runtime invocation, **and Lambda interceptor invocation**:

```mermaid
graph LR
    subgraph "Gateway Role Permissions"
        A[InvokeRuntime]
        B[GetOAuth2CredentialProvider]
        C[GetTokenVault]
        D[GetWorkloadAccessToken]
        E[GetResourceOauth2Token]
        F[SecretsManager:GetSecretValue]
        G[Lambda:InvokeFunction]
    end

    subgraph "Resources"
        R1[runtime/*]
        R2[token-vault/*]
        R3[workload-identity-directory/*]
        R4[secrets/*]
        R5[auth-interceptor Lambda]
    end

    A --> R1
    B --> R2
    C --> R2
    D --> R3
    E --> R2
    F --> R4
    G --> R5
```

**CRITICAL**: The Gateway role MUST have `lambda:InvokeFunction` permission for the interceptor Lambda. This is in addition to the Lambda's resource-based policy. Both are required:

```python
# In Gateway Role inline policy (simple_oauth_stack.py)
iam.PolicyStatement(
    sid="InvokeLambdaInterceptor",
    effect=iam.Effect.ALLOW,
    actions=["lambda:InvokeFunction"],
    resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:{self.stack_name}-auth-interceptor"]
)
```

### Interceptor Lambda Permission (Resource-Based Policy)

The Lambda also requires a resource-based policy allowing Gateway invocation:

```python
# simple_oauth_stack.py
auth_interceptor_lambda.add_permission("GatewayInvoke",
    principal=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
    source_arn=f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:gateway/*"
)
```

**Both permissions are required**: The Gateway role needs `lambda:InvokeFunction`, AND the Lambda needs a resource-based policy allowing `bedrock-agentcore.amazonaws.com`.

---

## Understanding the Code

This section walks through the key source files with references to the actual implementation.

### Project Structure

```
simple-oauth-gateway/
├── app.py                      # CDK app entry point
├── simple_oauth_stack.py       # Main CDK stack definition
├── deploy.sh                   # Deployment script (builds image, deploys CDK)
├── setup_users.py              # Creates test users with group memberships
├── client/
│   └── demo.py                 # Demo client (M2M and user modes)
├── mcp-server/
│   └── server.py               # Auth-aware MCP server with RBAC
└── infra_utils/
    ├── auth_interceptor_lambda.py    # JWT extraction and RBAC enforcement
    ├── oauth_provider_lambda.py      # Custom resource for OAuth provider
    └── runtime_health_check_lambda.py  # Waits for runtime readiness
```

### Lambda Interceptor Implementation

The interceptor in `infra_utils/auth_interceptor_lambda.py` performs three key functions:

**1. JWT Claim Extraction** (`auth_interceptor_lambda.py:45-66`):
```python
def _decode_jwt_claims(token: str) -> dict:
    """Decode JWT payload without verification (Gateway already validated)."""
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    # Add padding for base64url decoding
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    decoded = base64.urlsafe_b64decode(payload)
    return json.loads(decoded)
```

**2. RBAC Enforcement** (`auth_interceptor_lambda.py:89-102`):
```python
# Check if requesting admin tool without admin group
if tool_name in ADMIN_TOOLS and "admin" not in groups:
    return _error_response(
        rpc_id=rpc_id,
        message=f"Access denied: '{tool_name}' requires admin group membership"
    )
```

**3. Header Injection** (`auth_interceptor_lambda.py:104-118`):
```python
return {
    "interceptorOutputVersion": "1.0",
    "mcp": {
        "transformedGatewayRequest": {
            "headers": {
                **headers,
                "X-User-Id": user_id,
                "X-User-Groups": ",".join(groups),
                "X-Client-Id": client_id,
            },
            "body": body,
        }
    }
}
```

### User Authentication with SECRET_HASH

The demo client in `client/demo.py:162-246` implements user password authentication:

```python
# client/demo.py:205-212 - SECRET_HASH calculation
message = username + client_id
dig = hmac.new(
    client_secret.encode("utf-8"),
    message.encode("utf-8"),
    hashlib.sha256
).digest()
secret_hash = base64.b64encode(dig).decode()

# client/demo.py:215-224 - Authentication
auth_response = cognito.initiate_auth(
    ClientId=client_id,
    AuthFlow="USER_PASSWORD_AUTH",
    AuthParameters={
        "USERNAME": username,
        "PASSWORD": password,
        "SECRET_HASH": secret_hash
    }
)
```

### Auth-Aware MCP Server

The server in `mcp-server/server.py` reads identity headers:

**Header Extraction** (`server.py:45-72`):
```python
def _get_user_context() -> dict:
    headers = _request_headers.get()
    user_id = headers.get("x-user-id", "unknown")
    groups_str = headers.get("x-user-groups", "")
    groups = [g.strip() for g in groups_str.split(",") if g.strip()]
    return {
        "user_id": user_id,
        "groups": groups,
        "authenticated": user_id != "unknown"
    }
```

**Admin Tool with Defense-in-Depth** (`server.py:134-173`):
```python
@mcp.tool()
def admin_action(action: str) -> dict:
    ctx = _get_user_context()
    # Secondary check (interceptor should have blocked non-admins)
    if ctx["authenticated"] and "admin" not in ctx["groups"]:
        return {
            "success": False,
            "error": "Unauthorized: admin group membership required"
        }
    return {
        "success": True,
        "action": action,
        "performed_by": ctx["user_id"]
    }
```

### CDK Stack Updates for RBAC

**Cognito User Groups** (`simple_oauth_stack.py:118-133`):
```python
users_group = cognito.CfnUserPoolGroup(self, "UsersGroup",
    user_pool_id=user_pool.user_pool_id,
    group_name="users",
    description="Standard users with basic access",
    precedence=10
)
admin_group = cognito.CfnUserPoolGroup(self, "AdminGroup",
    user_pool_id=user_pool.user_pool_id,
    group_name="admin",
    description="Administrators with full access",
    precedence=5
)
```

**Interceptor Configuration** (`simple_oauth_stack.py:428-446`):
```python
interceptor_configurations=[
    bedrockagentcore.CfnGateway.GatewayInterceptorConfigurationProperty(
        interception_points=["REQUEST"],
        interceptor=bedrockagentcore.CfnGateway.InterceptorConfigurationProperty(
            lambda_=bedrockagentcore.CfnGateway.LambdaInterceptorConfigurationProperty(
                arn=auth_interceptor_lambda.function_arn,
            ),
        ),
        input_configuration=bedrockagentcore.CfnGateway.InterceptorInputConfigurationProperty(
            pass_request_headers=True,
        ),
    )
]
```

### Test User Setup

The `setup_users.py` script creates users with group memberships:

```python
# setup_users.py:29-42 - User definitions
TEST_USERS = [
    {
        "username": "admin@example.com",
        "password": "AdminPass123!",
        "groups": ["admin", "users"],
    },
    {
        "username": "user@example.com",
        "password": "UserPass123!",
        "groups": ["users"],
    }
]
```

---

## Lessons Learned and Best Practices

### Mistake 1: M2M Tokens Don't Have Groups

**Symptom**: RBAC not working in M2M mode - all requests treated the same.

**Root Cause**: The `client_credentials` flow (M2M) has no user context, so the JWT never includes `cognito:groups`.

**Solution**: Add user password authentication for RBAC scenarios. Use M2M only for service-to-service communication where RBAC isn't needed.

**Best Practice**: Design your auth strategy based on RBAC requirements upfront. If you need group-based access control, implement user authentication.

### Mistake 2: Missing IAM Permissions for Lambda Interceptor (ROOT CAUSE OF 500 ERRORS)

**Symptom**: Gateway returns 500 "An internal error occurred" without invoking the Lambda interceptor. CloudWatch logs show no Lambda invocations.

**Root Cause**: **Two separate permissions are required** for Gateway to invoke the Lambda interceptor:

1. **Lambda Resource-Based Policy** - Allows the Gateway service to invoke the Lambda
2. **Gateway IAM Role Policy** - Allows the Gateway role to invoke the Lambda

Most documentation only shows the resource-based policy, but the Gateway role also needs `lambda:InvokeFunction` permission!

**Solution**: Add BOTH permissions:

```python
# 1. Lambda resource-based policy (allows Gateway service principal)
auth_interceptor_lambda.add_permission("GatewayInvoke",
    principal=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
    source_arn=f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:gateway/*"
)

# 2. Gateway role inline policy (allows role to invoke Lambda)
iam.PolicyStatement(
    sid="InvokeLambdaInterceptor",
    effect=iam.Effect.ALLOW,
    actions=["lambda:InvokeFunction"],
    resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:{self.stack_name}-auth-interceptor"]
)
```

**Debugging Steps**:
1. Check Lambda CloudWatch logs - if empty, Lambda isn't being invoked
2. Verify Lambda resource-based policy: `aws lambda get-policy --function-name <name>`
3. Verify Gateway role has `lambda:InvokeFunction`: `aws iam get-role-policy --role-name <gateway-role> --policy-name <policy>`

**Best Practice**: When using Lambda interceptors with AgentCore Gateway, always configure BOTH the Lambda's resource-based policy AND the Gateway role's invoke permission.

### Mistake 3: SECRET_HASH Required for User Password Auth

**Symptom**: `initiate_auth` call fails with "Unable to verify secret hash for client".

**Root Cause**: Cognito clients with secrets require a SECRET_HASH when using USER_PASSWORD_AUTH.

**Solution**: Calculate HMAC-SHA256 of (username + client_id) with client_secret:
```python
message = username + client_id
dig = hmac.new(client_secret.encode(), message.encode(), hashlib.sha256).digest()
secret_hash = base64.b64encode(dig).decode()
```

**Best Practice**: When using Cognito clients with secrets for user auth flows, always include SECRET_HASH.

### Mistake 4: JWT Decoding Without Verification

**Symptom**: Concern about JWT security in interceptor.

**Clarification**: The interceptor only decodes the JWT payload - it does NOT verify the signature. This is intentional because the Gateway has already validated the JWT via OIDC discovery before invoking the interceptor.

**Best Practice**: Trust the Gateway's validation. The interceptor's role is claim extraction and RBAC enforcement, not token verification.

### Mistake 5: Interceptor Event Structure

**Symptom**: Interceptor returns malformed response; requests fail.

**Root Cause**: The event structure for Gateway interceptors is specific and documented.

**Solution**: Use the correct structure (see `auth_interceptor_lambda.py:104-118`):
```python
return {
    "interceptorOutputVersion": "1.0",
    "mcp": {
        "transformedGatewayRequest": {
            "headers": {...},
            "body": body
        }
    }
}
```

**Best Practice**: Follow the exact event structure. For errors, use `immediateGatewayResponse` with a JSON-RPC error body.

### Mistake 6: Missing Gateway Role Permissions for OAuth Outbound

**Symptom**: Tool listing worked, but tool invocation returned "An internal error occurred."

**Root Cause**: The Gateway Role was missing permissions required to retrieve OAuth tokens from the credential provider.

**Solution**: Add these permissions to the Gateway Role (see `simple_oauth_stack.py:201-216`):

- `bedrock-agentcore:GetOAuth2CredentialProvider`
- `bedrock-agentcore:GetTokenVault` (CRITICAL - often missed)
- `bedrock-agentcore:GetWorkloadAccessToken` (CRITICAL - often missed)
- `bedrock-agentcore:GetResourceOauth2Token`
- `secretsmanager:GetSecretValue`

**Best Practice**: When using OAuth outbound authentication, always include `GetTokenVault` and `GetWorkloadAccessToken` permissions.

### Development Checklist

Before deploying an AgentCore Gateway with OAuth and RBAC:

- [ ] Gateway Role includes `GetTokenVault` and `GetWorkloadAccessToken` permissions
- [ ] Lambda interceptor has Gateway invoke permission
- [ ] Cognito groups created with appropriate precedence
- [ ] User client configured with `USER_PASSWORD_AUTH` flow
- [ ] Client code implements SECRET_HASH for user authentication
- [ ] Interceptor returns correct event structure with version "1.0"
- [ ] MCP server reads injected headers correctly
- [ ] Defense-in-depth: server also checks groups (backup for interceptor)

---

## Troubleshooting

### Token Request Fails

**Check that**:
- The User Pool Domain is correctly configured
- The client has the appropriate flow enabled (`client_credentials` or `USER_PASSWORD_AUTH`)
- The scope matches the resource server scope (`simple-oauth/invoke`)
- For user auth: SECRET_HASH is correctly calculated

### Gateway Returns 401

**Verify**:
- The token is not expired
- The client ID is in the gateway's `allowedClients` list
- The OIDC discovery URL is correct and accessible
- The token was issued by the expected User Pool

### Interceptor Not Invoked

**Check**:
- Lambda has Gateway invoke permission (resource-based policy)
- `interceptor_configurations` is set on the Gateway
- `interception_points` includes "REQUEST"
- `pass_request_headers` is True in input configuration

### Admin Tool Blocked When It Shouldn't Be

**Verify**:
- User is a member of the `admin` group in Cognito
- Token was obtained with user password auth (not M2M)
- Decode the JWT to confirm `cognito:groups` contains "admin"

### Admin Tool Not Blocked

**Check**:
- Tool name matches exactly (case-sensitive) in `ADMIN_TOOLS` set
- Interceptor is correctly parsing the JSON-RPC body
- Lambda logs for the interceptor in CloudWatch

### Tool Invocation Returns "Internal Error"

This usually indicates Gateway to Runtime authentication failure:
- Verify Gateway Role has `GetTokenVault` and `GetWorkloadAccessToken` permissions
- Check that the OAuth Credential Provider was created successfully
- Ensure the Runtime's JWT authorizer accepts the machine client
- Check CloudWatch logs for the Gateway, Interceptor Lambda, and Runtime

### Headers Not Received by MCP Server

**Check**:
- Interceptor is returning `transformedGatewayRequest` with injected headers
- Header names are correct (X-User-Id, X-User-Groups, X-Client-Id)
- Server is reading headers correctly (lowercase in HTTP headers)

### Docker Build Fails

If the local Docker build fails:
- Ensure Docker Desktop is running: `docker info`
- Check you have enough disk space for the image build
- Try cleaning up old buildx builders: `docker buildx prune`
- For ARM64 emulation issues, reinstall QEMU: `docker run --rm --privileged tonistiigi/binfmt --install arm64`

---

## Comparison with Travel Concierge Sample

This sample is a simplified version of the OAuth2 flow used in `05-blueprints/travel-concierge-agent`. Here's what was removed to focus on RBAC and interceptors:

| Feature | This Sample | Travel Concierge |
|---------|-------------|------------------|
| OAuth2 M2M | Yes | Yes |
| User Password Auth | Yes | No |
| Cognito Groups | Yes | No |
| Lambda Interceptor | Yes | Yes |
| RBAC Enforcement | Yes | No |
| Amplify Backend | No | Yes |
| DynamoDB | No | Yes |
| Web UI | No | Yes |
| Multiple MCP Servers | No | Yes |
| Subagents | No | Yes |
| Memory | No | Yes |

This sample focuses specifically on demonstrating:
- OAuth2 authentication with both M2M and user flows
- Lambda interceptor for JWT claim extraction
- Role-based access control using Cognito groups
- Header injection for identity propagation
- Defense-in-depth authorization patterns
