# Neo4j MCP Server on AWS Bedrock AgentCore: Status & Lessons Learned

**Status: BLOCKED**
**Root Cause: Unsolvable HTTP Authorization header conflict**

---

## Executive Summary

This project attempted to deploy the official Neo4j MCP server to AWS Bedrock AgentCore. After extensive experimentation with multiple architectural approaches, we determined that **the integration is blocked by a fundamental HTTP protocol limitation**: both AgentCore and the Neo4j MCP server require the `Authorization` header for different, incompatible purposes.

HTTP only allows one `Authorization` header per request. This creates an irreconcilable conflict that cannot be solved through Gateway interceptors or custom header configurations.

---

## The Core Problem

### Two Systems, One Header

**AWS Bedrock AgentCore** requires:
```
Authorization: Bearer <jwt_token>
```
For validating client access to the MCP server.

**Neo4j MCP Server** requires:
```
Authorization: Basic <base64(username:password)>
```
For authenticating with the Neo4j database.

When a request passes through AgentCore to reach the Neo4j MCP server:
1. AgentCore consumes the JWT Bearer token for its own authentication
2. The Gateway's OAuth2 credential provider adds its own Bearer token for Runtime authentication
3. The Neo4j MCP server receives a Bearer token instead of Basic credentials
4. Database authentication fails

---

## What Was Tried

### Approach 1: Gateway REQUEST Interceptor with Header Transformation

**Theory**: Use a Lambda interceptor to read `X-Neo4j-Authorization` from the client and transform it to `Authorization` before forwarding to the Runtime.

**Implementation**:
- Created `auth_interceptor.py` Lambda with REQUEST interception
- Configured Gateway with `passRequestHeaders: true`
- Client sent both headers: `Authorization: Bearer <jwt>` and `X-Neo4j-Authorization: Basic <creds>`
- Interceptor successfully received and transformed the header

**Result**: **FAILED**

The interceptor correctly processed the transformation, but the OAuth2 credential provider configured on the Gateway Target **overwrites headers** when calling the Runtime. Custom headers from `transformedGatewayRequest` are not forwarded when OAuth credentials are involved.

### Approach 2: Metadata Configuration for Header Allowlist

**Theory**: Use `metadataConfiguration.allowedRequestHeaders` on the Gateway Target to explicitly allow custom headers through.

**Implementation**:
- Added `metadataConfiguration: { allowedRequestHeaders: ["X-Neo4j-Authorization"] }` to Gateway Target
- Configuration was accepted, target showed READY status

**Result**: **FAILED**

Despite the configuration, the custom header still did not reach the Runtime. The OAuth credential flow appears to strip non-standard headers.

While this change successfully allows AgentCore's health checks to pass, we return to the original problem: when `tools/call` is invoked, the Authorization header contains AgentCore's OAuth token, not the Neo4j Basic credentials. The header conflict remains unsolvable.

---

## Why No Solution Exists

### The Fundamental Constraint

HTTP/1.1 and HTTP/2 only allow **one Authorization header per request**. This is defined in RFC 7235 and is not a platform limitation—it's the protocol itself.

### What AWS Documentation Claims

AWS documentation states:
> "While the Authorization header cannot be configured in the target's allowlist, it will be forwarded to the target when provided by an interceptor lambda."

However, this only applies when:
1. The Gateway Target does NOT use an OAuth credential provider
2. The request flow is Client → Gateway → Interceptor → Runtime (pass-through)

When an OAuth credential provider is configured:
1. Gateway consumes the client's Authorization header for validation
2. Gateway's OAuth provider creates a NEW Authorization header for Runtime auth
3. Custom headers from interceptors are not merged into this flow

### AWS Samples Do Not Cover This Use Case

We examined all relevant samples in `amazon-bedrock-agentcore-samples`:
- Bearer token injection
- Custom header propagation
- Fine-grained access control
- Token exchange at interceptor

**None demonstrate passing custom credentials through OAuth-protected targets.** The site-reliability-agent-workshop uses JWT end-to-end with no OAuth credential provider, so header passthrough works. Our use case requires OAuth (for Gateway→Runtime auth) AND custom credentials (for Neo4j auth)—a combination that appears unsupported.

---

## Current State

### What Works

| Component | Status |
|-----------|--------|
| CDK deployment infrastructure | Working |
| Cognito OAuth2 M2M authentication | Working |
| AgentCore Runtime with custom MCP server | Working |
| AgentCore Gateway with JWT validation | Working |
| OAuth2 Credential Provider | Working |
| Gateway Target creation | Working |
| Protocol handshake (initialize, tools/list) | Working |
| Custom Python MCP server with Secrets Manager | Working (single-tenant) |

### What Does NOT Work

| Feature | Status |
|---------|--------|
| Official Neo4j MCP server on AgentCore | Blocked |
| Per-request Neo4j credentials via headers | Blocked |
| Multi-tenant Neo4j authentication | Blocked |
| Custom header propagation through OAuth targets | Blocked |

---

## Lessons Learned

### 1. Single M2M Client Architecture is Essential

Both Gateway and Runtime must use the same Cognito client in their `allowedClients` list. The OAuth2 Credential Provider must also use this same client. Any mismatch causes authentication failures with no useful error messages.

### 2. Runtime Must Be READY Before Gateway Target

AgentCore Runtime takes time to pull container images and initialize. CloudFormation considers the resource "created" immediately, but Gateway Target creation fails unless the Runtime status is READY. Always implement a wait condition.

### 3. OAuth2 Credential Provider Not in CloudFormation

There is no CloudFormation resource type for OAuth2 Credential Providers. A Lambda-backed custom resource calling the boto3 API is required.

### 4. AgentCore Gateway is Not a Transparent Proxy

The Gateway has its own authentication layer that actively participates in the request flow. It is not a simple pass-through proxy. When OAuth credential providers are configured, the Gateway:
- Consumes the client's Authorization header for its own validation
- Generates a new Authorization header for Runtime communication
- Does not merge or forward custom headers from interceptors through the OAuth flow

This fundamentally limits use cases where target services require their own authentication headers.

### 5. CDK L1 Constructs May Lag Behind API Features

The `aws-cdk-lib` (v2.233.0) did not expose `metadataConfiguration` for `CfnGatewayTarget`, despite the feature being available via CLI and direct API calls. Workarounds include:
- Post-deployment CLI commands
- Custom resources that call the API directly
- Waiting for CDK library updates

### 6. URL Encoding Runtime ARNs

Runtime invocation URLs must have the ARN properly URL-encoded (`:` → `%3A`, `/` → `%2F`). Do NOT include `?qualifier=DEFAULT` in the URL.

### 7. Gateway Interceptors Have Limitations

REQUEST interceptors work well for:
- JWT validation and claims extraction
- Request logging and auditing
- Blocking/allowing based on headers

REQUEST interceptors do NOT work for:
- Injecting Authorization headers when OAuth credential providers are used
- Propagating custom headers through OAuth authentication flows

### 8. CDK Dependencies Matter

The deployment order matters significantly:
1. ECR repository must exist before CDK runs (not just during Docker build)
2. OAuth2 Credential Provider must exist before Gateway Target
3. Runtime must be READY before Gateway Target references it
4. Cognito domain must be globally unique (include account ID)

### 9. IAM Permissions Require Both Resource Policy and Identity Policy

When Gateway invokes an interceptor Lambda:
- The Lambda needs a resource policy allowing `bedrock-agentcore.amazonaws.com`
- The Gateway role needs `lambda:InvokeFunction` permission

Both are required. Missing either causes silent failures.

---

## Recommendations

### For Single-Tenant Deployments

Use the custom Python MCP server with Secrets Manager credentials. This works reliably but:
- All requests use the same Neo4j credentials
- No per-user database isolation
- Limited feature set compared to official server

### For Multi-Tenant Requirements

Do not use AgentCore for Neo4j MCP server deployments. Instead consider:
1. **Direct Runtime access** without Gateway (loses public HTTPS endpoint)
2. **Self-hosted MCP proxy** that handles header transformation before AgentCore
3. **Alternative Neo4j access patterns** (direct driver connections, custom APIs)

### For Neo4j MCP Server Maintainers

Consider adding alternative authentication modes:
1. `auth_mode=env` - Read credentials from environment variables
2. `auth_mode=custom_header` - Read from a configurable header name (e.g., `X-Neo4j-Authorization`)
3. **Allow unauthenticated protocol handshake** - Let `initialize` and `tools/list` proceed without credentials

These changes would enable cloud deployments while maintaining backward compatibility.

---

## Technical Reference

### Key Files

| File | Purpose |
|------|---------|
| `app.py` | CDK application entry point |
| `neo4j_mcp/stack.py` | Main CDK stack definition |
| `neo4j_mcp/constructs/cognito.py` | Cognito User Pool, Domain, Resource Server |
| `neo4j_mcp/constructs/iam_roles.py` | IAM roles with least-privilege permissions |
| `neo4j_mcp/constructs/agentcore.py` | Runtime, Gateway, Target, OAuth Provider |
| `mcp-server/server.py` | Custom Python MCP server (Secrets Manager auth) |
| `client/demo.py` | OAuth2 M2M demo client |
| `deploy.sh` | Deployment script |

### Debug Commands

```bash
# Check Runtime status
aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id <RUNTIME_ID> \
  --region us-west-2

# Check Gateway configuration
aws bedrock-agentcore-control get-gateway \
  --gateway-identifier <GATEWAY_ID> \
  --region us-west-2

# Check Gateway Target with interceptors
aws bedrock-agentcore-control get-gateway-target \
  --gateway-identifier <GATEWAY_ID> \
  --target-id <TARGET_ID> \
  --region us-west-2

# View Runtime logs
aws logs tail /aws/bedrock-agentcore/runtimes/<RUNTIME_ID>-DEFAULT \
  --region us-west-2 --since 30m

# View interceptor Lambda logs
aws logs tail /aws/lambda/<STACK>-auth-interceptor \
  --region us-west-2 --since 30m
```

---

## Conclusion

Deploying the official Neo4j MCP server to AWS Bedrock AgentCore is **not currently possible** due to HTTP protocol constraints around the Authorization header. The conflict between AgentCore's OAuth authentication and Neo4j's Basic authentication cannot be resolved through available Gateway features.

The custom Python MCP server approach provides a working single-tenant solution. Multi-tenant scenarios require architectural changes either to the Neo4j MCP server itself or to the AgentCore platform.

---

*Last Updated: 2026-01-03*
