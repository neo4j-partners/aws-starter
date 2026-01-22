# Strands Agent Test

A minimal test project for Strands Agents with Amazon Bedrock AgentCore Runtime. Based on the official AWS sample from [amazon-bedrock-agentcore-samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples).

## Overview

This project demonstrates:
- Strands Agents with Amazon Bedrock models (Claude Haiku 4.5)
- Custom tools (`weather`) and built-in tools (`calculator`)
- Local development and testing
- Cloud deployment to AgentCore Runtime

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- AWS CLI configured with credentials
- Bedrock model access enabled (Claude Haiku 4.5)

## Setup

```bash
cd strands-test
uv sync
```

## Local Testing

Run the agent locally without deploying to AWS:

```bash
# Test weather tool
uv run python strands_claude.py '{"prompt": "What is the weather now?"}'

# Test calculator tool
uv run python strands_claude.py '{"prompt": "What is 25 * 17?"}'
```

## Cloud Deployment

### Deploy to AgentCore Runtime

```bash
uv run python deploy.py
```

This will:
1. Create an ECR repository
2. Create IAM execution roles
3. Build the container image via CodeBuild
4. Deploy to AgentCore Runtime
5. Test the deployment
6. Save deployment info to `deployment_info.json`

### Redeploy (after code changes)

```bash
uv run python redeploy.py
```

### Test the deployed agent

```bash
# Test weather
uv run python test_invoke.py "What is the weather now?"

# Test calculator
uv run python test_invoke.py "What is 123 * 456?"
```

### Cleanup

Delete all AWS resources when done:

```bash
uv run python cleanup.py
```

## Project Structure

```
strands-test/
├── strands_claude.py          # Local testing agent
├── strands_claude_runtime.py  # Cloud deployment agent (with @app.entrypoint)
├── deploy.py                  # Initial deployment script
├── redeploy.py                # Redeploy with Dockerfile fix
├── test_invoke.py             # Test deployed agent
├── cleanup.py                 # Delete AWS resources
├── requirements.txt           # Dependencies for Lambda container
├── pyproject.toml             # uv project configuration
└── README.md
```

## How It Works

### Local Agent (`strands_claude.py`)

```python
from strands import Agent, tool
from strands.models import BedrockModel

@tool
def weather():
    """ Get weather """
    return "sunny"

agent = Agent(
    model=BedrockModel(model_id="global.anthropic.claude-haiku-4-5-20251001-v1:0"),
    tools=[calculator, weather],
    system_prompt="You're a helpful assistant..."
)

response = agent("What is the weather?")
```

### Cloud Agent (`strands_claude_runtime.py`)

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

@app.entrypoint
def strands_agent_bedrock(payload):
    user_input = payload.get("prompt")
    response = agent(user_input)
    return response.message['content'][0]['text']

if __name__ == "__main__":
    app.run()
```

## Known Issues

### Dockerfile Permissions Bug

The `bedrock-agentcore-starter-toolkit` generates a Dockerfile with a permissions issue. The `COPY . .` command runs after switching to a non-root user, causing permission denied errors.

**Fix:** The `redeploy.py` script patches the Dockerfile after `configure()`:

```python
dockerfile = dockerfile.replace(
    "COPY . .",
    "COPY --chown=bedrock_agentcore:bedrock_agentcore . ."
)
```

## Resources

- [Amazon Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [Strands Agents](https://github.com/strands-agents/strands-agents)
- [AgentCore Samples Repository](https://github.com/awslabs/amazon-bedrock-agentcore-samples)
