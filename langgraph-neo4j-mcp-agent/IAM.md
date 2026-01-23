# IAM Permissions

This document describes the IAM permissions required for `setup-inference-profile.sh` and the notebooks.

## Overview

The setup script and notebooks manage and use Bedrock inference profiles. They do **not** create any IAM roles.

## setup-inference-profile.sh Permissions

| Action | Purpose |
|--------|---------|
| `sts:GetCallerIdentity` | Get AWS account ID |
| `bedrock:ListInferenceProfiles` | List existing profiles |
| `bedrock:GetInferenceProfile` | Get profile details |
| `bedrock:CreateInferenceProfile` | Create new profiles |
| `bedrock:DeleteInferenceProfile` | Delete profiles (--delete flag) |
| `bedrock:ListTagsForResource` | Check tags on profiles |
| `bedrock-runtime:Converse` | Test profiles (--test flag) |

## Notebook Permissions

All three notebooks use Bedrock inference profiles to invoke Claude models:

| Notebook | Additional Permissions |
|----------|----------------------|
| `minimal_langgraph_agent.ipynb` | `bedrock-runtime:Converse` |
| `neo4j_simple_mcp_agent.ipynb` | `bedrock-runtime:Converse` |
| `neo4j_strands_mcp_agent.ipynb` | `bedrock-runtime:Converse`, `bedrock-runtime:InvokeModel` |

**Note:** The MCP Gateway notebooks (`neo4j_simple_mcp_agent.ipynb` and `neo4j_strands_mcp_agent.ipynb`) authenticate to the gateway using a Bearer token over HTTPS, not IAM. The gateway credentials come from `.mcp-credentials.json`.

## Combined IAM Policy

This policy covers both the setup script and all notebooks:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InferenceProfileManagement",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "bedrock:ListInferenceProfiles",
        "bedrock:GetInferenceProfile",
        "bedrock:CreateInferenceProfile",
        "bedrock:DeleteInferenceProfile",
        "bedrock:ListTagsForResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BedrockModelInvocation",
      "Effect": "Allow",
      "Action": [
        "bedrock-runtime:Converse",
        "bedrock-runtime:InvokeModel"
      ],
      "Resource": "*"
    }
  ]
}
```

## Notes

- The script creates application inference profiles with the `AmazonBedrockManaged=true` tag
- This tag is required for SageMaker Unified Studio to access the profiles
- Region defaults to `us-west-2` but can be overridden via `AWS_REGION`
- MCP Gateway authentication uses Bearer tokens, not IAM credentials
