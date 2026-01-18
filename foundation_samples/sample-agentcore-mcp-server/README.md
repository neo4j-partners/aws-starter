# Sample 2: MCP Server on AgentCore (CDK)

Deploy an MCP (Model Context Protocol) server to Amazon Bedrock AgentCore Runtime using AWS CDK.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (for local builds)
- Node.js (for CDK CLI)
- AWS CDK CLI (`npm install -g aws-cdk`)
- AWS credentials configured
- Bedrock AgentCore access enabled

## Quick Start

```bash
# Install dependencies
uv sync

# Bootstrap CDK (first time only)
uv run cdk bootstrap

# Deploy to AgentCore Runtime
uv run cdk deploy

# Test the MCP server
uv run python test_mcp_server.py

# Clean up
uv run cdk destroy
```

## Architecture

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                                  AWS Cloud                                     │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │                      Amazon Bedrock AgentCore                             │ │
│  │                                                                           │ │
│  │   ┌─────────────────────┐         ┌────────────────────────────────────┐ │ │
│  │   │    MCP Runtime      │         │       Your MCP Container           │ │ │
│  │   │    (Managed)        │         │                                    │ │ │
│  │   │                     │  HTTP   │   ┌────────────────────────────┐  │ │ │
│  │   │  ┌───────────────┐  │ ──────▶ │   │     FastMCP Server         │  │ │ │
│  │   │  │ Load Balancer │  │  :8000  │   │                            │  │ │ │
│  │   │  └───────────────┘  │         │   │  @mcp.tool()               │  │ │ │
│  │   │                     │         │   │  ├── add_numbers(a, b)     │  │ │ │
│  │   │  ┌───────────────┐  │         │   │  ├── multiply_numbers(a,b) │  │ │ │
│  │   │  │ Auto Scaling  │  │         │   │  ├── greet_user(name)      │  │ │ │
│  │   │  └───────────────┘  │         │   │  └── get_server_info()     │  │ │ │
│  │   │                     │         │   │                            │  │ │ │
│  │   │  ┌───────────────┐  │         │   │  stateless_http=True       │  │ │ │
│  │   │  │ Health Checks │  │         │   └────────────────────────────┘  │ │ │
│  │   │  └───────────────┘  │         │                                    │ │ │
│  │   └─────────────────────┘         └────────────────────────────────────┘ │ │
│  │              ▲                                                            │ │
│  │              │ JWT Validation                                             │ │
│  │   ┌──────────┴──────────┐                                                │ │
│  │   │   Amazon Cognito    │                                                │ │
│  │   │    User Pool        │                                                │ │
│  │   │                     │                                                │ │
│  │   │  • testuser         │                                                │ │
│  │   │  • JWT tokens       │                                                │ │
│  │   │  • OIDC discovery   │                                                │ │
│  │   └─────────────────────┘                                                │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │                          Amazon ECR                                       │ │
│  │                   (Container Image Storage)                               │ │
│  │                                                                           │ │
│  │   ┌─────────────────────────────────────────────────────────────────┐    │ │
│  │   │  cdk-hnb659fds-container-assets-ACCOUNT-REGION                  │    │ │
│  │   │                                                                  │    │ │
│  │   │  mcp-server:latest (ARM64)                                      │    │ │
│  │   └─────────────────────────────────────────────────────────────────┘    │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │                       CloudWatch Logs                                     │ │
│  │        /aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT              │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────┘

                              MCP Client
                         ┌─────────────────┐
                         │  test_mcp.py    │
                         │                 │
                         │ 1. Get JWT      │
                         │    from Cognito │
                         │                 │
                         │ 2. Connect to   │
                         │    MCP Runtime  │
                         │                 │
                         │ 3. Call tools   │
                         │    via MCP      │
                         │    protocol     │
                         └─────────────────┘


    CDK Deployment Flow
    ═══════════════════

    ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
    │  Local Docker   │      │   Push to ECR   │      │ Create Runtime  │
    │  Build (ARM64)  │ ───▶ │   (~20 sec)     │ ───▶ │ + Cognito       │
    │  (~20 sec)      │      │                 │      │ (~30 sec)       │
    └─────────────────┘      └─────────────────┘      └─────────────────┘

    Total deployment time: ~1 minute (vs ~10 minutes with CodeBuild)
```

## Project Structure

```
sample_two/
├── app.py                    # CDK App entry point
├── sample_two_stack.py       # Main CDK stack
├── cdk.json                  # CDK configuration
├── pyproject.toml            # Dependencies (uv)
├── test_mcp_server.py        # MCP protocol test client
├── get_token.py              # Cognito JWT token helper
├── infra_utils/
│   ├── __init__.py
│   └── agentcore_role.py     # Reusable IAM role construct
└── mcp-server/
    ├── mcp_server.py         # MCP server with FastMCP
    ├── Dockerfile            # Container image (ARM64)
    └── requirements.txt      # Runtime dependencies
```

## How It Works

1. **CDK builds the Docker image locally** (ARM64 architecture)
2. **Image is pushed to CDK's bootstrap ECR repository**
3. **Cognito User Pool is created** with a test user for JWT authentication
4. **AgentCore Runtime is created** with MCP protocol and JWT authorizer
5. **MCP clients authenticate** via Cognito and connect using the MCP protocol

**Key benefit**: Local Docker builds are much faster than CodeBuild (~1 min vs ~10 min total deployment).

## Available MCP Tools

| Tool | Description | Example |
|------|-------------|---------|
| `add_numbers` | Add two integers | `{"a": 5, "b": 3}` → `8` |
| `multiply_numbers` | Multiply two integers | `{"a": 4, "b": 7}` → `28` |
| `greet_user` | Greet a user by name | `{"name": "Alice"}` → `"Hello, Alice! Welcome to AgentCore."` |
| `get_server_info` | Get server metadata | `{}` → `{"name": "Sample MCP Server", ...}` |

## Stack Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| AgentName | MCPServer | Name for the MCP server runtime |
| NetworkMode | PUBLIC | PUBLIC or PRIVATE |

## Stack Outputs

| Output | Description |
|--------|-------------|
| MCPServerRuntimeId | ID of the MCP server runtime |
| MCPServerRuntimeArn | ARN for connecting to the server |
| AgentRoleArn | ARN of the IAM execution role |
| ImageUri | URI of the Docker image in ECR |
| CognitoUserPoolId | Cognito User Pool ID |
| CognitoClientId | Cognito Client ID for authentication |
| TestUsername | Test user: `testuser` |
| TestPassword | Test password: `TestPassword123!` |
| GetTokenCommand | Ready-to-run command for token retrieval |

## Testing

### Automated test (recommended)
```bash
uv run python test_mcp_server.py
```

This script automatically:
1. Gets stack outputs from CloudFormation
2. Authenticates with Cognito to get a JWT token
3. Connects to the MCP server using the MCP protocol
4. Lists available tools and tests each one

### Manual token retrieval
```bash
# Get the client ID from stack outputs
CLIENT_ID=$(aws cloudformation describe-stacks \
  --stack-name SampleTwoMCPServer \
  --query "Stacks[0].Outputs[?OutputKey=='CognitoClientId'].OutputValue" \
  --output text)

# Get token
uv run python get_token.py $CLIENT_ID testuser TestPassword123!

# Export token for use with curl
export JWT_TOKEN="<token>"
```

## Best Practices

### MCP Server Best Practices

1. **Stateless HTTP**: Always use `stateless_http=True` - AgentCore manages sessions:
   ```python
   mcp = FastMCP(host="0.0.0.0", stateless_http=True)
   ```

2. **Port 8000**: MCP servers must listen on port 8000 (AgentCore default).

3. **Tool Docstrings**: Write clear, concise docstrings - they become tool descriptions:
   ```python
   @mcp.tool()
   def add_numbers(a: int, b: int) -> int:
       """Add two numbers together."""
       return a + b
   ```

4. **Type Hints**: Always use type hints - they define the tool's input schema.

### Dockerfile Best Practices

1. **File Permissions**: Copy files before switching to non-root user, then set ownership:
   ```dockerfile
   COPY . .
   RUN useradd -m -u 1000 bedrock_agentcore && \
       chown -R bedrock_agentcore:bedrock_agentcore /app
   USER bedrock_agentcore
   ```

2. **ARM64 Architecture**: Always build for ARM64 (AgentCore requirement):
   ```python
   ecr_assets.DockerImageAsset(
       self, "Image",
       directory="./mcp-server",
       platform=ecr_assets.Platform.LINUX_ARM64,
   )
   ```

3. **Slim Base Images**: Use `python:3.11-slim` to reduce image size and startup time.

### CDK Best Practices

1. **Use CfnParameter** for configurable values
2. **Always output the Runtime ARN** for easy client connection
3. **Use reusable constructs** for IAM roles (see `infra_utils/agentcore_role.py`)

## Debugging Tips

### Test container locally
```bash
cd mcp-server
docker build -t test-mcp .
docker run --rm -p 8000:8000 test-mcp

# Container should start without errors
# You'll see "Uvicorn running on http://0.0.0.0:8000"
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Permission denied` on startup | Files owned by root | Add `chown` before `USER` in Dockerfile |
| `401 Unauthorized` | Invalid or expired JWT | Get a fresh token with `get_token.py` |
| Runtime stuck in CREATING | Container startup failure | Check CloudWatch logs |
| MCP connection timeout | Runtime not ready | Wait for ACTIVE status |

### Check runtime status
```bash
RUNTIME_ID=$(aws cloudformation describe-stacks \
  --stack-name SampleTwoMCPServer \
  --query "Stacks[0].Outputs[?OutputKey=='MCPServerRuntimeId'].OutputValue" \
  --output text)

aws bedrock-agentcore get-agent-runtime \
  --agent-runtime-id $RUNTIME_ID \
  --query 'status'
```

### View CloudWatch logs
```bash
aws logs tail /aws/bedrock-agentcore/runtimes/$RUNTIME_ID-DEFAULT --follow
```

## Lessons Learned

1. **File permissions are critical** - The most common container startup failure is files being unreadable by the non-root user.

2. **Local Docker testing saves time** - Always test containers locally before deploying to AgentCore.

3. **MCP uses streamable-http transport** - Not standard HTTP. Use the MCP client library.

4. **JWT tokens expire** - Cognito tokens have a 1-hour expiration. Get fresh tokens for testing.

5. **ARM64 is required** - AgentCore runs ARM64 containers. Local builds on Apple Silicon work natively.

6. **Port 8000 is hardcoded** - MCP servers must listen on port 8000, not configurable.

## Clean Up

```bash
# Destroy the CDK stack
uv run cdk destroy

# Remove local Docker images (optional)
docker rmi test-mcp
```

## Using LangGraph with MCP Servers

You can build AI agents that consume MCP servers using LangGraph and the `langchain-mcp-adapters` library. This enables natural language interaction with your MCP tools.

### Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   User Input    │────▶│  LangGraph Agent │────▶│   AgentCore     │
│  (Natural Lang) │     │  (ReAct Pattern) │     │    Runtime      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │                        │
                               │ MCP Protocol           │ JWT Auth
                               │ over HTTP              │
                               ▼                        ▼
                        ┌──────────────────┐     ┌─────────────────┐
                        │   langchain-mcp  │     │    MCP Server   │
                        │    -adapters     │     │   (Your Tools)  │
                        └──────────────────┘     └─────────────────┘
```

### Dependencies

```bash
pip install langgraph langchain-mcp-adapters langchain-aws boto3
```

### Example Agent

```python
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain_aws import ChatBedrockConverse

async def run_agent(question: str, mcp_url: str, jwt_token: str):
    # Initialize LLM (AWS Bedrock Claude)
    llm = ChatBedrockConverse(
        model="us.anthropic.claude-sonnet-4-20250514-v1:0",
        region_name="us-west-2",
        temperature=0,
    )

    # Connect to MCP server
    client = MultiServerMCPClient({
        "mcp_server": {
            "transport": "streamable_http",
            "url": mcp_url,
            "headers": {"Authorization": f"Bearer {jwt_token}"},
        }
    })

    # Load tools and create agent
    tools = await client.get_tools()
    agent = create_react_agent(llm, tools)

    # Run agent
    result = await agent.ainvoke({"messages": [("user", question)]})
    return result["messages"][-1].content

# Usage
asyncio.run(run_agent(
    "Add 5 and 3, then multiply by 2",
    "https://your-runtime.bedrock-agentcore.us-west-2.amazonaws.com/mcp",
    "eyJ..."  # JWT token
))
```

### Full Implementation Example

See the `neo4j-agentcore-mcp-server/agent/` directory for a complete working implementation including:
- Credential loading from `.mcp-credentials.json`
- Token expiry validation
- Error handling
- Shell wrapper script

```bash
# From neo4j-agentcore-mcp-server directory
./agent.sh "What is the database schema?"
```

### Key Considerations

1. **Authentication**: MCP servers on AgentCore require JWT authentication via Cognito
2. **Transport**: Use `streamable_http` transport for AgentCore MCP servers
3. **Tool Discovery**: `langchain-mcp-adapters` automatically discovers and converts MCP tools
4. **LLM Choice**: Use `ChatBedrockConverse` for best tool-calling compatibility with Bedrock

### References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/llms.txt)
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
- [LangGraph + MCP Integration Guide](https://neo4j.com/blog/developer/react-agent-langgraph-mcp/)

## Learn More

- [AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [FastMCP Python Library](https://github.com/jlowin/fastmcp)
- [AWS CDK Python Reference](https://docs.aws.amazon.com/cdk/api/v2/python/)
- [Amazon Cognito Developer Guide](https://docs.aws.amazon.com/cognito/)
