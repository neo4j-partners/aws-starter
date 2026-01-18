# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains AWS Lambda and Bedrock AgentCore learning samples. There are two main components:

1. **Lambda Function URL Starter** - A uv-based Python template for deploying Lambda functions with public HTTP endpoints
2. **Bedrock AgentCore Samples** - Progressive hands-on samples for learning Amazon Bedrock AgentCore features

## Common Commands

### Lambda Deployment (happy-new-year)

```bash
cd happy-new-year
./deploy-lambda.sh              # Deploy Lambda
./deploy-lambda.sh --delete     # Delete function only (keeps IAM role)
./deploy-lambda.sh --delete-all # Delete function and IAM role
AWS_REGION=eu-west-1 ./deploy-lambda.sh  # Deploy to specific region
```

### Sample 1: AgentCore Runtime Quick Start

```bash
cd sample_1
./agent.sh setup         # Install dependencies
./agent.sh start         # Start local agent (port 8080)
./agent.sh test          # Run test suite
./agent.sh invoke "prompt"  # Send prompt to local agent
./agent.sh stop          # Stop local agent
./agent.sh deploy        # Deploy to AgentCore Runtime
./agent.sh invoke-cloud "prompt"  # Send prompt to deployed agent
./agent.sh destroy       # Remove from AgentCore
```

### Sample 2: MCP Server on AgentCore (CloudFormation)

```bash
cd foundation_samples/sample-agentcore-mcp-server

# Local Development
./server.sh start        # Start local MCP server (port 8000)
./server.sh stop         # Stop local server
./client.sh test         # Test local server
./client.sh tools        # List available tools
./client.sh call add_numbers '{"a": 5, "b": 3}'

# Cloud Deployment (CloudFormation)
./deploy.sh              # Deploy CloudFormation stack (~15 min)
./deploy.sh my-stack us-west-2  # Custom stack name and region
./test.sh                # Test deployed MCP server
./cleanup.sh             # Delete all AWS resources
```

### Sample 3: AgentCore Gateway

```bash
cd sample_three
./manage.sh setup        # Deploy Lambda + Gateway
./manage.sh test         # Run tests
./manage.sh run          # Interactive agent session
./manage.sh cleanup      # Remove all AWS resources
```

### Sample 4: AgentCore Memory

```bash
cd sample_four
./manage.sh status       # Verify AWS setup
./manage.sh run          # Execute memory demo
./manage.sh list         # List all memories
./manage.sh clean        # Delete demo memories
```

### Dependency Management (uv)

```bash
uv sync                  # Install dependencies
uv add <package>         # Add a dependency
uv add --dev <package>   # Add dev dependency
uv run python script.py  # Run script in venv
uv export --frozen --no-dev -o requirements.txt  # Export for Lambda
```

## Architecture

### Lambda Projects

Each Lambda project follows this structure:
- `src/handler.py` - Lambda handler with `handler(event, context)` function
- `pyproject.toml` - uv project configuration
- `.python-version` - Pins Python version (3.12 for Lambda compatibility)

The deploy script handles cross-platform builds using `--platform manylinux2014_x86_64` for macOS to Linux compatibility.

### AgentCore Samples Structure

Each sample has a lifecycle management shell script (agent.sh, server.sh, manage.sh) that wraps the AgentCore CLI commands.

| Sample | Focus | Key Pattern |
|--------|-------|-------------|
| sample_1 | Runtime Quick Start | `@app.entrypoint` decorator pattern with Strands Agents |
| sample_two | MCP Server (CloudFormation) | FastMCP + CloudFormation IaC deployment |
| sample_three | Gateway | Lambda functions as MCP tools via Gateway |
| sample_four | Memory | Session memory + episodic memory with strategies |

### AgentCore Runtime Requirements

- Architecture: arm64 (aarch64) - starter toolkit handles this automatically
- Python: 3.10-3.13 supported
- Port: 8080 for local development
- All MCP servers must be stateless (`stateless_http=True`)

## Key Patterns

### AgentCore App Pattern (sample_1)
```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
app = BedrockAgentCoreApp()

@app.entrypoint
async def invoke(payload: dict) -> dict:
    # Handler receives requests, returns JSON-serializable response
    pass

app.run(port=8080)
```

### MCP Server Pattern (sample_two)
```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP(host="0.0.0.0", stateless_http=True)

@mcp.tool()
def my_tool(param: str) -> str:
    pass

mcp.run(transport="streamable-http")
```

### Memory Naming Convention
Memory names must match pattern `[a-zA-Z][a-zA-Z0-9_]{0,47}` (letters, numbers, underscores only).

## AWS Requirements

- AWS CLI v2.31.13+ (for AgentCore commands)
- Bedrock model access enabled (Claude Sonnet)
- IAM permissions for bedrock-agentcore actions
- Default region: us-east-1 for AgentCore, configurable via AWS_REGION

## Resources

- AgentCore Documentation: https://docs.aws.amazon.com/bedrock-agentcore/
- AgentCore Samples: https://github.com/awslabs/amazon-bedrock-agentcore-samples
- uv Package Manager: https://docs.astral.sh/uv/
- MCP Protocol: https://modelcontextprotocol.io/
