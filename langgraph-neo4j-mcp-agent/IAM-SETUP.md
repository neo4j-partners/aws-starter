# IAM Setup for LangGraph Bedrock Agents

This document describes the IAM permissions required to run LangGraph agents with AWS Bedrock in SageMaker Studio or other AWS environments.

## Table of Contents

- [Quick Start](#quick-start)
- [Model ID Formats](#model-id-formats)
- [Minimum Required Permissions](#minimum-required-permissions)
- [SageMaker Studio Setup](#sagemaker-studio-setup)
- [Additional Useful Permissions](#additional-useful-permissions)
- [Cross-Region Inference Profiles](#cross-region-inference-profiles)
- [Troubleshooting](#troubleshooting)
- [Sources](#sources)

---

## Quick Start

For basic LangGraph agent testing with Bedrock Claude, attach this policy to your IAM role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvokeModels",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.*"
      ]
    }
  ]
}
```

---

## Model ID Formats

Understanding model ID formats is critical for IAM permissions:

| Format | Type | Example | IAM Resource ARN |
|--------|------|---------|------------------|
| `anthropic.claude-*` | Base model | `anthropic.claude-sonnet-4-20250514-v1:0` | `arn:aws:bedrock:REGION::foundation-model/anthropic.claude-*` |
| `us.anthropic.claude-*` | Cross-region inference profile | `us.anthropic.claude-sonnet-4-20250514-v1:0` | `arn:aws:bedrock:REGION:ACCOUNT:inference-profile/us.anthropic.claude-*` |
| `eu.anthropic.claude-*` | EU inference profile | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | `arn:aws:bedrock:REGION:ACCOUNT:inference-profile/eu.anthropic.claude-*` |

### Recommended Model IDs (Base Models)

These work with standard `foundation-model` permissions:

| Model | Model ID |
|-------|----------|
| Claude Sonnet 4 | `anthropic.claude-sonnet-4-20250514-v1:0` |
| Claude Sonnet 4.5 | `anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Claude 3.5 Sonnet | `anthropic.claude-3-5-sonnet-20241022-v2:0` |
| Claude 3.5 Haiku | `anthropic.claude-3-5-haiku-20241022-v1:0` |
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5-20251001-v1:0` |
| Claude Opus 4.5 | `anthropic.claude-opus-4-5-20251101-v1:0` |

---

## Minimum Required Permissions

### Policy: Basic Model Invocation

This is the minimum required to run the notebooks:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvokeFoundationModels",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.*"
      ]
    }
  ]
}
```

### Policy: Specific Model Only (Least Privilege)

For production, restrict to specific models:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvokeClaudeSonnet4",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0",
        "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
      ]
    }
  ]
}
```

### Policy: Region-Specific

Lock to specific regions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvokeUSWest2Only",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-west-2::foundation-model/anthropic.*"
      ]
    }
  ]
}
```

---

## SageMaker Studio Setup

### Option 1: Modify Existing Execution Role

1. Go to **IAM Console** > **Roles**
2. Find your SageMaker execution role (e.g., `datazone_usr_role_*` or `AmazonSageMaker-ExecutionRole-*`)
3. Click **Add permissions** > **Create inline policy**
4. Use the JSON editor and paste the policy below:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:ListFoundationModels",
        "bedrock:GetFoundationModel"
      ],
      "Resource": "*"
    }
  ]
}
```

5. Name it `BedrockAccess` and create

### Option 2: Use AWS Managed Policy

Attach the managed policy **AmazonBedrockFullAccess** or **AmazonBedrockReadOnly** to your role:

```bash
aws iam attach-role-policy \
  --role-name YOUR_SAGEMAKER_EXECUTION_ROLE \
  --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess
```

### Option 3: SageMaker Unified Studio

If using SageMaker Unified Studio, the **AmazonSageMakerBedrockModelConsumptionRole** comes with preconfigured Bedrock permissions. You may need to add inline policies for specific model access.

### Trust Relationship (if required)

Some setups require Bedrock in the trust relationship:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": [
          "sagemaker.amazonaws.com",
          "bedrock.amazonaws.com"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

---

## Additional Useful Permissions

### List and Discover Models

Allows listing available models in the console or via API:

```json
{
  "Sid": "BedrockListModels",
  "Effect": "Allow",
  "Action": [
    "bedrock:ListFoundationModels",
    "bedrock:GetFoundationModel",
    "bedrock:ListInferenceProfiles",
    "bedrock:GetInferenceProfile"
  ],
  "Resource": "*"
}
```

### Token Counting

Useful for cost estimation:

```json
{
  "Sid": "BedrockCountTokens",
  "Effect": "Allow",
  "Action": "bedrock:CountTokens",
  "Resource": "arn:aws:bedrock:*::foundation-model/*"
}
```

### Batch/Async Invocation

For batch processing jobs:

```json
{
  "Sid": "BedrockBatchInvocation",
  "Effect": "Allow",
  "Action": [
    "bedrock:CreateModelInvocationJob",
    "bedrock:GetModelInvocationJob",
    "bedrock:ListModelInvocationJobs",
    "bedrock:StopModelInvocationJob",
    "bedrock:GetAsyncInvoke",
    "bedrock:ListAsyncInvokes"
  ],
  "Resource": [
    "arn:aws:bedrock:*:*:model-invocation-job/*",
    "arn:aws:bedrock:*:*:async-invoke/*"
  ]
}
```

### Guardrails (Safety)

For applying content guardrails:

```json
{
  "Sid": "BedrockGuardrails",
  "Effect": "Allow",
  "Action": [
    "bedrock:ApplyGuardrail",
    "bedrock:GetGuardrail",
    "bedrock:ListGuardrails"
  ],
  "Resource": "arn:aws:bedrock:*:*:guardrail/*"
}
```

---

## Cross-Region Inference Profiles

If you need cross-region inference (using `us.`, `eu.`, `apac.` prefixes), add:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInferenceProfiles",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.*",
        "arn:aws:bedrock:*:*:inference-profile/us.anthropic.*",
        "arn:aws:bedrock:*:*:inference-profile/eu.anthropic.*",
        "arn:aws:bedrock:*:*:inference-profile/apac.anthropic.*"
      ]
    }
  ]
}
```

---

## Complete Recommended Policy

For development and testing, this comprehensive policy covers most use cases:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockModelInvocation",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.*",
        "arn:aws:bedrock:*::foundation-model/amazon.*",
        "arn:aws:bedrock:*:*:inference-profile/*"
      ]
    },
    {
      "Sid": "BedrockDiscovery",
      "Effect": "Allow",
      "Action": [
        "bedrock:ListFoundationModels",
        "bedrock:GetFoundationModel",
        "bedrock:ListInferenceProfiles",
        "bedrock:GetInferenceProfile"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BedrockTokenCounting",
      "Effect": "Allow",
      "Action": "bedrock:CountTokens",
      "Resource": "arn:aws:bedrock:*::foundation-model/*"
    }
  ]
}
```

---

## Troubleshooting

### Error: AccessDeniedException on inference-profile

**Problem:**
```
AccessDeniedException: User is not authorized to perform: bedrock:InvokeModel
on resource: arn:aws:bedrock:us-west-2:123456789012:inference-profile/us.anthropic.claude-*
```

**Solution:** Either:
1. Use base model ID without prefix: `anthropic.claude-sonnet-4-20250514-v1:0`
2. Add inference-profile to IAM policy resource

### Error: AccessDeniedException on foundation-model

**Problem:**
```
AccessDeniedException: User is not authorized to perform: bedrock:InvokeModel
on resource: arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-*
```

**Solution:**
1. Verify the model ID is correct
2. Check IAM policy includes the foundation-model ARN
3. Ensure model access is enabled in Bedrock console (some models require explicit enablement)

### Error: Model not found

**Problem:**
```
ResourceNotFoundException: Could not resolve the foundation model
```

**Solution:**
1. Verify model ID spelling and version
2. Check model availability in your region
3. Some newer models may not be available in all regions

### Verifying Permissions

Test your permissions with AWS CLI:

```bash
# Check current identity
aws sts get-caller-identity

# List available Bedrock models
aws bedrock list-foundation-models --region us-west-2

# Test model invocation (simple)
aws bedrock-runtime invoke-model \
  --model-id anthropic.claude-3-5-haiku-20241022-v1:0 \
  --region us-west-2 \
  --body '{"anthropic_version":"bedrock-2023-05-31","max_tokens":100,"messages":[{"role":"user","content":"Hello"}]}' \
  --content-type application/json \
  output.json
```

---

## ARN Reference

| Resource Type | ARN Format |
|---------------|------------|
| Foundation Model | `arn:aws:bedrock:REGION::foundation-model/MODEL_ID` |
| Inference Profile | `arn:aws:bedrock:REGION:ACCOUNT:inference-profile/PROFILE_ID` |
| Provisioned Model | `arn:aws:bedrock:REGION:ACCOUNT:provisioned-model/NAME` |
| Guardrail | `arn:aws:bedrock:REGION:ACCOUNT:guardrail/ID` |
| Custom Model | `arn:aws:bedrock:REGION:ACCOUNT:custom-model/NAME` |
| Model Invocation Job | `arn:aws:bedrock:REGION:ACCOUNT:model-invocation-job/ID` |

Note: Foundation models have no account ID in the ARN (uses `::` double colon).

---

## Sources

- [Identity-based policy examples for Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html)
- [Actions, resources, and condition keys for Amazon Bedrock](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrock.html)
- [How Amazon Bedrock works with IAM](https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_service-with-iam.html)
- [AWS managed policies for Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/security-iam-awsmanpol.html)
- [Simplified model access in Amazon Bedrock](https://aws.amazon.com/blogs/security/simplified-amazon-bedrock-model-access/)
- [Implementing least privilege access for Amazon Bedrock](https://aws.amazon.com/blogs/security/implementing-least-privilege-access-for-amazon-bedrock/)
- [Access Amazon Bedrock foundation models](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)
- [Grant Users Permissions for Bedrock in SageMaker Canvas](https://docs.aws.amazon.com/sagemaker/latest/dg/canvas-fine-tuning-permissions.html)
- [SageMakerStudioBedrockFunctionExecutionRolePolicy](https://docs.aws.amazon.com/sagemaker-unified-studio/latest/adminguide/security-iam-awsmanpol-SageMakerStudioBedrockFunctionExecutionRolePolicy.html)
- [Configure fine-grained access to Amazon Bedrock models using SageMaker Unified Studio](https://aws.amazon.com/blogs/machine-learning/configure-fine-grained-access-to-amazon-bedrock-models-using-amazon-sagemaker-unified-studio/)
