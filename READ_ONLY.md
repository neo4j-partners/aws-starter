# IAM Permissions Guide: Deployment, Read-Only Access, and Agent Sandbox

This document describes how to separate IAM permissions for three personas when working with the Neo4j MCP Server (`neo4j-agentcore-mcp-server/`) and AgentCore Agents (`agentcore-neo4j-mcp-agent/`):

1. **Deployer** -- Full permissions to build, deploy, and manage all infrastructure
2. **Viewer (Read-Only)** -- Can inspect deployed resources but cannot modify or invoke them
3. **Agent Sandbox Tester** -- Can invoke deployed agents and gateways for testing, but cannot modify infrastructure

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [What Gets Deployed](#what-gets-deployed)
- [1. Deployer Permissions](#1-deployer-permissions)
  - [MCP Server Stack Deployment](#mcp-server-stack-deployment)
  - [Agent Runtime Deployment](#agent-runtime-deployment)
  - [Deployer IAM Policy](#deployer-iam-policy)
- [2. Read-Only Viewer Permissions](#2-read-only-viewer-permissions)
  - [What Viewers Can See](#what-viewers-can-see)
  - [Viewer IAM Policy](#viewer-iam-policy)
  - [Viewer Restrictions](#viewer-restrictions)
- [3. Agent Sandbox Tester Permissions](#3-agent-sandbox-tester-permissions)
  - [What Testers Can Do](#what-testers-can-do)
  - [Sandbox Tester IAM Policy](#sandbox-tester-iam-policy)
  - [Sandbox Guardrails](#sandbox-guardrails)
- [Cross-Account Access Pattern](#cross-account-access-pattern)
- [Implementation Guide](#implementation-guide)
- [AWS Documentation References](#aws-documentation-references)

---

## Architecture Overview

```
Deployer Account (or Role)
  |
  +-- Deploys CDK Stack (MCP Server)
  |     +-- Cognito User Pool + OAuth2 Client
  |     +-- ECR Repository + Docker Image
  |     +-- AgentCore Runtime (MCP Server container)
  |     +-- AgentCore Gateway + Target
  |     +-- IAM Roles (Execution, Gateway, Custom Resource)
  |     +-- Lambda Functions (OAuth Provider, Health Check)
  |
  +-- Deploys CloudFormation Stack (Agent)
        +-- ECR Repository + Docker Image
        +-- AgentCore Runtime (Agent container)
        +-- IAM Execution Role

Viewer (Read-Only)
  |
  +-- Can describe/list all above resources
  +-- Can view CloudWatch logs and metrics
  +-- Cannot modify, delete, or invoke anything

Sandbox Tester
  |
  +-- Can invoke Gateway (MCP tools via JWT)
  +-- Can invoke Agent Runtime (direct API)
  +-- Can view logs from their invocations
  +-- Cannot modify infrastructure
```

---

## What Gets Deployed

### MCP Server Stack (`neo4j-agentcore-mcp-server/`)

| AWS Resource | Type | Purpose |
|---|---|---|
| Cognito User Pool | `AWS::Cognito::UserPool` | OAuth2 token issuer |
| Cognito Domain | `AWS::Cognito::UserPoolDomain` | Token endpoint |
| Resource Server | `AWS::Cognito::UserPoolResourceServer` | Custom OAuth scopes |
| Machine Client | `AWS::Cognito::UserPoolClient` | M2M credentials (client_id + secret) |
| ECR Repository | `AWS::ECR::Repository` | Container image storage |
| Custom Resource Role | `AWS::IAM::Role` | Lambda execution for custom resources |
| Agent Execution Role | `AWS::IAM::Role` | Runtime container permissions |
| Gateway Execution Role | `AWS::IAM::Role` | Gateway service permissions |
| OAuth Provider Lambda | `AWS::Lambda::Function` | Creates OAuth2 credential provider |
| Health Check Lambda | `AWS::Lambda::Function` | Waits for runtime readiness |
| MCP Runtime | `AWS::BedrockAgentCore::Runtime` | Neo4j MCP server container |
| Gateway | `AWS::BedrockAgentCore::Gateway` | JWT-authenticated MCP endpoint |
| Gateway Target | `AWS::BedrockAgentCore::GatewayTarget` | Routes gateway to runtime |

### Agent Stack (`agentcore-neo4j-mcp-agent/`)

| AWS Resource | Type | Purpose |
|---|---|---|
| ECR Repository | `AWS::ECR::Repository` | Agent container image |
| Agent Execution Role | `AWS::IAM::Role` | Runtime permissions (Bedrock, ECR, logs) |
| AgentCore Runtime | `AWS::BedrockAgentCore::Runtime` | Agent container (basic or orchestrator) |

---

## 1. Deployer Permissions

The deployer needs full CRUD access to create, update, and tear down the entire stack.

### MCP Server Stack Deployment

The CDK stack (`neo4j-agentcore-mcp-server/cdk/neo4j_mcp_stack.py`) requires permissions across these services:

1. **CloudFormation** -- Create/update/delete stacks
2. **IAM** -- Create roles, attach policies, pass roles to AgentCore
3. **Cognito** -- Create user pools, clients, domains, resource servers
4. **ECR** -- Create repositories, push images
5. **Lambda** -- Create functions for custom resources
6. **Bedrock AgentCore** -- Create runtimes, gateways, targets, OAuth providers
7. **Secrets Manager** -- Create/manage secrets for OAuth credential providers
8. **CloudWatch Logs** -- Create log groups for runtimes
9. **CDK Bootstrap** -- S3 bucket + ECR for CDK assets

### Agent Runtime Deployment

The CloudFormation template (`agentcore-neo4j-mcp-agent/cfn/agent-runtime.yaml`) requires:

1. **CloudFormation** -- Create/update/delete stacks
2. **IAM** -- Create execution role with `CAPABILITY_NAMED_IAM`
3. **ECR** -- Create repository, push ARM64 images
4. **Bedrock AgentCore** -- Create runtime
5. **STS** -- Get caller identity for account ID

### Deployer IAM Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AgentCoreFull",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:CreateAgentRuntime",
        "bedrock-agentcore:UpdateAgentRuntime",
        "bedrock-agentcore:DeleteAgentRuntime",
        "bedrock-agentcore:GetAgentRuntime",
        "bedrock-agentcore:ListAgentRuntimes",
        "bedrock-agentcore:CreateAgentRuntimeEndpoint",
        "bedrock-agentcore:UpdateAgentRuntimeEndpoint",
        "bedrock-agentcore:DeleteAgentRuntimeEndpoint",
        "bedrock-agentcore:GetAgentRuntimeEndpoint",
        "bedrock-agentcore:ListAgentRuntimeEndpoints",
        "bedrock-agentcore:CreateGateway",
        "bedrock-agentcore:UpdateGateway",
        "bedrock-agentcore:DeleteGateway",
        "bedrock-agentcore:GetGateway",
        "bedrock-agentcore:ListGateways",
        "bedrock-agentcore:CreateGatewayTarget",
        "bedrock-agentcore:UpdateGatewayTarget",
        "bedrock-agentcore:DeleteGatewayTarget",
        "bedrock-agentcore:GetGatewayTarget",
        "bedrock-agentcore:ListGatewayTargets",
        "bedrock-agentcore:CreateOauth2CredentialProvider",
        "bedrock-agentcore:DeleteOauth2CredentialProvider",
        "bedrock-agentcore:GetOauth2CredentialProvider",
        "bedrock-agentcore:ListOauth2CredentialProviders",
        "bedrock-agentcore:CreateTokenVault",
        "bedrock-agentcore:GetTokenVault",
        "bedrock-agentcore:PutResourcePolicy",
        "bedrock-agentcore:DeleteResourcePolicy",
        "bedrock-agentcore:GetResourcePolicy",
        "bedrock-agentcore:ListTagsForResource",
        "bedrock-agentcore:TagResource",
        "bedrock-agentcore:UntagResource",
        "bedrock-agentcore:InvokeAgentRuntime",
        "bedrock-agentcore:InvokeGateway"
      ],
      "Resource": "arn:aws:bedrock-agentcore:*:*:*"
    },
    {
      "Sid": "IAMRoleManagement",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies",
        "iam:ListRoleTags",
        "iam:UpdateAssumeRolePolicy"
      ],
      "Resource": [
        "arn:aws:iam::*:role/*BedrockAgentCore*",
        "arn:aws:iam::*:role/*neo4j*",
        "arn:aws:iam::*:role/*agentcore*"
      ]
    },
    {
      "Sid": "IAMPassRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::*:role/*BedrockAgentCore*",
        "arn:aws:iam::*:role/*neo4j*",
        "arn:aws:iam::*:role/*agentcore*"
      ],
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": [
            "bedrock-agentcore.amazonaws.com",
            "lambda.amazonaws.com"
          ]
        }
      }
    },
    {
      "Sid": "IAMServiceLinkedRoles",
      "Effect": "Allow",
      "Action": "iam:CreateServiceLinkedRole",
      "Resource": "arn:aws:iam::*:role/aws-service-role/bedrock-agentcore.amazonaws.com/*"
    },
    {
      "Sid": "CognitoFull",
      "Effect": "Allow",
      "Action": [
        "cognito-idp:CreateUserPool",
        "cognito-idp:DeleteUserPool",
        "cognito-idp:UpdateUserPool",
        "cognito-idp:DescribeUserPool",
        "cognito-idp:ListUserPools",
        "cognito-idp:CreateUserPoolClient",
        "cognito-idp:DeleteUserPoolClient",
        "cognito-idp:UpdateUserPoolClient",
        "cognito-idp:DescribeUserPoolClient",
        "cognito-idp:ListUserPoolClients",
        "cognito-idp:CreateUserPoolDomain",
        "cognito-idp:DeleteUserPoolDomain",
        "cognito-idp:DescribeUserPoolDomain",
        "cognito-idp:CreateResourceServer",
        "cognito-idp:DeleteResourceServer",
        "cognito-idp:UpdateResourceServer",
        "cognito-idp:DescribeResourceServer",
        "cognito-idp:ListResourceServers",
        "cognito-idp:TagResource",
        "cognito-idp:UntagResource",
        "cognito-idp:ListTagsForResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ECRFull",
      "Effect": "Allow",
      "Action": [
        "ecr:CreateRepository",
        "ecr:DeleteRepository",
        "ecr:DescribeRepositories",
        "ecr:DescribeImages",
        "ecr:ListImages",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:GetAuthorizationToken",
        "ecr:SetRepositoryPolicy",
        "ecr:GetRepositoryPolicy",
        "ecr:DeleteRepositoryPolicy",
        "ecr:TagResource",
        "ecr:PutImageScanningConfiguration"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LambdaForCustomResources",
      "Effect": "Allow",
      "Action": [
        "lambda:CreateFunction",
        "lambda:DeleteFunction",
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration",
        "lambda:GetFunction",
        "lambda:InvokeFunction",
        "lambda:AddPermission",
        "lambda:RemovePermission",
        "lambda:TagResource"
      ],
      "Resource": "arn:aws:lambda:*:*:function:*neo4j*"
    },
    {
      "Sid": "CloudFormation",
      "Effect": "Allow",
      "Action": [
        "cloudformation:CreateStack",
        "cloudformation:UpdateStack",
        "cloudformation:DeleteStack",
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "cloudformation:DescribeStackResources",
        "cloudformation:GetTemplate",
        "cloudformation:GetTemplateSummary",
        "cloudformation:ListStacks",
        "cloudformation:ListStackResources",
        "cloudformation:CreateChangeSet",
        "cloudformation:ExecuteChangeSet",
        "cloudformation:DeleteChangeSet",
        "cloudformation:DescribeChangeSet",
        "cloudformation:ValidateTemplate"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SecretsManager",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:CreateSecret",
        "secretsmanager:DeleteSecret",
        "secretsmanager:GetSecretValue",
        "secretsmanager:PutSecretValue",
        "secretsmanager:DescribeSecret",
        "secretsmanager:TagResource"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:DeleteLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:GetLogEvents",
        "logs:FilterLogEvents",
        "logs:PutRetentionPolicy",
        "logs:TagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "STSIdentity",
      "Effect": "Allow",
      "Action": "sts:GetCallerIdentity",
      "Resource": "*"
    },
    {
      "Sid": "CDKBootstrap",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "s3:*"
      ],
      "Resource": "*"
    }
  ]
}
```

> **Note**: The deployer policy above follows least-privilege principles where possible. The CDK bootstrap (`ssm:GetParameter`, `s3:*`) is broadly scoped because CDK uses dynamically-named S3 buckets. In production, scope these to your CDK bootstrap bucket ARN.

### Deployer Trust Policy (for service roles)

All AgentCore execution roles must trust the `bedrock-agentcore.amazonaws.com` service principal with confused deputy protections:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock-agentcore.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "ACCOUNT_ID"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock-agentcore:us-west-2:ACCOUNT_ID:*"
        }
      }
    }
  ]
}
```

---

## 2. Read-Only Viewer Permissions

### What Viewers Can See

| Resource | Visible Information |
|---|---|
| AgentCore Runtimes | Name, ARN, status, configuration, environment variables (names only) |
| AgentCore Gateways | Name, ARN, targets, authorization config |
| Cognito User Pools | Pool config, clients (not secrets), domains, resource servers |
| ECR Repositories | Repository names, image tags, scan results |
| CloudFormation Stacks | Stack status, outputs, parameters, resources |
| IAM Roles | Role config, attached policies, trust relationships |
| CloudWatch Logs | Runtime and agent execution logs |
| CloudWatch Metrics | AgentCore runtime metrics |

### Viewer IAM Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AgentCoreReadOnly",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:GetAgentRuntime",
        "bedrock-agentcore:GetAgentRuntimeEndpoint",
        "bedrock-agentcore:GetGateway",
        "bedrock-agentcore:GetGatewayTarget",
        "bedrock-agentcore:GetOauth2CredentialProvider",
        "bedrock-agentcore:GetTokenVault",
        "bedrock-agentcore:GetResourcePolicy",
        "bedrock-agentcore:GetMemory",
        "bedrock-agentcore:GetEvaluator",
        "bedrock-agentcore:GetOnlineEvaluationConfig",
        "bedrock-agentcore:ListAgentRuntimes",
        "bedrock-agentcore:ListAgentRuntimeVersions",
        "bedrock-agentcore:ListAgentRuntimeEndpoints",
        "bedrock-agentcore:ListGateways",
        "bedrock-agentcore:ListGatewayTargets",
        "bedrock-agentcore:ListOauth2CredentialProviders",
        "bedrock-agentcore:ListMemories",
        "bedrock-agentcore:ListEvaluators",
        "bedrock-agentcore:ListOnlineEvaluationConfigs",
        "bedrock-agentcore:ListTagsForResource"
      ],
      "Resource": "arn:aws:bedrock-agentcore:*:*:*"
    },
    {
      "Sid": "CognitoReadOnly",
      "Effect": "Allow",
      "Action": [
        "cognito-idp:DescribeUserPool",
        "cognito-idp:DescribeUserPoolClient",
        "cognito-idp:DescribeUserPoolDomain",
        "cognito-idp:DescribeResourceServer",
        "cognito-idp:ListUserPools",
        "cognito-idp:ListUserPoolClients",
        "cognito-idp:ListResourceServers",
        "cognito-idp:ListTagsForResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ECRReadOnly",
      "Effect": "Allow",
      "Action": [
        "ecr:DescribeRepositories",
        "ecr:DescribeImages",
        "ecr:DescribeImageScanFindings",
        "ecr:GetRepositoryPolicy",
        "ecr:GetLifecyclePolicy",
        "ecr:ListImages",
        "ecr:ListTagsForResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudFormationReadOnly",
      "Effect": "Allow",
      "Action": [
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "cloudformation:DescribeStackResources",
        "cloudformation:GetTemplateSummary",
        "cloudformation:GetStackPolicy",
        "cloudformation:ListStacks",
        "cloudformation:ListStackResources"
      ],
      "Resource": "*"
    },
    {
      "Sid": "IAMReadOnly",
      "Effect": "Allow",
      "Action": [
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListRoles",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies",
        "iam:ListRoleTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LogsReadOnly",
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:GetLogEvents",
        "logs:FilterLogEvents",
        "logs:StartQuery",
        "logs:StopQuery",
        "logs:GetQueryResults",
        "logs:StartLiveTail",
        "logs:StopLiveTail"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchMetricsReadOnly",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricData",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "cloudwatch:DescribeAlarms"
      ],
      "Resource": "*"
    },
    {
      "Sid": "XRayReadOnly",
      "Effect": "Allow",
      "Action": [
        "xray:GetTraceSummaries",
        "xray:BatchGetTraces",
        "xray:GetServiceGraph"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LambdaReadOnly",
      "Effect": "Allow",
      "Action": [
        "lambda:GetFunction",
        "lambda:GetFunctionConfiguration",
        "lambda:ListFunctions",
        "lambda:GetPolicy"
      ],
      "Resource": "*"
    },
    {
      "Sid": "STSIdentity",
      "Effect": "Allow",
      "Action": "sts:GetCallerIdentity",
      "Resource": "*"
    }
  ]
}
```

### Viewer Restrictions

The viewer policy explicitly **excludes**:

| Excluded Action Pattern | Reason |
|---|---|
| `bedrock-agentcore:Create*`, `Update*`, `Delete*` | Cannot modify infrastructure |
| `bedrock-agentcore:Invoke*` | Cannot invoke agents or gateways |
| `bedrock-agentcore:GetWorkloadAccessToken*` | Cannot generate auth tokens |
| `bedrock-agentcore:GetResourceOauth2Token` | Cannot obtain OAuth tokens |
| `cognito-idp:Admin*`, `Create*`, `Delete*`, `Update*` | Cannot modify Cognito config |
| `cloudformation:Create*`, `Update*`, `Delete*`, `Execute*` | Cannot modify stacks |
| `cloudformation:GetTemplate` | Prevents exposure of secrets in CFN parameters |
| `ecr:BatchGetImage`, `GetDownloadUrlForLayer` | Cannot pull container images |
| `iam:Create*`, `Delete*`, `Attach*`, `Detach*`, `Put*`, `PassRole` | Cannot modify IAM |
| `secretsmanager:GetSecretValue` | Cannot read secret values |

> **Security note**: `cloudformation:GetTemplate` is intentionally excluded because CFN templates may contain Neo4j credentials passed as parameters. Use `GetTemplateSummary` instead for metadata inspection.

### Alternative: AWS Managed Policy

For a quick start, attach the `ViewOnlyAccess` managed policy (`arn:aws:iam::aws:policy/job-function/ViewOnlyAccess`). This grants `List*` and `Describe*` across most AWS services. However, it does not include AgentCore-specific `Get*` actions, so you would supplement it with the `AgentCoreReadOnly` statement above.

---

## 3. Agent Sandbox Tester Permissions

The sandbox tester can invoke deployed agents and gateways to test agent behavior, view their own invocation logs, but cannot modify any infrastructure.

### What Testers Can Do

| Action | Description |
|---|---|
| Invoke Gateway | Send MCP requests through the gateway using JWT auth |
| Invoke Agent Runtime | Call agent endpoints directly via API |
| View logs | Read CloudWatch logs from their invocations |
| View agent cards | Retrieve agent metadata (A2A protocol) |
| List resources | See what runtimes and gateways are available |

### Sandbox Tester IAM Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AgentCoreInvoke",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:InvokeAgentRuntime",
        "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream",
        "bedrock-agentcore:InvokeGateway",
        "bedrock-agentcore:StopRuntimeSession",
        "bedrock-agentcore:GetAgentCard"
      ],
      "Resource": "arn:aws:bedrock-agentcore:us-west-2:ACCOUNT_ID:*"
    },
    {
      "Sid": "AgentCoreReadOnly",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:GetAgentRuntime",
        "bedrock-agentcore:GetAgentRuntimeEndpoint",
        "bedrock-agentcore:GetGateway",
        "bedrock-agentcore:GetGatewayTarget",
        "bedrock-agentcore:ListAgentRuntimes",
        "bedrock-agentcore:ListAgentRuntimeEndpoints",
        "bedrock-agentcore:ListGateways",
        "bedrock-agentcore:ListGatewayTargets",
        "bedrock-agentcore:ListTagsForResource"
      ],
      "Resource": "arn:aws:bedrock-agentcore:us-west-2:ACCOUNT_ID:*"
    },
    {
      "Sid": "LogsReadOnly",
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:GetLogEvents",
        "logs:FilterLogEvents",
        "logs:StartLiveTail",
        "logs:StopLiveTail"
      ],
      "Resource": "arn:aws:logs:us-west-2:ACCOUNT_ID:log-group:/aws/bedrock-agentcore/*"
    },
    {
      "Sid": "BedrockModelAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-*",
        "arn:aws:bedrock:us-west-2:ACCOUNT_ID:inference-profile/*"
      ]
    },
    {
      "Sid": "STSIdentity",
      "Effect": "Allow",
      "Action": "sts:GetCallerIdentity",
      "Resource": "*"
    }
  ]
}
```

### Restricting Sandbox to Specific Resources

To limit testers to only specific agents or gateways, narrow the resource ARNs:

```json
{
  "Sid": "InvokeSpecificAgent",
  "Effect": "Allow",
  "Action": [
    "bedrock-agentcore:InvokeAgentRuntime",
    "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream"
  ],
  "Resource": [
    "arn:aws:bedrock-agentcore:us-west-2:ACCOUNT_ID:runtime/basic_agent_*",
    "arn:aws:bedrock-agentcore:us-west-2:ACCOUNT_ID:runtime/basic_agent_*/runtime-endpoint/*"
  ]
}
```

> **Note**: AgentCore evaluates authorization hierarchically -- both the runtime AND endpoint resource policies must allow the action. For cross-account invocation, attach resource-based policies to both resources.

### Sandbox Guardrails

Apply these deny statements to prevent sandbox testers from modifying infrastructure or escalating privileges:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyInfraModification",
      "Effect": "Deny",
      "Action": [
        "bedrock-agentcore:Create*",
        "bedrock-agentcore:Update*",
        "bedrock-agentcore:Delete*",
        "bedrock-agentcore:PutResourcePolicy",
        "bedrock-agentcore:DeleteResourcePolicy",
        "bedrock-agentcore:TagResource",
        "bedrock-agentcore:UntagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyIAMModification",
      "Effect": "Deny",
      "Action": [
        "iam:Create*",
        "iam:Delete*",
        "iam:Attach*",
        "iam:Detach*",
        "iam:Put*",
        "iam:PassRole",
        "iam:UpdateAssumeRolePolicy"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyRegionEscape",
      "Effect": "Deny",
      "Action": "*",
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": "us-west-2"
        }
      }
    },
    {
      "Sid": "DenyUnauthGateway",
      "Effect": "Deny",
      "Action": "bedrock-agentcore:CreateGateway",
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "bedrock-agentcore:GatewayAuthorizerType": "NONE"
        }
      }
    }
  ]
}
```

### Using the Sandbox with OAuth (Gateway Invocation)

Testers who invoke the Gateway directly (as the agents do) need a Cognito JWT token rather than IAM permissions. The flow:

1. Deployer provides tester with `client_id`, `client_secret`, and `token_url` from `.mcp-credentials.json`
2. Tester obtains JWT:
   ```bash
   curl -X POST "$TOKEN_URL" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=client_credentials&client_id=$CLIENT_ID&client_secret=$CLIENT_SECRET&scope=$SCOPE"
   ```
3. Tester invokes Gateway with JWT:
   ```bash
   curl -X POST "$GATEWAY_URL" \
     -H "Authorization: Bearer $ACCESS_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
   ```

This path uses **Cognito JWT validation** at the Gateway level, not IAM. The tester does not need `bedrock-agentcore:InvokeGateway` IAM permission for this flow -- the JWT is validated independently by the Gateway's Custom JWT Authorizer.

For **direct runtime invocation** (SigV4-signed API calls via `boto3`), the tester needs the `bedrock-agentcore:InvokeAgentRuntime` IAM permission from the policy above.

---

## Cross-Account Access Pattern

For organizations with separate deployer and viewer/tester accounts:

```
Deployer Account (111111111111)         Viewer Account (222222222222)
  |                                       |
  +-- Deploys all resources               +-- Assumes cross-account role
  +-- Creates cross-account role          +-- Gets read-only permissions
      with trust to viewer account        +-- Views resources in deployer account
```

### Step 1: Create cross-account role in deployer account

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::222222222222:root"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:PrincipalOrgID": "o-yourorgid"
        }
      }
    }
  ]
}
```

Attach the [Viewer IAM Policy](#viewer-iam-policy) to this role.

### Step 2: Grant assume-role in viewer account

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::111111111111:role/AgentCoreViewerRole"
    }
  ]
}
```

### Step 3: Viewer assumes role

```bash
aws sts assume-role \
  --role-arn arn:aws:iam::111111111111:role/AgentCoreViewerRole \
  --role-session-name viewer-session
```

For the sandbox tester, create a separate cross-account role with the [Sandbox Tester IAM Policy](#sandbox-tester-iam-policy) instead.

---

## Implementation Guide

### Setting up all three personas

1. **Create IAM policies** using the JSON above (adjust `ACCOUNT_ID` and region)
2. **Create IAM roles** or users for each persona
3. **Attach policies** to the appropriate roles
4. **Test with the deployer** by running `./deploy.sh` in `neo4j-agentcore-mcp-server/`
5. **Verify viewer access** by running describe/list commands:
   ```bash
   # As viewer role
   aws bedrock-agentcore-control list-agent-runtimes --region us-west-2
   aws bedrock-agentcore-control list-gateways --region us-west-2
   aws cloudformation describe-stacks --region us-west-2
   ```
6. **Verify sandbox tester** by invoking the agent:
   ```bash
   # As sandbox tester role (SigV4 path)
   cd agentcore-neo4j-mcp-agent/basic-agent
   uv run python invoke_agent.py "What is the database schema?"

   # Or via Gateway JWT (no IAM required, just credentials)
   cd neo4j-agentcore-mcp-server
   ./cloud.sh tools
   ```

### Verify deny rules work

```bash
# As viewer -- should be denied
aws bedrock-agentcore-control delete-agent-runtime \
  --agent-runtime-id test-id --region us-west-2
# Expected: AccessDeniedException

# As sandbox tester -- should be denied
aws cloudformation delete-stack --stack-name neo4j-agentcore-mcp-server
# Expected: AccessDeniedException
```

---

## AWS Documentation References

| Topic | URL |
|---|---|
| AgentCore Runtime Permissions | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html |
| AgentCore Gateway Permissions | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-prerequisites-permissions.html |
| AgentCore IAM Policy Examples | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/security_iam_id-based-policy-examples.html |
| AgentCore Managed Policies | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/security-iam-awsmanpol.html |
| AgentCore + IAM Overview | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/security_iam_service-with-iam.html |
| AgentCore Resource-Based Policies | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html |
| AgentCore Gateway Auth | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html |
| AgentCore VPC Conditions | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/security-vpc-condition.html |
| BedrockAgentCoreFullAccess Policy | https://docs.aws.amazon.com/aws-managed-policy/latest/reference/BedrockAgentCoreFullAccess.html |
| Service Authorization Reference | https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrockagentcore.html |
| IAM Best Practices | https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html |
| ReadOnlyAccess Managed Policy | https://docs.aws.amazon.com/aws-managed-policy/latest/reference/ReadOnlyAccess.html |
| ViewOnlyAccess Managed Policy | https://docs.aws.amazon.com/aws-managed-policy/latest/reference/ViewOnlyAccess.html |
| Cross-Account Access | https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies-cross-account-resource-access.html |
| IAM Condition Keys | https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-keys.html |
| CloudFormation Least Privilege | https://docs.aws.amazon.com/prescriptive-guidance/latest/least-privilege-cloudformation/best-practices-identity-based-policies.html |
