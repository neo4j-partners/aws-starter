# Model Configuration for SageMaker Unified Studio

## TL;DR - Three Keys to Success

### 1. `AmazonBedrockManaged=true` Tag
SageMaker Unified Studio's permissions boundary only allows `bedrock:InvokeModel` on inference profiles with this tag.

### 2. `base_model_id` Parameter
The `langchain-aws` library calls `bedrock:GetInferenceProfile` which SageMaker roles don't have. Bypass it:

```python
llm = ChatBedrockConverse(
    model=INFERENCE_PROFILE_ARN,
    provider="anthropic",
    region_name="us-west-2",
    base_model_id="anthropic.claude-3-5-haiku-20241022-v1:0",  # Bypasses GetInferenceProfile
)
```

### 3. DataZone IDs from AWS CLI
The setup script auto-detects DataZone IDs via `aws datazone list-domains` and `aws datazone list-projects` - no Bedrock IDE export folder needed.

---

## Quick Start

```bash
# Run from CLI (auto-detects DataZone IDs)
./setup-inference-profile.sh haiku

# Output:
# MODEL = "haiku"
# INFERENCE_PROFILE_ARN = "arn:aws:bedrock:us-west-2:..."
```

Copy both values to your notebook:

```python
MODEL = "haiku"
INFERENCE_PROFILE_ARN = "arn:aws:bedrock:us-west-2:ACCOUNT:application-inference-profile/ID"
REGION = "us-west-2"

BASE_MODEL_IDS = {
    "haiku": "anthropic.claude-3-5-haiku-20241022-v1:0",
    "sonnet": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "sonnet4": "anthropic.claude-sonnet-4-20250514-v1:0",
    "sonnet45": "anthropic.claude-sonnet-4-5-20250929-v1:0",
}

llm = ChatBedrockConverse(
    model=INFERENCE_PROFILE_ARN,
    provider="anthropic",
    region_name=REGION,
    base_model_id=BASE_MODEL_IDS[MODEL],
)
```

---

## Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `AccessDeniedException: bedrock:InvokeModel` | Profile missing `AmazonBedrockManaged=true` tag | Recreate with `./setup-inference-profile.sh` |
| `AccessDeniedException: bedrock:GetInferenceProfile` | SageMaker role lacks this permission | Add `base_model_id` parameter |
| `ValidationException: provider` | Using ARN without provider param | Add `provider="anthropic"` |

---

## Why This Works

SageMaker Unified Studio uses a **permissions boundary** that blocks direct Bedrock model access:

```json
{
  "Action": ["bedrock:InvokeModel"],
  "Condition": {
    "StringEquals": {
      "aws:ResourceTag/AmazonBedrockManaged": "true"
    }
  }
}
```

The setup script creates profiles with all required tags:
- `AmazonBedrockManaged` = `true` ← **THE KEY!**
- `AmazonDataZoneProject` = `{project_id}`
- `AmazonDataZoneDomain` = `{domain_id}`

---

## Script Features

The `setup-inference-profile.sh` script:

1. **Auto-detects DataZone IDs** from AWS CLI (no export folder needed)
2. **Interactive selection** if multiple domains/projects exist
3. **Creates properly tagged profiles** with `AmazonBedrockManaged=true`
4. **Outputs both MODEL and ARN** for notebook configuration

```bash
./setup-inference-profile.sh --help     # See all options
./setup-inference-profile.sh --list     # Show profiles with tag status
./setup-inference-profile.sh --detect   # Show detected DataZone IDs
./setup-inference-profile.sh haiku      # Create haiku profile
./setup-inference-profile.sh --test haiku  # Create and test
```

---

## Detailed Documentation

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
4. Find the model in the export:
   ```bash
   grep -r "model" amazon-bedrock-ide-app-export-*/amazon-bedrock-ide-app-stack-*.json | grep anthropic
   ```

## Git History: What Was Tried

### Commit 3162797 - Cross-region model ID (FAILS in SageMaker Studio)
```python
MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"

llm = ChatBedrockConverse(
    model=MODEL_ID,
    region_name=REGION,
    temperature=0,
)
```
- No `provider` parameter
- Works outside SageMaker Unified Studio, but fails inside due to permissions boundary

### Commit 4e0c3e8 - Base model ID (FAILS in SageMaker Studio)
```python
MODEL_ID = "anthropic.claude-sonnet-4-20250514-v1:0"

llm = ChatBedrockConverse(
    model=MODEL_ID,
    region_name=REGION,
    temperature=0,
)
```
- Simplest format
- Works outside SageMaker Unified Studio, but fails inside due to permissions boundary

### Commit 7468b76 - Application inference profile ARN (WORKS if created by Bedrock IDE)
```python
MODEL_ID = "arn:aws:bedrock:us-west-2:159878781974:application-inference-profile/9p4fb3e8undd"

llm = ChatBedrockConverse(
    model=MODEL_ID,
    provider="anthropic",  # REQUIRED when using ARN
    region_name=REGION,
    temperature=0,
)
```
- Requires `provider="anthropic"` parameter
- Only works if the profile was created by Bedrock IDE (not CLI)

### Commit 8f442aa - Added setup-inference-profile.sh (BREAKS things)
- Added complex auto-discovery logic
- CLI-created profiles don't work in SageMaker Unified Studio

### Current State - Variable Mismatch (BROKEN)
- Config cell uses `INFERENCE_PROFILE_ARN` variable
- LLM setup cell references `MODEL_ID` variable
- Causes `NameError: name 'MODEL_ID' is not defined`

## What Does NOT Work in SageMaker Unified Studio

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

## Model ID Formats Reference

| Format | Example | `provider` param needed? | Works in SageMaker Studio? |
|--------|---------|--------------------------|---------------------------|
| Base model | `anthropic.claude-3-5-sonnet-20241022-v2:0` | No | No |
| Cross-region | `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | No | No |
| App profile ARN (CLI-created) | `arn:aws:bedrock:...:application-inference-profile/ID` | **Yes** | No |
| App profile ARN (Bedrock IDE) | `arn:aws:bedrock:...:application-inference-profile/ID` | **Yes** | **Yes** |

## Things to Try

### Fix 1: Ensure Variable Consistency
The notebook has a variable mismatch. Ensure both cells use the same variable:

```python
# Configuration cell
INFERENCE_PROFILE_ARN = "arn:aws:bedrock:us-west-2:ACCOUNT:application-inference-profile/ID"
REGION = "us-west-2"

# LLM setup cell - use SAME variable name
llm = ChatBedrockConverse(
    model=INFERENCE_PROFILE_ARN,  # Match the config variable
    provider="anthropic",         # REQUIRED for ARN format
    region_name=REGION,
    temperature=0,
)
```

### Fix 2: Add Missing `provider` Parameter
When using an ARN, `provider="anthropic"` is required:

```python
llm = ChatBedrockConverse(
    model=INFERENCE_PROFILE_ARN,
    provider="anthropic",  # ADD THIS
    region_name=REGION,
    temperature=0,
)
```

### Fix 3: Get Fresh Profile from Bedrock IDE Export
The profile ARN from Bedrock IDE export should work:

```bash
# Find the model ID in latest export
grep -r '"model"' amazon-bedrock-ide-app-export-*/amazon-bedrock-ide-app-stack-*.json | grep anthropic
```

### Fix 4: Try Outside SageMaker Unified Studio
If running locally or on EC2, use direct model ID:

```python
MODEL_ID = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

llm = ChatBedrockConverse(
    model=MODEL_ID,
    region_name=REGION,
    temperature=0,
)
```

## Key Differences: SageMaker-Created vs CLI-Created Profiles

| Attribute | SageMaker-Created Profile | Script-Created Profile |
|-----------|---------------------------|------------------------|
| Works in Studio | Yes | No |
| Description | `"Created by Amazon SageMaker Unified Studio for domain {domain} to provide access to Amazon Bedrock model in project {project}"` | `"LangGraph lab inference profile"` |
| Internal associations | Has proper IAM/DataZone bindings | Missing internal bindings |
| Tags | Auto-tagged by SageMaker | Manually tagged |

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
