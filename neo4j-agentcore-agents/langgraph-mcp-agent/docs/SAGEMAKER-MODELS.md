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
    region_name="us-east-1",
    base_model_id="anthropic.claude-haiku-4-5-20251001-v1:0",  # Bypasses GetInferenceProfile
)
```

### 3. DataZone IDs from AWS CLI
The setup script auto-detects DataZone IDs via `aws datazone list-domains` and `aws datazone list-projects` - no Bedrock IDE export folder needed.

---

## Quick Start

```bash
# Run from CLI (auto-detects DataZone IDs)
./inference-profiles/setup-inference-profile.sh haiku

# Output:
# MODEL = "haiku"
# INFERENCE_PROFILE_ARN = "arn:aws:bedrock:us-east-1:..."
```

Copy both values to your notebook:

```python
MODEL = "haiku"
INFERENCE_PROFILE_ARN = "arn:aws:bedrock:us-east-1:ACCOUNT:application-inference-profile/ID"
REGION = "us-east-1"

BASE_MODEL_IDS = {
    "haiku": "anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "haiku45": "anthropic.claude-haiku-4-5-20251001-v1:0",
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
| `AccessDeniedException: bedrock:InvokeModel` | Profile missing `AmazonBedrockManaged=true` tag | Recreate with `./inference-profiles/setup-inference-profile.sh` |
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
./inference-profiles/setup-inference-profile.sh --help     # See all options
./inference-profiles/setup-inference-profile.sh --list     # Show profiles with tag status
./inference-profiles/setup-inference-profile.sh --detect   # Show detected DataZone IDs
./inference-profiles/setup-inference-profile.sh haiku      # Create haiku profile
./inference-profiles/setup-inference-profile.sh --test haiku  # Create and test
```

---

## The Problem

SageMaker Unified Studio uses a **permissions boundary** (`SageMakerStudioProjectUserRolePermissionsBoundary`) that restricts Bedrock access. Direct model invocation is blocked:

```
AccessDeniedException: User is not authorized to perform: bedrock:InvokeModel
on resource: arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-*
```

## What Works

An application inference profile works when it carries the `AmazonBedrockManaged=true` tag along with the matching DataZone tags. Profiles created in Bedrock IDE get these tags automatically. `inference-profiles/setup-inference-profile.sh` applies the same tags to CLI-created profiles, so they work too.

```python
# Profile created by Bedrock IDE or by setup-inference-profile.sh
INFERENCE_PROFILE_ARN = "arn:aws:bedrock:us-east-1:ACCOUNT:application-inference-profile/PROFILE_ID"

llm = ChatBedrockConverse(
    model=INFERENCE_PROFILE_ARN,
    provider="anthropic",  # Required when using an ARN
    region_name="us-east-1",
    temperature=0,
    base_model_id="anthropic.claude-haiku-4-5-20251001-v1:0",  # Skips bedrock:GetInferenceProfile
)
```

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

### 3. Application Inference Profiles Without the Magic Tag
A profile created with the DataZone tags but missing `AmazonBedrockManaged=true` is still blocked:
```bash
# Missing AmazonBedrockManaged=true -> FAILS in SageMaker Studio
aws bedrock create-inference-profile \
  --inference-profile-name "my-profile" \
  --model-source 'copyFrom=arn:aws:bedrock:us-east-1:ACCOUNT:inference-profile/us.anthropic.claude-3-5-sonnet-20241022-v2:0' \
  --tags key=AmazonDataZoneProject,value=PROJECT_ID key=AmazonDataZoneDomain,value=DOMAIN_ID
```
Use `inference-profiles/setup-inference-profile.sh`, which applies all three required tags.

## Model ID Formats Reference

| Format | Example | `provider` param needed? | Works in SageMaker Studio? |
|--------|---------|--------------------------|---------------------------|
| Base model | `anthropic.claude-3-5-sonnet-20241022-v2:0` | No | No |
| Cross-region | `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | No | No |
| App profile ARN, no `AmazonBedrockManaged` tag | `arn:aws:bedrock:...:application-inference-profile/ID` | **Yes** | No |
| App profile ARN, tagged (Bedrock IDE or the script) | `arn:aws:bedrock:...:application-inference-profile/ID` | **Yes** | **Yes** |

## References

- [SageMakerStudioProjectUserRolePermissionsBoundary](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/SageMakerStudioProjectUserRolePermissionsBoundary.html)
- [Configure fine-grained access to Amazon Bedrock models using SageMaker Unified Studio](https://aws.amazon.com/blogs/machine-learning/configure-fine-grained-access-to-amazon-bedrock-models-using-amazon-sagemaker-unified-studio/)
- [Create an application inference profile](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-create.html)
