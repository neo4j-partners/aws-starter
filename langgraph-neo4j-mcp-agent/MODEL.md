# Model Configuration for SageMaker Unified Studio

This document describes the model configuration challenges and solutions for running LangGraph agents with Bedrock in SageMaker Unified Studio.

## The Problem

SageMaker Unified Studio uses a **permissions boundary** (`SageMakerStudioProjectUserRolePermissionsBoundary`) that restricts Bedrock access. Direct model invocation is blocked:

```
AccessDeniedException: User is not authorized to perform: bedrock:InvokeModel
on resource: arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-*
```

## What Works

**Only inference profiles created by SageMaker Unified Studio work.**

When you create an app in **Bedrock IDE** (within SageMaker Unified Studio), it automatically creates an application inference profile with the proper internal associations.

### Working Configuration

```python
# Profile created by SageMaker Unified Studio (via Bedrock IDE)
INFERENCE_PROFILE_ARN = "arn:aws:bedrock:us-west-2:ACCOUNT:application-inference-profile/PROFILE_ID"

llm = ChatBedrockConverse(
    model=INFERENCE_PROFILE_ARN,
    provider="anthropic",  # Required when using ARN
    region_name="us-west-2",
    temperature=0,
)
```

### How to Get a Working Profile

1. Go to SageMaker Unified Studio → **Build** → **Bedrock IDE**
2. Create any app (agent, chat, etc.)
3. Export the app
4. Find the `inferenceProfileArn` in the export:
   ```bash
   grep "inferenceProfileArn" amazon-bedrock-ide-app-export-*/amazon-bedrock-ide-app-stack-*.json
   ```

## What Does NOT Work

### 1. Direct Model IDs

```python
# FAILS - permissions boundary blocks direct model access
MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
```

### 2. Cross-Region Inference Profiles (us. prefix)

```python
# FAILS - still blocked by permissions boundary
MODEL_ID = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
```

### 3. Manually Created Application Inference Profiles

Even with correct DataZone tags, profiles created via CLI don't work:

```bash
# Creates profile but it FAILS when used in SageMaker Studio
aws bedrock create-inference-profile \
  --inference-profile-name "my-profile" \
  --model-source 'copyFrom=arn:aws:bedrock:us-west-2:ACCOUNT:inference-profile/us.anthropic.claude-3-5-sonnet-20241022-v2:0' \
  --tags key=AmazonDataZoneProject,value=PROJECT_ID key=AmazonDataZoneDomain,value=DOMAIN_ID
```

## Key Differences

| Attribute | SageMaker-Created Profile | Script-Created Profile |
|-----------|---------------------------|------------------------|
| Works in Studio | ✅ Yes | ❌ No |
| Description | `"Created by Amazon SageMaker Unified Studio for domain {domain} to provide access to Amazon Bedrock model in project {project}"` | `"LangGraph lab inference profile"` |
| Internal associations | Has proper IAM/DataZone bindings | Missing internal bindings |
| Tags | Auto-tagged by SageMaker | Manually tagged |

## What Needs to be Fixed

### Option 1: AWS Feature Request

Request AWS add a way to create inference profiles with proper SageMaker Unified Studio bindings via CLI/API. Currently, the only way is through the Bedrock IDE UI.

### Option 2: Use Bedrock IDE Export

Current workaround:
1. Create app in Bedrock IDE for each model you need
2. Export to get the inference profile ARN
3. Use that ARN in notebooks

### Option 3: Different Compute Environment

Run notebooks outside SageMaker Unified Studio:
- SageMaker Classic Studio
- SageMaker Notebook Instances
- EC2
- Local machine

These environments don't have the restrictive permissions boundary.

## Current Workaround

1. Create an app in Bedrock IDE (SageMaker Unified Studio)
2. Export the app
3. Extract the inference profile ARN from the export
4. Use that ARN in your notebook

```bash
# Find ARN in export
grep "inferenceProfileArn" amazon-bedrock-ide-app-export-*/amazon-bedrock-ide-app-stack-*.json

# Output example:
# "inferenceProfileArn": "arn:aws:bedrock:us-west-2:159878781974:application-inference-profile/hsl5b7kh1279"
```

## Script Status

The `setup-inference-profile.sh` script **does not work** for SageMaker Unified Studio because:

1. CLI-created profiles lack internal SageMaker/DataZone bindings
2. The permissions boundary checks for these internal bindings, not just tags
3. Only profiles created through the SageMaker Unified Studio UI have these bindings

The script may still be useful for:
- Other AWS environments (EC2, Lambda, local)
- Cost tracking via application inference profiles
- Environments without restrictive permissions boundaries

## References

- [SageMakerStudioProjectUserRolePermissionsBoundary](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/SageMakerStudioProjectUserRolePermissionsBoundary.html)
- [Configure fine-grained access to Amazon Bedrock models using SageMaker Unified Studio](https://aws.amazon.com/blogs/machine-learning/configure-fine-grained-access-to-amazon-bedrock-models-using-amazon-sagemaker-unified-studio/)
- [Create an application inference profile](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-create.html)
