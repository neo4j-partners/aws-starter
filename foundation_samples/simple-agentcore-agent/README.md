# Sample 1: Deploy Your First AI Agent (CDK)

Deploy a simple AI agent to Amazon Bedrock AgentCore Runtime using AWS CDK.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (for local builds)
- Node.js (for CDK CLI)
- AWS CDK CLI (`npm install -g aws-cdk`)
- AWS credentials configured
- Amazon Bedrock model access enabled (Claude Sonnet)

## Quick Start

```bash
# Install dependencies
uv sync

# Bootstrap CDK (first time only)
uv run cdk bootstrap

# Deploy to AgentCore Runtime
uv run cdk deploy

# Test the agent
uv run python test_agent.py

# Clean up
uv run cdk destroy
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              AWS Cloud                                   │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Amazon Bedrock AgentCore                      │   │
│  │  ┌─────────────────┐    ┌─────────────────────────────────────┐ │   │
│  │  │  Agent Runtime  │    │         Your Container              │ │   │
│  │  │  (Managed)      │───▶│  ┌─────────────────────────────┐   │ │   │
│  │  │                 │    │  │  BedrockAgentCoreApp        │   │ │   │
│  │  │ • Auto-scaling  │    │  │  ├── @app.entrypoint        │   │ │   │
│  │  │ • Load balancing│    │  │  │   └── invoke(payload)    │   │ │   │
│  │  │ • Health checks │    │  │  └── Strands Agent          │   │ │   │
│  │  └─────────────────┘    │  │      └── Claude Sonnet      │   │ │   │
│  │          │              │  └─────────────────────────────┘   │ │   │
│  │          ▼              └─────────────────────────────────────┘ │   │
│  │  ┌─────────────────┐                                            │   │
│  │  │  CloudWatch     │    ┌─────────────────────────────────────┐ │   │
│  │  │  Logs & Metrics │    │            Amazon ECR               │ │   │
│  │  └─────────────────┘    │  (Container image storage)          │ │   │
│  │                         └─────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     Amazon Bedrock                               │   │
│  │  ┌─────────────────────────────────────────────────────────┐    │   │
│  │  │  Foundation Models (Claude Sonnet, etc.)                 │    │   │
│  │  └─────────────────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │  CDK Deployment  │
    │  ┌────────────┐  │
    │  │ Local      │──────▶ Docker build (ARM64)
    │  │ Docker     │──────▶ Push to ECR
    │  │ Build      │──────▶ Create AgentCore Runtime
    │  └────────────┘  │
    └──────────────────┘
```

## Project Structure

```
sample_one/
├── app.py                    # CDK App entry point
├── sample_one_stack.py       # Main CDK stack
├── cdk.json                  # CDK configuration
├── pyproject.toml            # Dependencies (uv)
├── test_agent.py             # Test script for invoking agent
├── infra_utils/
│   └── agentcore_role.py     # Reusable IAM role construct
└── agent-code/
    ├── agent.py              # Agent code with @app.entrypoint
    ├── Dockerfile            # Container image definition
    └── requirements.txt      # Agent runtime dependencies
```

## How It Works

1. **CDK builds the Docker image locally** (ARM64 architecture)
2. **Image is pushed to CDK's bootstrap ECR repository**
3. **AgentCore Runtime is created** with the container image
4. **Agent receives requests** via `/invocations` endpoint

**Key benefit**: Local Docker builds are much faster than CodeBuild for iterative development (~30s vs ~5min).

## Stack Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| AgentName | QuickStartAgent | Name for the agent runtime |
| NetworkMode | PUBLIC | PUBLIC or PRIVATE |

## Stack Outputs

| Output | Description |
|--------|-------------|
| AgentRuntimeId | ID of the created agent runtime |
| AgentRuntimeArn | ARN for invoking the agent |
| AgentRoleArn | ARN of the IAM execution role |
| ImageUri | URI of the Docker image in ECR |

## Testing the Agent

### Using the test script (recommended)
```bash
uv run python test_agent.py
```

### Using AWS CLI
```bash
# Get the runtime ARN from stack outputs
RUNTIME_ARN=$(aws cloudformation describe-stacks \
  --stack-name SampleOneAgentDemo \
  --query "Stacks[0].Outputs[?OutputKey=='AgentRuntimeArn'].OutputValue" \
  --output text)

# Invoke the agent
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "$RUNTIME_ARN" \
  --payload "$(echo '{"prompt": "What is 2+2?"}' | base64)" \
  --region us-west-2 \
  /tmp/response.json

cat /tmp/response.json
```

## Best Practices

### Dockerfile Best Practices

1. **File Permissions**: When using non-root users, ensure files are readable:
   ```dockerfile
   # Copy files BEFORE creating user, then set ownership
   COPY . .
   RUN useradd -m -u 1000 bedrock_agentcore && \
       chown -R bedrock_agentcore:bedrock_agentcore /app
   USER bedrock_agentcore
   ```

2. **ARM64 Architecture**: AgentCore runs on ARM64 - always build for this platform:
   ```python
   ecr_assets.DockerImageAsset(
       self, "Image",
       directory="./agent-code",
       platform=ecr_assets.Platform.LINUX_ARM64,
   )
   ```

3. **Slim Base Images**: Use `python:3.11-slim` to reduce image size and startup time.

### Agent Code Best Practices

1. **Entrypoint Pattern**: Use the `@app.entrypoint` decorator:
   ```python
   @app.entrypoint
   async def invoke(payload=None):
       query = payload.get("prompt", "Hello!")
       response = agent(query)
       return {"status": "success", "response": response.message['content'][0]['text']}
   ```

2. **Error Handling**: Always wrap agent calls in try/except:
   ```python
   try:
       response = agent(query)
       return {"status": "success", "response": ...}
   except Exception as e:
       return {"status": "error", "error": str(e)}
   ```

3. **Payload Flexibility**: Handle missing or None payloads gracefully:
   ```python
   query = payload.get("prompt", "Hello!") if payload else "Hello!"
   ```

### CDK Best Practices

1. **Use CfnParameter** for configurable values:
   ```python
   agent_name = CfnParameter(self, "AgentName", default="MyAgent")
   ```

2. **Always output the Runtime ARN** for easy invocation:
   ```python
   CfnOutput(self, "AgentRuntimeArn", value=runtime.attr_agent_runtime_arn)
   ```

3. **Use reusable constructs** for IAM roles (see `infra_utils/agentcore_role.py`).

## Debugging Tips

### Container fails with RuntimeClientError

When the agent fails with `RuntimeClientError`, CloudWatch logs may not show Python startup errors. **Run the container locally**:

```bash
cd agent-code
docker build -t test-agent .
docker run --rm -p 8080:8080 -e AWS_REGION=us-west-2 test-agent

# In another terminal:
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello"}'
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Permission denied` on startup | Files owned by root, user is non-root | Add `chown` before `USER` in Dockerfile |
| `Module not found` | Wrong CMD or missing `__main__.py` | Use `CMD ["python", "agent.py"]` |
| `Unable to locate credentials` | Missing IAM permissions | Check `agentcore_role.py` has Bedrock permissions |
| Container starts but hangs | Agent cold start or model access | Wait longer, check Bedrock model access |

### Check CloudWatch Logs

```bash
# Get the log group
aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/runtimes/ \
  --query "logGroups[*].logGroupName"

# Tail recent logs
aws logs tail /aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT --follow
```

## Lessons Learned

1. **File permissions are critical** - The most common issue is files being unreadable by the non-root container user.

2. **Local Docker testing saves time** - Always test containers locally before deploying to AgentCore.

3. **The endpoint is `/invocations`** - Not `/invoke` or `/`. The `BedrockAgentCoreApp` registers routes at `/invocations`, `/ping`, and `/ws`.

4. **Both sync and async entrypoints work** - Despite documentation variations, both patterns are supported.

5. **ARM64 is required** - AgentCore runs ARM64 containers. Ensure your Docker build targets this platform.

6. **OpenTelemetry errors are normal locally** - The `StatusCode.UNAVAILABLE` errors for metrics export only occur when there's no collector running.

## Clean Up

```bash
# Destroy the CDK stack
uv run cdk destroy

# Remove local Docker images (optional)
docker rmi test-agent
```

## Learn More

- [AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [AWS CDK Python Reference](https://docs.aws.amazon.com/cdk/api/v2/python/)
- [Strands Agents](https://strandsagents.com/)
- [BedrockAgentCore Runtime SDK](https://pypi.org/project/bedrock-agentcore/)
