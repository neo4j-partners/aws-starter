# Neo4j MCP Agent - AgentCore Runtime

A ReAct agent that connects to the Neo4j MCP server via AWS Bedrock AgentCore Gateway and answers natural language questions using Claude. Deployed on Amazon Bedrock AgentCore Runtime.

## Quick Start

```bash
# 1. Install dependencies
./agent.sh setup

# 2. Copy credentials from Neo4j MCP server deployment
cp ../neo4j-agentcore-mcp-server/.mcp-credentials.json .

# 3. Test locally
./agent.sh start                    # Start server on port 8080
./agent.sh test                     # Test with curl (in another terminal)

# 4. Deploy to AgentCore Runtime
./agent.sh configure                # Configure AWS deployment
./agent.sh deploy                   # Deploy to cloud

# 5. Test deployed agent
./agent.sh invoke-cloud "What is the database schema?"

# 6. Cleanup when done
./agent.sh destroy
```

## Prerequisites

1. **Python 3.10+** and **uv** package manager
2. **AWS CLI** configured with credentials
3. **Bedrock Claude Sonnet model access** enabled in AWS console
4. **Deployed Neo4j MCP Server** with AgentCore Gateway (`.mcp-credentials.json`)

## Commands

| Command | Description |
|---------|-------------|
| `./agent.sh setup` | Install dependencies |
| `./agent.sh start` | Start agent locally (port 8080) |
| `./agent.sh stop` | Stop local agent |
| `./agent.sh test` | Test local agent with curl |
| `./agent.sh configure` | Configure for AWS deployment |
| `./agent.sh deploy` | Deploy to AgentCore Runtime |
| `./agent.sh status` | Check deployment status |
| `./agent.sh invoke-cloud "prompt"` | Invoke deployed agent |
| `./agent.sh destroy` | Remove from AgentCore |
| `./agent.sh help` | Show help |

## Step-by-Step Deployment Guide

### Step 1: Setup

Install dependencies using uv:

```bash
./agent.sh setup
```

### Step 2: Configure Credentials

Copy the credentials file from your Neo4j MCP server deployment:

```bash
cp ../neo4j-agentcore-mcp-server/.mcp-credentials.json .
```

Required fields in `.mcp-credentials.json`:

| Field | Description |
|-------|-------------|
| `gateway_url` | AgentCore Gateway endpoint URL |
| `token_url` | Cognito token endpoint for OAuth2 |
| `client_id` | OAuth2 client ID |
| `client_secret` | OAuth2 client secret |
| `scope` | OAuth2 scope for MCP invocation |
| `region` | AWS region for Bedrock access |

### Step 3: Test Locally

Start the agent locally on port 8080:

```bash
./agent.sh start
```

In another terminal, test with curl:

```bash
./agent.sh test

# Or manually:
curl -X POST http://localhost:8080/invocations \
    -H "Content-Type: application/json" \
    -d '{"prompt": "What is the database schema?"}'
```

Stop with Ctrl+C.

### Step 4: Configure for AWS Deployment

Run the AgentCore configure command:

```bash
./agent.sh configure
```

This creates `.bedrock_agentcore.yaml` with your deployment configuration.

For a specific region:

```bash
uv run agentcore configure -e agent.py -r us-east-1
```

### Step 5: Deploy to AgentCore Runtime

Deploy the agent to AWS:

```bash
./agent.sh deploy
```

This may take several minutes. Note the agent ARN from the output.

Check deployment status:

```bash
./agent.sh status
```

### Step 6: Test Deployed Agent

Invoke the deployed agent using the CLI:

```bash
./agent.sh invoke-cloud "What is the database schema?"
./agent.sh invoke-cloud "How many aircraft are in the database?"
```

### Step 7: Invoke Your Agent Programmatically

Use the `invoke_agent.py` script to call the deployed agent from Python:

```bash
python invoke_agent.py "What is the database schema?"
```

Or use the boto3 API directly:

```python
import json
import uuid
import boto3

agent_arn = "<your-agent-arn>"
prompt = "What is the database schema?"

client = boto3.client("bedrock-agentcore")
payload = json.dumps({"prompt": prompt}).encode()

response = client.invoke_agent_runtime(
    agentRuntimeArn=agent_arn,
    runtimeSessionId=str(uuid.uuid4()),
    payload=payload,
    qualifier="DEFAULT",
)

content = []
for chunk in response.get("response", []):
    content.append(chunk.decode("utf-8"))
print(json.loads("".join(content)))
```

### Step 8: Cleanup

Remove the agent from AgentCore Runtime:

```bash
./agent.sh destroy
```

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   User Input    │────▶│  BedrockAgentCore│────▶│   AgentCore     │
│  (via API)      │     │      App         │     │    Gateway      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │                        │
                               │ LangChain              │ OAuth2 JWT
                               │ ReAct Agent            │
                               ▼                        ▼
                        ┌──────────────────┐     ┌─────────────────┐
                        │   langchain-mcp  │     │   Neo4j MCP     │
                        │    -adapters     │     │    Server       │
                        └──────────────────┘     └─────────────────┘
                               │
                               │ AWS Bedrock
                               ▼
                        ┌──────────────────┐
                        │  Claude Sonnet 4 │
                        │  (Converse API)  │
                        └──────────────────┘
```

## Example Questions

```bash
./agent.sh invoke-cloud "What is the database schema?"
./agent.sh invoke-cloud "How many aircraft are in the database?"
./agent.sh invoke-cloud "Show aircraft with recent maintenance events"
./agent.sh invoke-cloud "What sensors monitor the engines?"
./agent.sh invoke-cloud "Find components needing attention"
./agent.sh invoke-cloud "List 5 airports with their city and country"
```

## Files

| File | Description |
|------|-------------|
| `agent.py` | Main agent with BedrockAgentCoreApp |
| `agent.sh` | CLI wrapper for all commands |
| `invoke_agent.py` | Programmatic invocation example |
| `simple-agent.py` | Simplified agent for local testing |
| `pyproject.toml` | Dependencies (uv) |
| `.mcp-credentials.json` | Gateway credentials (not committed) |
| `.bedrock_agentcore.yaml` | AgentCore config (created by configure) |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MODEL_ID` | Bedrock model ID | `us.anthropic.claude-sonnet-4-20250514-v1:0` |
| `AWS_REGION` | AWS region | `us-west-2` |

## Troubleshooting

### Token Refresh Failed
```
ERROR: Token refresh failed: 401
```
Check that `client_id` and `client_secret` in `.mcp-credentials.json` are correct.

### AWS Credentials Not Found
```
botocore.exceptions.NoCredentialsError
```
Configure AWS CLI: `aws configure` or set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.

### Bedrock Access Denied
```
AccessDeniedException: You don't have access to the model
```
Enable Claude Sonnet 4 model access in your AWS Bedrock console.

### Port 8080 Already in Use
```
{"timestamp":"...","status":404,"error":"Not Found","path":"/invocations"}
```
If you get a 404 error or unexpected response format (especially JSON with "timestamp" field), another service may be running on port 8080.

Check what's using the port:
```bash
lsof -i :8080
```

Kill conflicting processes:
```bash
# Kill by PID (replace 12345 with actual PID from lsof output)
kill 12345

# Or kill all processes on port 8080
lsof -ti :8080 | xargs kill
```

Then restart the agent with `./agent.sh start`.

### Deployment Failed
```
agentcore deploy failed
```
Check `./agent.sh status` for details. Ensure you have proper IAM permissions for bedrock-agentcore actions.

## Observability & Monitoring

### CloudWatch Logs

Agent logs are automatically stored in CloudWatch Logs. After deployment, find your logs at:

```
/aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT
```

**View logs via CLI:**

```bash
# Get your agent runtime ID from status
./agent.sh status

# Tail logs (replace with your agent ID)
aws logs tail /aws/bedrock-agentcore/runtimes/<agent-id>-DEFAULT --follow

# View recent logs
aws logs tail /aws/bedrock-agentcore/runtimes/<agent-id>-DEFAULT --since 1h
```

### AWS Console

View agent resources in the AWS Management Console:

| Resource | Console Location |
|----------|------------------|
| Agent Logs | **CloudWatch** → Log groups → `/aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT` |
| Agent Runtime | **Bedrock AgentCore** → Runtimes |
| Memory Resources | **Bedrock AgentCore** → Memory |
| IAM Role | **IAM** → Roles → Search "BedrockAgentCore" |

### Enabling Transaction Search (Tracing)

For enhanced tracing and observability, enable CloudWatch Transaction Search before deploying:

1. Open the AWS Console
2. Navigate to **CloudWatch** → **Settings** → **Transaction Search**
3. Follow the [AgentCore Observability Setup Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/userguide/runtime-observability.html)

### CLI Commands for Monitoring

```bash
# Check deployment status and resource health
./agent.sh status

# Or directly with agentcore CLI
uv run agentcore status

# List all deployed agent runtimes
aws bedrock-agentcore-control list-agent-runtimes --region us-west-2

# Get details for a specific runtime
aws bedrock-agentcore-control get-agent-runtime \
    --agent-runtime-id <agent-id> \
    --region us-west-2
```

### Deployment Output

After running `./agent.sh deploy`, the output includes:
- **Agent ARN** - Full Amazon Resource Name for invoking the agent
- **CloudWatch Log Group** - Location for debugging and monitoring
- **Endpoint URL** - For direct API invocation

## References

- [AgentCore Runtime Quickstart](https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/quickstart.html)
- [Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [neo4j-agentcore-mcp-server](../neo4j-agentcore-mcp-server/) - The MCP server this agent connects to
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
- [Model Context Protocol](https://modelcontextprotocol.io/)
