# Architecture Details

This pattern puts role-based access control in front of an MCP server on AgentCore Runtime. Cognito issues the tokens. The AgentCore Gateway validates each JWT and calls a Lambda interceptor. The interceptor reads the caller's Cognito groups, blocks admin-only tools for non-admins, and adds identity headers. The MCP server reads those headers and checks the admin group a second time.

## Table of Contents

- [Request Flow](#request-flow)
- [Authentication Modes](#authentication-modes)
- [Lambda Interceptor](#lambda-interceptor)
- [Role-Based Access Control](#role-based-access-control)
- [Infrastructure](#infrastructure)
- [IAM Permissions](#iam-permissions)
- [Understanding the Code](#understanding-the-code)
- [Lessons Learned](#lessons-learned)
- [Troubleshooting](#troubleshooting)
- [Comparison with the Travel Concierge Sample](#comparison-with-the-travel-concierge-sample)

## Diagrams

| Diagram | What it shows |
|---------|---------------|
| [request-flow.svg](images/request-flow.svg) | The ten steps from token request to tool result |
| [m2m-auth.svg](images/m2m-auth.svg) | The client_credentials flow and why admin tools are denied |
| [user-auth.svg](images/user-auth.svg) | The USER_PASSWORD_AUTH flow that puts groups in the token |
| [interceptor-decision.svg](images/interceptor-decision.svg) | How the interceptor allows or denies a request |
| [defense-in-depth.svg](images/defense-in-depth.svg) | The Gateway check and the server check on admin_action |
| [infrastructure.svg](images/infrastructure.svg) | Every resource deploy.sh and the CDK stack create |
| [gateway-role-permissions.svg](images/gateway-role-permissions.svg) | The Gateway role statements and the interceptor resource policy |

---

## Request Flow

![Request flow from token request to tool result](images/request-flow.svg)

- **Inbound auth:** The Gateway uses a `CUSTOM_JWT` authorizer. It validates the token through the Cognito OIDC discovery URL and accepts both the machine client and the user client.
- **Interceptor:** The Gateway calls the interceptor on every request at the `REQUEST` interception point. The interceptor either rewrites the request or returns a response that ends the call.
- **Outbound auth:** The Gateway target gets a Runtime token from the OAuth2 credential provider. The provider uses the machine client with the `simple-oauth/invoke` scope.
- **Runtime auth:** The Runtime has its own JWT authorizer. It accepts tokens from both Cognito clients through the same discovery URL.

---

## Authentication Modes

The demo client supports two OAuth2 flows. Only the user flow produces a token with groups.

### M2M Mode (client_credentials)

![M2M authentication flow](images/m2m-auth.svg)

- **No user context:** A `client_credentials` token has no `cognito:groups` claim.
- **Identity:** The interceptor sets the user ID to `m2m:{client_id}` and the groups to an empty list.
- **Access:** The interceptor denies every admin-only tool for an M2M token.
- **Use case:** M2M fits service-to-service calls that do not need group-based access.

### User Mode (USER_PASSWORD_AUTH)

![User authentication flow](images/user-auth.svg)

- **Groups claim:** The access token includes `cognito:groups`, so the interceptor can apply RBAC.
- **Identity:** The interceptor uses the token's `sub` claim as the user ID.
- **SECRET_HASH:** The user client has a secret, so every `InitiateAuth` call must include a SECRET_HASH. The [code walkthrough](#user-authentication-with-secret_hash) shows the calculation.

---

## Lambda Interceptor

The interceptor runs between the Gateway's JWT check and the call to the Runtime. It enforces RBAC and injects identity headers.

![Interceptor decision flow](images/interceptor-decision.svg)

### Input Event

The Gateway sends the request headers and body under `mcp.gatewayRequest`. The body can arrive as a string, and the interceptor parses it as JSON.

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

### Allow Response

An allowed request goes back to the Gateway as a `transformedGatewayRequest`. The interceptor sets `Authorization`, `Content-Type`, and three identity headers. It returns the body as a parsed JSON object.

```json
{
  "interceptorOutputVersion": "1.0",
  "mcp": {
    "transformedGatewayRequest": {
      "headers": {
        "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
        "Content-Type": "application/json",
        "X-User-Id": "abc123-def456",
        "X-User-Groups": "admin,users",
        "X-Client-Id": "3a2b1c4d5e6f..."
      },
      "body": {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": { "name": "admin_action" }
      }
    }
  }
}
```

### Deny Response

A denied request ends at the Gateway as a `transformedGatewayResponse`. The Runtime never sees it. MCP surfaces the denial as a successful JSON-RPC result whose `result.isError` is `true`. The message prints the caller's groups as a Python list.

```json
{
  "interceptorOutputVersion": "1.0",
  "mcp": {
    "transformedGatewayResponse": {
      "statusCode": 200,
      "headers": { "Content-Type": "application/json" },
      "body": {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
          "isError": true,
          "content": [{ "type": "text", "text": "Access denied: Tool 'admin_action' requires 'admin' group. Your groups: ['users']" }]
        }
      }
    }
  }
}
```

For an M2M token the message ends with `Your groups: none`. The interceptor also returns a deny response when the body is invalid JSON or when any step raises an exception.

---

## Role-Based Access Control

### Cognito User Groups

| Group | Precedence | Description in the stack | Access |
|-------|------------|--------------------------|--------|
| `admin` | 5 | Administrators with full tool access | Every tool |
| `users` | 10 | Regular users with basic tool access | Every tool except `admin_action` |

A lower precedence number wins when a user belongs to more than one group.

### Tool Access Matrix

| Tool | Required group | Description |
|------|----------------|-------------|
| `echo` | Any authenticated caller | Echoes a message back |
| `get_user_info` | Any authenticated caller | Returns the caller identity and auth type |
| `server_info` | Any authenticated caller | Returns server information |
| `admin_action` | `admin` | Performs an admin operation |

The interceptor's `ADMIN_TOOLS` set holds only `admin_action`.

### Defense in Depth

![Defense in depth for admin_action](images/defense-in-depth.svg)

- **Interceptor check:** The interceptor blocks a non-admin call to `admin_action` before it reaches the MCP server. The client gets a result with `isError` set to `true`.
- **Server check:** The `admin_action` tool checks the `X-User-Groups` header again. A non-admin caller gets a normal tool result with `success: false`.
- **Missing headers:** The server check runs only when `X-User-Id` is present. A direct Runtime call without the Gateway carries no identity headers, so the server check passes.

---

## Infrastructure

![Infrastructure created by deploy.sh and the CDK stack](images/infrastructure.svg)

`deploy.sh` builds the arm64 image and creates the ECR repository with the AWS CLI. The repository name is `{stack}-mcp-server` in lowercase. The CDK stack only looks the repository up, so it is not a stack resource. `./deploy.sh --destroy` deletes it after the stack.

| Group | Resources in the SimpleOAuthDemo stack |
|-------|----------------------------------------|
| AgentCore | Gateway with a `CUSTOM_JWT` authorizer and the interceptor, Gateway target `mcp-server-target`, and Runtime `{stack}_mcp_server` |
| Cognito | User pool with domain, resource server `simple-oauth` with scope `invoke`, MachineClient, UserClient, and the `admin` and `users` groups |
| Lambda | AuthInterceptorLambda, OAuthProviderLambda, and RuntimeHealthCheckLambda on Python 3.13, each with a one-week log group |
| Custom resources | OAuthProvider creates the OAuth2 credential provider `{stack}_oauth_provider`. RuntimeHealthCheck waits for the Runtime before the Gateway target is created |
| IAM | GatewayRole, RuntimeRole, and CustomResourceRole |
| Secrets Manager | TestUserPassword, a generated 20-character password for the test users |

### Key Authentication Components

| Component | Role | Configuration |
|-----------|------|---------------|
| **Cognito user pool** | Identity provider | Issues JWTs with group claims |
| **MachineClient** | M2M authentication | `client_credentials` grant with scope `simple-oauth/invoke` |
| **UserClient** | User authentication | `USER_PASSWORD_AUTH` with SECRET_HASH. Access tokens last 60 minutes |
| **User groups** | RBAC membership | `admin` with precedence 5 and `users` with precedence 10 |
| **AuthInterceptorLambda** | RBAC enforcement | Extracts groups, injects headers, and blocks admin tools |
| **Gateway JWT authorizer** | Inbound auth | Validates tokens through OIDC discovery |
| **OAuth2 credential provider** | Outbound auth | Gets the Gateway a token for the Runtime |
| **Runtime JWT authorizer** | Runtime auth | Validates the Gateway's outbound token |

---

## IAM Permissions

### Gateway Role

![Gateway role statements and the interceptor resource policy](images/gateway-role-permissions.svg)

The GatewayRole inline policy has four statements. Each statement grants all of its actions on all of its resources.

| Statement | Actions | Resources |
|-----------|---------|-----------|
| `InvokeRuntime` | `InvokeRuntime`, `InvokeRuntimeWithResponseStream` | `runtime/*` |
| `CloudWatchLogs` | `CreateLogGroup`, `CreateLogStream`, `PutLogEvents` | `log-group:/aws/bedrock-agentcore/*` |
| `OAuthProviderAccess` | `GetOAuth2CredentialProvider`, `GetTokenVault`, `GetWorkloadAccessToken`, `GetResourceOauth2Token`, `secretsmanager:GetSecretValue` | `token-vault/*`, `workload-identity-directory/*`, `secret:bedrock-agentcore*` |
| `BedrockModelAccess` | `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream` | `foundation-model/*`, `inference-profile/*` |

Only the AgentCore service can assume the role. The trust policy adds `aws:SourceAccount` and `aws:SourceArn` conditions.

The role also needs `lambda:InvokeFunction` on the interceptor. The stack grants it with the CDK construct, so the resource follows the function reference instead of a hand-built ARN (`simple_oauth_stack.py:438`):

```python
# Identity policy on the Gateway role to invoke the interceptor
auth_interceptor_lambda.grant_invoke(gateway_role)
```

### Interceptor Resource Policy

The Lambda also needs a resource-based policy that lets the AgentCore service principal invoke it (`simple_oauth_stack.py:444-449`). The `gateway/*` source ARN avoids a circular dependency on the Gateway.

```python
auth_interceptor_lambda.add_permission(
    "GatewayInvokePermission",
    principal=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
    action="lambda:InvokeFunction",
    source_arn=f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:gateway/*"
)
```

**Both grants are required:** The Gateway role needs `lambda:InvokeFunction`, and the Lambda needs a resource-based policy for `bedrock-agentcore.amazonaws.com`.

---

## Understanding the Code

### Project Structure

```
gateway-rbac-interceptor/
├── app.py                      # CDK app entry point
├── simple_oauth_stack.py       # Main CDK stack definition
├── deploy.sh                   # Builds and pushes the image, deploys the stack
├── setup_users.py              # Creates test users with group memberships
├── test.sh                     # End-to-end tests for M2M, admin, and user modes
├── client/
│   └── demo.py                 # Demo client for M2M and user modes
├── mcp-server/
│   ├── Dockerfile              # arm64 image, runs as a non-root user on port 8000
│   └── server.py               # Auth-aware MCP server with RBAC
├── infra_utils/
│   ├── auth_interceptor_lambda.py      # JWT extraction and RBAC enforcement
│   ├── oauth_provider_lambda.py        # Custom resource for the OAuth provider
│   └── runtime_health_check_lambda.py  # Waits for Runtime readiness
└── docs/
    ├── ARCHITECTURE.md         # This document
    ├── troubleshooting.md      # Root cause of the interceptor 500 errors
    └── images/                 # SVG diagrams
```

### Lambda Interceptor Implementation

The interceptor in `infra_utils/auth_interceptor_lambda.py` does three things.

**1. JWT claim extraction** (`auth_interceptor_lambda.py:102-123`):
```python
def _decode_jwt(auth_header: str) -> dict[str, Any] | None:
    """Decode JWT payload without verification (Gateway already validated)."""
    token = auth_header.replace("Bearer ", "").strip()
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    # Add padding for base64url decoding
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    decoded = base64.urlsafe_b64decode(payload)
    return json.loads(decoded)
```

**2. RBAC enforcement** (`auth_interceptor_lambda.py:61-72`):
```python
if method == "tools/call":
    tool_name = body.get("params", {}).get("name", "")
    # Remove target prefix (e.g., "mcp-server-target___admin_action")
    base_tool_name = tool_name.split("___")[-1]

    if base_tool_name in ADMIN_TOOLS and "admin" not in groups:
        return _deny_request(
            rpc_id,
            f"Access denied: Tool '{base_tool_name}' requires 'admin' group. "
            f"Your groups: {groups or 'none'}"
        )
```

**3. Header injection** (`auth_interceptor_lambda.py:126-148`):
```python
def _allow_request(auth_header, body, user_id, groups, client_id) -> dict[str, Any]:
    return {
        "interceptorOutputVersion": INTERCEPTOR_VERSION,
        "mcp": {
            "transformedGatewayRequest": {
                "headers": {
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                    "X-User-Id": user_id,
                    "X-User-Groups": ",".join(groups),
                    "X-Client-Id": client_id,
                },
                "body": body,
            }
        },
    }
```

### User Authentication with SECRET_HASH

The demo client in `client/demo.py` reads the user client secret with `describe_user_pool_client`. It then computes the SECRET_HASH and calls `initiate_auth`.

```python
# client/demo.py:193-195 - SECRET_HASH calculation
message = username + client_id
dig = hmac.new(client_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
secret_hash = base64.b64encode(dig).decode()

# client/demo.py:199-203 - Authentication
auth_response = cognito.initiate_auth(
    ClientId=client_id,
    AuthFlow="USER_PASSWORD_AUTH",
    AuthParameters={"USERNAME": username, "PASSWORD": password, "SECRET_HASH": secret_hash},
)
```

### Auth-Aware MCP Server

The server in `mcp-server/server.py` reads the identity headers the interceptor injected.

**Header capture:** MCP tools run outside the HTTP request scope. `IdentityHeaderMiddleware` (`server.py:52-65`) copies each request's headers into a `ContextVar`. The `__main__` block installs it on the streamable HTTP app before it starts uvicorn:

```python
app = mcp.streamable_http_app(stateless_http=True, host=HOST)
app.add_middleware(IdentityHeaderMiddleware)
uvicorn.run(app, host=HOST, port=PORT)
```

Without the middleware the tools never see the headers, and the server check never runs.

**Header extraction** (`server.py:68-95`):
```python
def _get_user_context() -> dict:
    headers = _request_headers.get({})
    user_id = headers.get("x-user-id", "unknown")
    groups_str = headers.get("x-user-groups", "")
    client_id = headers.get("x-client-id", "unknown")
    groups = [g.strip() for g in groups_str.split(",") if g.strip()]
    return {
        "user_id": user_id,
        "groups": groups,
        "client_id": client_id,
        "authenticated": user_id != "unknown",
    }
```

**Admin tool with defense in depth** (`server.py:157-200`):
```python
@mcp.tool()
def admin_action(action: str) -> dict:
    ctx = _get_user_context()
    # Defense-in-depth: the Gateway interceptor should have already
    # blocked non-admins
    if ctx["authenticated"] and "admin" not in ctx["groups"]:
        return {
            "success": False,
            "error": "Unauthorized: admin group membership required",
            "user": ctx["user_id"],
            "groups": ctx["groups"]
        }
    return {
        "success": True,
        "action": action,
        "performed_by": ctx["user_id"],
        "user_groups": ctx["groups"],
        "message": f"Admin action '{action}' completed successfully"
    }
```

### CDK Stack for RBAC

**Cognito user groups** (`simple_oauth_stack.py:149-162`):
```python
users_group = cognito.CfnUserPoolGroup(self, "UsersGroup",
    user_pool_id=user_pool.user_pool_id,
    group_name="users",
    description="Regular users with basic tool access",
    precedence=10  # Higher number = lower precedence
)
admin_group = cognito.CfnUserPoolGroup(self, "AdminGroup",
    user_pool_id=user_pool.user_pool_id,
    group_name="admin",
    description="Administrators with full tool access",
    precedence=5  # Lower number = higher precedence
)
```

**Interceptor configuration** (`simple_oauth_stack.py:529-541`):
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

`setup_users.py` creates two users and adds them to their groups:

```python
# setup_users.py - User definitions (no password in source)
TEST_USERS = [
    {
        "username": "admin@example.com",
        "groups": ["admin", "users"],
    },
    {
        "username": "user@example.com",
        "groups": ["users"],
    }
]
```

- **Password:** The CDK stack generates the shared password at deploy time and stores it in the `TestUserPassword` secret. No credential is committed to source.
- **Readers:** `setup_users.py`, `client/demo.py`, and `test.sh` find the secret through the stack's `TestUserSecretName` output.
- **Creation:** The script creates each user with the welcome message suppressed and sets the password as permanent.

---

## Lessons Learned

### Mistake 1: M2M Tokens Have No Groups

- **Symptom:** RBAC did nothing in M2M mode. Every request was treated the same.
- **Root cause:** The `client_credentials` flow has no user, so the JWT never includes `cognito:groups`.
- **Solution:** Use user password authentication when you need RBAC. Keep M2M for service-to-service calls that do not need groups.
- **Best practice:** Decide on the auth flow from your RBAC needs before you build. Group-based access requires user authentication.

### Mistake 2: Missing IAM Permissions for the Lambda Interceptor

This mistake was the root cause of the 500 errors. See [troubleshooting.md](troubleshooting.md) for the full investigation.

- **Symptom:** The Gateway returned 500 "An internal error occurred" and never invoked the interceptor. The Lambda's CloudWatch logs were empty.
- **Root cause:** The Gateway needs two separate permissions to invoke the interceptor. The Lambda resource-based policy lets the AgentCore service invoke the function. The Gateway role identity policy lets the role invoke it. Most examples show only the resource-based policy.
- **Solution:** Grant both permissions.

```python
# 1. Gateway role identity policy (allows role to invoke Lambda)
auth_interceptor_lambda.grant_invoke(gateway_role)

# 2. Lambda resource-based policy (allows Gateway service principal)
auth_interceptor_lambda.add_permission(
    "GatewayInvokePermission",
    principal=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
    action="lambda:InvokeFunction",
    source_arn=f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:gateway/*"
)
```

**Debugging steps:**
1. Check the Lambda's CloudWatch logs. Empty logs mean the Gateway never invoked it.
2. Verify the resource-based policy with `aws lambda get-policy --function-name <name>`.
3. Verify the Gateway role has `lambda:InvokeFunction` with `aws iam get-role-policy --role-name <gateway-role> --policy-name <policy>`.

- **Best practice:** Configure both the Lambda resource-based policy and the Gateway role grant whenever you add a Lambda interceptor.

### Mistake 3: SECRET_HASH Required for User Password Auth

- **Symptom:** `initiate_auth` failed with "Unable to verify secret hash for client".
- **Root cause:** A Cognito client with a secret requires a SECRET_HASH for `USER_PASSWORD_AUTH`.
- **Solution:** Compute an HMAC-SHA256 of username plus client ID, keyed with the client secret.

```python
message = username + client_id
dig = hmac.new(client_secret.encode(), message.encode(), hashlib.sha256).digest()
secret_hash = base64.b64encode(dig).decode()
```

- **Best practice:** Always send SECRET_HASH when a user auth flow uses a client with a secret.

### Mistake 4: JWT Decoding Without Verification

- **Concern:** The interceptor decodes the JWT payload without checking the signature.
- **Clarification:** This is intentional. The Gateway validates the JWT through OIDC discovery before it invokes the interceptor.
- **Best practice:** Trust the Gateway's validation. The interceptor's job is claim extraction and RBAC, not token verification.

### Mistake 5: Interceptor Event Structure

- **Symptom:** The interceptor returned a malformed response, and requests failed.
- **Root cause:** The Gateway expects a specific interceptor output structure.
- **Solution:** Return the documented structure (`auth_interceptor_lambda.py:126-148`).

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

- **Best practice:** Follow the exact structure. To deny, return a `transformedGatewayResponse` whose body is a JSON-RPC result with `isError: true`.

### Mistake 6: Missing Gateway Role Permissions for OAuth Outbound

- **Symptom:** Tool listing worked, but tool calls returned "An internal error occurred."
- **Root cause:** The Gateway role could not fetch OAuth tokens from the credential provider.
- **Solution:** Add the `OAuthProviderAccess` statement to the Gateway role (`simple_oauth_stack.py:297-314`). It grants these actions:
  - `bedrock-agentcore:GetOAuth2CredentialProvider`
  - `bedrock-agentcore:GetTokenVault`
  - `bedrock-agentcore:GetWorkloadAccessToken`
  - `bedrock-agentcore:GetResourceOauth2Token`
  - `secretsmanager:GetSecretValue`
- **Best practice:** Always include `GetTokenVault` and `GetWorkloadAccessToken` for OAuth outbound auth. These two are the ones most often missed.

### Development Checklist

Check these before you deploy an AgentCore Gateway with OAuth and RBAC:

- [ ] The Gateway role includes `GetTokenVault` and `GetWorkloadAccessToken`
- [ ] The Gateway role has `lambda:InvokeFunction` on the interceptor through `grant_invoke`
- [ ] The interceptor has a resource-based policy for `bedrock-agentcore.amazonaws.com`
- [ ] The Cognito groups exist with the right precedence
- [ ] The user client allows the `USER_PASSWORD_AUTH` flow
- [ ] The client code sends SECRET_HASH for user authentication
- [ ] The interceptor returns the correct event structure with version "1.0"
- [ ] The MCP server installs `IdentityHeaderMiddleware` and reads the injected headers
- [ ] The server also checks groups as a backup for the interceptor

---

## Troubleshooting

### Token Request Fails

- **Domain:** Check that the user pool domain is configured.
- **Flow:** Check that the client allows the flow you use, either `client_credentials` or `USER_PASSWORD_AUTH`.
- **Scope:** Check that the scope matches the resource server scope `simple-oauth/invoke`.
- **SECRET_HASH:** For user auth, check that the SECRET_HASH is computed correctly.

### Gateway Returns 401

- **Expiry:** Check that the token has not expired.
- **Allowed clients:** Check that the client ID is in the Gateway's `allowedClients` list.
- **Discovery URL:** Check that the OIDC discovery URL is correct and reachable.
- **Issuer:** Check that the expected user pool issued the token.

### Interceptor Not Invoked

- **Role grant:** Check that the Gateway role has `lambda:InvokeFunction` on the interceptor. A missing role grant was the root cause of the 500 errors.
- **Resource policy:** Check that the Lambda allows `bedrock-agentcore.amazonaws.com` to invoke it.
- **Configuration:** Check that `interceptor_configurations` is set on the Gateway.
- **Interception point:** Check that `interception_points` includes "REQUEST".
- **Headers:** Check that `pass_request_headers` is `True` in the input configuration.

### Admin Tool Blocked When It Should Be Allowed

- **Membership:** Check that the user belongs to the `admin` group in Cognito.
- **Flow:** Check that the token came from user password auth and not from M2M.
- **Claim:** Decode the JWT and confirm `cognito:groups` contains "admin".

### Admin Tool Not Blocked

- **Tool name:** Check that the tool name matches an entry in `ADMIN_TOOLS` exactly. The match is case-sensitive.
- **Body parsing:** Check that the interceptor parses the JSON-RPC body.
- **Logs:** Read the interceptor's CloudWatch logs.

### Tool Invocation Returns "Internal Error"

This error usually means the Gateway could not authenticate to the Runtime.

- **Role permissions:** Check that the Gateway role has `GetTokenVault` and `GetWorkloadAccessToken`.
- **Credential provider:** Check that the OAuth2 credential provider was created.
- **Runtime authorizer:** Check that the Runtime's JWT authorizer accepts the machine client.
- **Logs:** Read the CloudWatch logs for the Gateway, the interceptor, and the Runtime.

### Headers Not Received by the MCP Server

- **Interceptor output:** Check that the interceptor returns `transformedGatewayRequest` with the identity headers.
- **Header names:** Check the names `X-User-Id`, `X-User-Groups`, and `X-Client-Id`.
- **Middleware:** Check that `IdentityHeaderMiddleware` is installed on the app. Without it the tools see only the default values.
- **Case:** Read the headers in lowercase, because HTTP header names arrive lowercased.

### Docker Build Fails

- **Docker:** Make sure Docker Desktop is running with `docker info`.
- **Disk:** Make sure there is enough disk space for the image build.
- **Builders:** Clean up old buildx state with `docker buildx prune`.
- **Emulation:** For ARM64 emulation issues, reinstall QEMU with `docker run --rm --privileged tonistiigi/binfmt --install arm64`.

---

## Comparison with the Travel Concierge Sample

This sample simplifies the OAuth2 flow from `05-blueprints/travel-concierge-agent`. It drops several features to focus on RBAC and interceptors.

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

This sample demonstrates five things:

- **Authentication:** It shows OAuth2 with both the M2M flow and the user flow.
- **Claim extraction:** A Lambda interceptor reads the JWT claims.
- **RBAC:** Cognito groups control access to tools.
- **Identity propagation:** The interceptor injects identity headers for the MCP server.
- **Defense in depth:** The Gateway and the MCP server both check the admin group.
