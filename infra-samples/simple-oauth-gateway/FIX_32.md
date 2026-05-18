# FIX_32: Lambda Interceptor 500 Errors — Root Cause and Resolution

## Status: RESOLVED

The `simple-oauth-gateway` sample implements OAuth2 authentication with RBAC
using Cognito groups and a Lambda REQUEST interceptor. The Gateway was returning
500 errors without invoking the interceptor Lambda.

**Root cause**: the Gateway IAM role was missing `lambda:InvokeFunction` for the
interceptor Lambda. The Lambda's resource-based policy allowing the
`bedrock-agentcore.amazonaws.com` service principal is necessary but not
sufficient on its own; the Gateway role also needs an identity-based grant to
invoke the function.

**Fix**: both permissions are now granted in `simple_oauth_stack.py`:

```python
# Identity policy on the Gateway role
auth_interceptor_lambda.grant_invoke(gateway_role)

# Resource-based policy for the Gateway service principal
auth_interceptor_lambda.add_permission(
    "GatewayInvokePermission",
    principal=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
    action="lambda:InvokeFunction",
    source_arn=f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:gateway/*"
)
```

All three authentication modes work correctly:

- M2M mode: `admin_action` blocked (no groups)
- Admin user: full access including `admin_action`
- Regular user: `admin_action` blocked (not in admin group)

---

## Verified During Investigation

| Area | Finding |
|------|---------|
| CDK property names | Correct. `cdk synth` emits the documented `InterceptorConfigurations` / `InterceptionPoints` / `Interceptor.Lambda.Arn` shape. |
| Interceptor config schema | Correct. Synthesized CloudFormation matches the SDK structure. |
| Gateway operational status | The operational state is `READY`, not `ACTIVE`. `deploy.sh` waits for `READY`. |
| Lambda handler | `handler` function name matches the CDK configuration. |
| Event structure | Interceptor events carry `mcp.gatewayRequest`; there is no `requestContext` field. The code reads identity from the JWT in the request headers. |

---

## Documentation References

- [Using interceptors with Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors.html)
- [Types of interceptors](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors-types.html)
- [Configuration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors-configuration.html)
- [Fine-grained access control](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-fine-grained-access-control.html)
- [AWS Blog: Apply fine-grained access control with interceptors](https://aws.amazon.com/blogs/machine-learning/apply-fine-grained-access-control-with-bedrock-agentcore-gateway-interceptors/)

---

## Files Involved

| File | Purpose |
|------|---------|
| `simple_oauth_stack.py` | CDK stack with Gateway and interceptor configuration |
| `infra_utils/auth_interceptor_lambda.py` | Lambda interceptor code |
| `mcp-server/server.py` | MCP server with auth-aware tools |
| `client/demo.py` | Test client with M2M and user auth modes |
| `setup_users.py` | Creates test users in Cognito |

---

## Success Criteria (met)

1. Gateway invokes the interceptor Lambda on every request
2. Interceptor logs show JWT claims extraction
3. Admin tools blocked for non-admin users
4. Admin tools allowed for admin users
5. Identity headers (`X-User-Id`, `X-User-Groups`, `X-Client-Id`) propagated to the MCP server
6. All three test modes pass: M2M (admin blocked), admin user (full access), regular user (admin blocked)
