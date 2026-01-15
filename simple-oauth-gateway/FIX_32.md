# FIX_32: Lambda Interceptor Implementation Analysis and Fix Plan

## Executive Summary

The simple-oauth-gateway sample implements OAuth2 authentication with RBAC using Cognito groups and a Lambda REQUEST interceptor. The Gateway was returning 500 errors without invoking the interceptor Lambda.

**ROOT CAUSE IDENTIFIED AND FIXED**: The Gateway IAM role was missing `lambda:InvokeFunction` permission. Even though the Lambda had a resource-based policy allowing the Gateway service principal, the Gateway role also needs explicit permission to invoke Lambda functions.

**STATUS: RESOLVED** - All three authentication modes now work correctly:
- M2M mode: admin_action blocked (no groups)
- Admin user: full access including admin_action
- Regular user: admin_action blocked (not in admin group)

---

## Current Implementation Status

### What Has Been Implemented

| Component | Status | Notes |
|-----------|--------|-------|
| Cognito User Pool | Working | Creates users, groups, tokens |
| Machine Client (M2M) | Working | client_credentials flow works |
| User Client (Password Auth) | Working | USER_PASSWORD_AUTH with SECRET_HASH works |
| Cognito Groups (admin, users) | Working | Groups assigned to test users |
| OAuth2 Credential Provider | Working | Custom resource creates provider |
| AgentCore Runtime | Working | MCP server starts, responds to health checks |
| AgentCore Gateway | Partially Working | JWT validation works, but interceptor not invoked |
| Auth Interceptor Lambda | Not Invoked | Lambda code works when tested directly |
| GatewayTarget | Unknown | May have configuration issues |

### Test Results (After Fix)

- **Direct Lambda invocation**: SUCCESS - Returns correct transformed request
- **Cognito token acquisition**: SUCCESS - M2M and user tokens work
- **Gateway with token**: SUCCESS - Requests processed correctly
- **Interceptor invocation**: SUCCESS - Lambda logs show invocations
- **M2M mode**: SUCCESS - Admin tools blocked (no user groups)
- **Admin user**: SUCCESS - Full access to all tools
- **Regular user**: SUCCESS - Admin tools blocked (only 'users' group)

---

## Identified Issues

### Issue 1: CDK Property Names - VERIFIED CORRECT

**Status**: VERIFIED - CDK generates correct CloudFormation.

**Synthesized CloudFormation** (verified via `cdk synth`):
```yaml
InterceptorConfigurations:
  - InputConfiguration:
      PassRequestHeaders: true
    InterceptionPoints:
      - REQUEST
    Interceptor:
      Lambda:
        Arn: !GetAtt AuthInterceptorLambda0A975A8C.Arn
```

This matches the AWS documentation exactly. The CDK property names are correct.

### Issue 2: Interceptor Configuration Schema - VERIFIED CORRECT

**Status**: VERIFIED - CDK output matches SDK structure.

The synthesized CloudFormation matches the expected structure from the SDK. This is not the issue.

### Issue 3: Gateway Status is "READY" not "ACTIVE"

**Status**: FIXED

**Finding**: The Gateway operational status is "READY", not "ACTIVE" as initially assumed. Updated deploy.sh to check for "READY" status when waiting for Gateway to be operational.

### Issue 4: Gateway May Need Explicit Update After Creation

**Observation**: The reference samples often create the Gateway first, then update it with interceptor configuration. Our CDK stack tries to create the Gateway with interceptor configuration inline.

**From reference samples**:
1. Create Gateway without interceptor
2. Deploy interceptor Lambda
3. Update Gateway with interceptor configuration

**Our approach**:
1. Create Lambda (dependency)
2. Create Gateway with interceptor configuration inline

This may cause a dependency or timing issue.

### Issue 4: Missing Request ID Context

**Observation**: Our interceptor extracts `requestContext.requestId` but the Gateway event structure shows no `requestContext` field.

**Current Code**:
```python
request_id = event.get("requestContext", {}).get("requestId", "unknown")
```

**Actual Event Structure** (from AWS docs):
```json
{
  "interceptorInputVersion": "1.0",
  "mcp": {
    "gatewayRequest": { ... }
  }
}
```

The `requestContext` field does not exist in interceptor events. This is a minor issue but indicates a misunderstanding of the event structure.

### Issue 5: Lambda Handler Function Name

**Observation**: Lambda is deployed with handler `auth_interceptor_lambda.handler`.

**Verification Needed**: Ensure the handler function is named `handler` (it is) and matches the CDK configuration.

### Issue 6: Gateway Role Permissions - ROOT CAUSE

**Status**: FIXED

**Gateway Role** needs permissions for:
- `bedrock-agentcore:InvokeRuntime`
- `bedrock-agentcore:GetOAuth2CredentialProvider`
- `bedrock-agentcore:GetTokenVault`
- `bedrock-agentcore:GetWorkloadAccessToken`
- `bedrock-agentcore:GetResourceOauth2Token`
- `secretsmanager:GetSecretValue`

**CRITICAL: Also needed for interceptors**:
- `lambda:InvokeFunction` - The Gateway role MUST have permission to invoke the interceptor Lambda!

The Lambda's resource-based policy (allowing bedrock-agentcore.amazonaws.com) is NOT sufficient alone. The Gateway's IAM role also needs `lambda:InvokeFunction` permission.

**Fix applied in `simple_oauth_stack.py`**:
```python
iam.PolicyStatement(
    sid="InvokeLambdaInterceptor",
    effect=iam.Effect.ALLOW,
    actions=["lambda:InvokeFunction"],
    resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:{self.stack_name}-auth-interceptor"]
)
```

---

## Reference Implementation Analysis

### Working Sample: 12-agents-as-tools-using-mcp

**Key Differences from Our Implementation**:

1. **Deployment Order**:
   - Sample: Creates Gateway, then updates with interceptor
   - Ours: Creates Gateway with interceptor inline

2. **Interceptor Configuration Method**:
   - Sample: Uses `update_mcp_gateway` SDK call
   - Ours: Uses CDK `CfnGateway` with inline properties

3. **Lambda Deployment**:
   - Sample: Deploys Lambda with boto3, adds permission manually
   - Ours: Uses CDK Lambda construct with permission

4. **Testing Approach**:
   - Sample: Tests Gateway without interceptor first
   - Ours: Deploys complete stack without intermediate testing

### Event/Response Structure (from AWS Documentation)

**INPUT to Interceptor**:
```json
{
  "interceptorInputVersion": "1.0",
  "mcp": {
    "rawGatewayRequest": {
      "body": "<raw_request_body>"
    },
    "gatewayRequest": {
      "path": "/mcp",
      "httpMethod": "POST",
      "headers": {
        "Authorization": "Bearer <token>",
        "Content-Type": "application/json"
      },
      "body": {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list"
      }
    }
  }
}
```

**OUTPUT from Interceptor (Allow)**:
```json
{
  "interceptorOutputVersion": "1.0",
  "mcp": {
    "transformedGatewayRequest": {
      "headers": { ... },
      "body": { ... }
    }
  }
}
```

**OUTPUT from Interceptor (Deny)**:
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
          "content": [{ "type": "text", "text": "Access denied" }]
        }
      }
    }
  }
}
```

---

## Fix Plan

### Step 1: Test Without Interceptor First

**Goal**: Confirm Gateway can forward requests to Runtime without interceptor.

**Changes Required**:

1. Modify `simple_oauth_stack.py` to remove `interceptor_configurations` from the Gateway
2. Deploy the stack
3. Run `python client/demo.py` to verify MCP calls work end-to-end
4. Confirm Runtime logs show incoming requests

**Success Criteria**:
- `tools/list` returns available tools
- `tools/call` with `echo` tool returns response
- No 500 errors from Gateway

### Step 2: Update Deploy Script to Add Interceptor After Gateway is Ready

**Goal**: Modify `deploy.sh` to deploy Gateway first, wait for it to be ready, then add interceptor via AWS CLI.

**Changes Required**:

1. Remove `interceptor_configurations` from CDK Gateway definition (keep it commented out)
2. Keep the Auth Interceptor Lambda in CDK (it still gets deployed)
3. Add post-deployment step to `deploy.sh` that:
   - Waits for Gateway to be in ACTIVE state
   - Calls `aws bedrock-agentcore-control update-gateway` to add the interceptor

**Deploy Script Addition**:

```bash
# After CDK deploy completes...

echo "==> Adding interceptor to Gateway..."

# Get Gateway ID and Lambda ARN from stack outputs
GATEWAY_ID=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --region $REGION \
  --query 'Stacks[0].Outputs[?OutputKey==`GatewayId`].OutputValue' \
  --output text)

LAMBDA_ARN=$(aws lambda get-function \
  --function-name ${STACK_NAME}-auth-interceptor \
  --region $REGION \
  --query 'Configuration.FunctionArn' \
  --output text)

# Wait for Gateway to be ready
echo "  Waiting for Gateway to be ACTIVE..."
while true; do
  STATUS=$(aws bedrock-agentcore-control get-gateway \
    --gateway-identifier $GATEWAY_ID \
    --region $REGION \
    --query 'status' \
    --output text 2>/dev/null || echo "PENDING")

  if [ "$STATUS" = "ACTIVE" ]; then
    echo "  Gateway is ACTIVE"
    break
  fi
  echo "  Gateway status: $STATUS, waiting..."
  sleep 5
done

# Add interceptor configuration
echo "  Adding interceptor configuration..."
aws bedrock-agentcore-control update-gateway \
  --gateway-identifier $GATEWAY_ID \
  --region $REGION \
  --interceptor-configurations "[{
    \"interceptor\": {
      \"lambda\": {
        \"arn\": \"$LAMBDA_ARN\"
      }
    },
    \"interceptionPoints\": [\"REQUEST\"],
    \"inputConfiguration\": {
      \"passRequestHeaders\": true
    }
  }]"

echo "  Interceptor added successfully!"
```

**Why This Approach**:
- Reference samples (12-agents-as-tools-using-mcp) use this two-step approach
- Gateway may need to be fully initialized before accepting interceptor configuration
- Separates concerns: CDK handles infrastructure, CLI handles runtime configuration

---

## Key Finding: CDK Configuration is Correct

After running `cdk synth`, the generated CloudFormation is correct. The issue is NOT with CDK property names, interceptor configuration structure, or Lambda ARN references.

**Root Cause**: The Gateway likely needs to be fully initialized before interceptor configuration is applied. Reference samples use a two-step approach: deploy Gateway first, then add interceptor via `update-gateway` API call.

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

## Success Criteria

1. Gateway invokes interceptor Lambda on every request
2. Interceptor logs show JWT claims extraction
3. Admin tools blocked for non-admin users
4. Admin tools allowed for admin users
5. Identity headers (X-User-Id, X-User-Groups) propagated to MCP server
6. All three test modes work:
   - M2M: admin tools blocked
   - Admin user: full access
   - Regular user: admin tools blocked
