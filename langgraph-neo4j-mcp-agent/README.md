# Neo4j MCP LangGraph ReAct Agents

This project provides LangGraph ReAct agents that connect to a Neo4j MCP server via AWS Bedrock AgentCore Gateway.

---

## Minimal LangGraph Agent (SageMaker Unified Studio)

A simple notebook to test LangGraph with Bedrock in **SageMaker Unified Studio**.

### Quick Start

#### Step 1: Create an Inference Profile (One-Time Setup)

Run this from CLI/CloudShell (**not** inside a notebook):

```bash
cd langgraph-neo4j-mcp-agent

# See available options
./setup-inference-profile.sh --help

# Create a profile (choose one):
./setup-inference-profile.sh haiku      # Fast & cheap - great for testing
./setup-inference-profile.sh sonnet     # Balanced - recommended for production
./setup-inference-profile.sh sonnet4    # Latest Claude Sonnet 4
./setup-inference-profile.sh --all      # Create ALL model profiles

# Create and test in one step:
./setup-inference-profile.sh --test haiku
```

#### Step 2: Copy the ARN to Your Notebook

The script will output something like:
```
╔════════════════════════════════════════════════════════════╗
║              COPY THIS TO YOUR NOTEBOOK                    ║
╚════════════════════════════════════════════════════════════╝

INFERENCE_PROFILE_ARN = "arn:aws:bedrock:us-west-2:123456789:application-inference-profile/abc123"
```

#### Step 3: Paste into Notebook

Open `minimal_langgraph_agent.ipynb` and paste the ARN in the configuration cell:

```python
#################################################
# CONFIGURATION - Paste your inference profile ARN
#################################################

INFERENCE_PROFILE_ARN = "PASTE_YOUR_ARN_HERE"
REGION = "us-west-2"

#################################################
```

### Script Commands Reference

```bash
# Interactive menu
./setup-inference-profile.sh

# Create specific model profile
./setup-inference-profile.sh haiku
./setup-inference-profile.sh sonnet
./setup-inference-profile.sh sonnet4
./setup-inference-profile.sh sonnet45

# Create and test profile
./setup-inference-profile.sh --test haiku

# Create all model profiles at once
./setup-inference-profile.sh --all

# List existing profiles (shows which have the magic tag)
./setup-inference-profile.sh --list

# Delete profiles
./setup-inference-profile.sh --delete haiku
./setup-inference-profile.sh --delete-all

# Show detected DataZone IDs
./setup-inference-profile.sh --detect
```

### Available Models

| Model | Command | Description |
|-------|---------|-------------|
| Claude 3.5 Haiku | `./setup-inference-profile.sh haiku` | Fast & cheap - great for testing |
| Claude 3.5 Sonnet v2 | `./setup-inference-profile.sh sonnet` | Balanced - **recommended** |
| Claude Sonnet 4 | `./setup-inference-profile.sh sonnet4` | Latest version |
| Claude Sonnet 4.5 | `./setup-inference-profile.sh sonnet45` | Most capable |

### Files

| File | Description |
|------|-------------|
| `minimal_langgraph_agent.ipynb` | Jupyter notebook for SageMaker Studio |
| `test_models.ipynb` | Testing notebook for model configuration |
| `setup-inference-profile.sh` | **CLI tool to create working inference profiles** |
| `MODEL.md` | Detailed explanation of the secret sauce |

### Prerequisites

Before running the script, you need a **Bedrock IDE export** in the parent directory. This provides the DataZone IDs needed for the magic tag.

1. Go to SageMaker Unified Studio → **Build** → **Bedrock IDE**
2. Create any app (agent, chat, etc.)
3. Export the app (this creates `amazon-bedrock-ide-app-export-*` folder)

The script auto-detects these IDs from the export.

---

## Neo4j MCP Agents

The full-featured agents connect to a Neo4j MCP server via AWS Bedrock AgentCore Gateway and answer natural language questions using Claude. The **simple agent** is a minimal implementation for testing and learning, while the **production agent** adds automatic OAuth2 token refresh for long-running deployments.

## Quick Setup

```bash
# Install dependencies
./agent.sh setup

# Copy credentials from neo4j-agentcore-mcp-server deployment
cp ../neo4j-agentcore-mcp-server/.mcp-credentials.json .
```

## Simple Agent

**File:** `simple-agent.py`

The simple agent is a minimal implementation designed for quick testing and learning. It reads the `access_token` directly from the credentials file and uses it as a static bearer token for all requests to the AgentCore Gateway.

**Key characteristics:**
- Uses a pre-generated access token from `.mcp-credentials.json`
- No automatic token refresh - when the token expires (typically after 1 hour), the agent stops working
- Simpler codebase with fewer dependencies
- Ideal for local development, demos, and understanding the core agent flow

**When to use:** Quick tests, learning the agent architecture, or short-lived sessions where token expiration is not a concern.

```bash
uv run python simple-agent.py                      # Run demo
uv run python simple-agent.py "What is the schema?"
```

## Production Agent

**File:** `agent.py`

The production agent is a robust implementation suitable for long-running applications and production deployments. It implements the OAuth2 client credentials flow to automatically refresh access tokens before they expire.

**Key characteristics:**
- Automatically refreshes tokens using OAuth2 client credentials grant
- Proactively refreshes tokens that are about to expire (within 5 minutes of expiry)
- Handles token refresh failures gracefully with clear error messages
- Production-ready with proper credential management
- Uses `httpx` for async HTTP requests to the Cognito token endpoint

**When to use:** Production deployments, long-running sessions, automated pipelines, or any scenario where the agent needs to run for more than an hour without interruption.

```bash
./agent.sh                      # Run demo
./agent.sh "What is the schema?"
```

### Production Agent Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   User Input    │────▶│  LangGraph Agent │────▶│   AgentCore     │
│  (Natural Lang) │     │  (ReAct Pattern) │     │    Gateway      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │                        │
                               │ MCP Protocol           │ OAuth2 JWT
                               │ over HTTP              │
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

The production agent adds a token management layer that intercepts requests and ensures a valid OAuth2 token is always available. When a token is expired or nearing expiration, the agent automatically requests a new one from Amazon Cognito using the client credentials stored in the credentials file.

### Token Refresh Flow

The production agent handles OAuth2 token lifecycle automatically. Here's how it works:

**1. Startup Check**

When the agent starts, it loads the credentials file and checks if the stored access token is still valid. The agent considers a token invalid if:
- No `token_expires_at` timestamp exists in the credentials file
- The current time is within 5 minutes of the expiry time (proactive refresh)

**2. Token Refresh Process**

If the token needs refreshing, the agent performs an OAuth2 client credentials grant:

1. Reads `token_url`, `client_id`, `client_secret`, and `scope` from `.mcp-credentials.json`
2. Sends an HTTP POST request to the Amazon Cognito token endpoint (`token_url`)
3. Includes the grant type (`client_credentials`), client ID, client secret, and scope in the request body
4. Receives a new access token and its TTL (typically 3600 seconds / 1 hour)
5. Calculates the new expiry timestamp and updates the credentials file
6. Uses the fresh token for all subsequent MCP server requests

**3. Credentials Used**

The agent uses **two separate sets of credentials** for different purposes:

| Credential Type | Source | Used For |
|-----------------|--------|----------|
| **OAuth2 Client Credentials** | `.mcp-credentials.json` | Authenticating with AgentCore Gateway via Cognito |
| **AWS Credentials** | AWS CLI profile or environment variables | Calling AWS Bedrock for Claude LLM inference |

**OAuth2 credentials** (`client_id`, `client_secret`) are specific to the AgentCore Gateway deployment. They are generated when you deploy the `neo4j-agentcore-mcp-server` and authorize access to the MCP server. These credentials authenticate requests to the gateway's Cognito user pool.

**AWS credentials** are your standard AWS access credentials (access key ID and secret access key, or IAM role). These authenticate requests to AWS Bedrock's Converse API for Claude inference. The agent uses whichever credentials are configured in your environment:
- `AWS_PROFILE` environment variable (named profile)
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables
- Default AWS CLI profile
- IAM instance role (when running on EC2/Lambda)

**4. Token Storage**

After a successful refresh, the agent writes the new token back to `.mcp-credentials.json`:
- `access_token` - The new bearer token
- `token_expires_at` - ISO 8601 timestamp of when the token expires

This means subsequent agent runs within the token's validity period can skip the refresh step entirely.

### Key Differences

| Aspect | Simple Agent | Production Agent |
|--------|--------------|------------------|
| Token handling | Static bearer token | Auto-refreshing OAuth2 |
| Session duration | Limited to token TTL (~1 hour) | Unlimited |
| Complexity | Minimal | More complex |
| Dependencies | Fewer | Includes `httpx` for token refresh |
| Use case | Testing/learning | Production deployments |

## Configuration

### Credentials File

Copy `.mcp-credentials.json` from your `neo4j-agentcore-mcp-server` deployment:

```bash
cp ../neo4j-agentcore-mcp-server/.mcp-credentials.json .
```

Required fields:

| Field | Description |
|-------|-------------|
| `gateway_url` | AgentCore Gateway endpoint URL |
| `token_url` | Cognito token endpoint for OAuth2 |
| `client_id` | OAuth2 client ID |
| `client_secret` | OAuth2 client secret |
| `scope` | OAuth2 scope for MCP invocation |
| `region` | AWS region for Bedrock access |

The agent automatically refreshes tokens when they expire using the client credentials flow.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_CREDENTIALS_FILE` | Path to credentials file | `.mcp-credentials.json` |
| `AWS_REGION` | AWS region (overrides credentials) | From credentials |
| `AWS_PROFILE` | AWS CLI profile to use | default |

## Commands

| Command | Description |
|---------|-------------|
| `./agent.sh` | Run demo queries |
| `./agent.sh "<question>"` | Ask a question |
| `./agent.sh setup` | Install dependencies |
| `./agent.sh help` | Show help |

## Example Questions (Aircraft Maintenance Database)

```bash
./agent.sh "What is the database schema?"
./agent.sh "How many aircraft are in the database?"
./agent.sh "Show aircraft with recent maintenance events"
./agent.sh "What sensors monitor the engines?"
./agent.sh "Find components needing attention"
./agent.sh "List 5 airports with their city and country"
./agent.sh "Show me 3 recent maintenance events with their severity"
```

## Example Output

```
======================================================================
Neo4j MCP Agent
======================================================================

Loading credentials...
Refreshing OAuth2 token...
Token refreshed. New expiry: 2026-01-06T21:10:25.158870+00:00

Gateway: https://your-gateway.amazonaws.com/mcp
Token expires: 2026-01-06T21:10:25.158870+00:00

Initializing LLM (Bedrock, region: us-west-2)...
Using: us.anthropic.claude-sonnet-4-20250514-v1:0

Connecting to MCP server...
Loaded 2 tools:
  - neo4j-mcp-server-target___get-schema
  - neo4j-mcp-server-target___read-cypher

Creating agent...
======================================================================
Question: How many Aircraft are in the database?
======================================================================

Answer:
----------------------------------------------------------------------
There are **60 Aircraft** in the database.
----------------------------------------------------------------------
```

## Gateway Tool Naming

When tools are accessed via AgentCore Gateway, they include a target prefix:

```
{target-name}___{tool-name}
```

For example: `neo4j-mcp-server-target___get-schema`

The `langchain-mcp-adapters` library handles this automatically - the LLM sees the full prefixed names and uses them correctly.

## Prerequisites

1. **Python 3.10+** - Required runtime
2. **uv** - Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
3. **AWS CLI** - Configured with credentials that have Bedrock access
4. **Deployed Neo4j MCP Server** - `neo4j-agentcore-mcp-server` with AgentCore Gateway

## How It Works

1. **Load Credentials**: Reads gateway URL and OAuth2 credentials from `.mcp-credentials.json`
2. **Auto-Refresh Token**: If token is expired or expiring soon, refreshes using client credentials
3. **Initialize LLM**: Creates AWS Bedrock Claude client via Converse API
4. **Connect to MCP**: Uses `MultiServerMCPClient` with streamable HTTP transport
5. **Load Tools**: Discovers and converts MCP tools to LangChain format
6. **Create Agent**: Builds ReAct agent with system prompt for database queries
7. **Process Query**: Agent reasons, calls tools, and returns formatted answer

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

### Connection Failed
```
httpx.ConnectError
```
Verify the gateway URL is correct and the MCP server is deployed.

## Dependencies

```toml
[project]
dependencies = [
    "langgraph>=0.2.0",
    "langchain-mcp-adapters>=0.1.0",
    "langchain-aws>=0.2.0",
    "httpx>=0.27.0",
    "boto3>=1.35.0",
]
```

## References

- [neo4j-agentcore-mcp-server](../neo4j-agentcore-mcp-server/) - The MCP server this agent connects to
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [AWS Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html)

---

## Appendix: Why the Script Works (The Secret Sauce)

### The Problem

SageMaker Unified Studio has a **permissions boundary** (`SageMakerStudioProjectUserRolePermissionsBoundary`) that blocks direct Bedrock model access:

```
AccessDeniedException: User is not authorized to perform: bedrock:InvokeModel
on resource: arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-*
```

**What doesn't work in SageMaker Unified Studio:**
- Direct model IDs (`anthropic.claude-3-5-sonnet-20241022-v2:0`)
- Cross-region profiles (`us.anthropic.claude-3-5-sonnet-20241022-v2:0`)
- CLI-created inference profiles without the magic tag

### The Discovery

After extensive testing, we discovered the **one critical tag** that makes CLI-created inference profiles work:

```
AmazonBedrockManaged = true
```

### Why This Tag Works

The SageMaker permissions boundary policy likely has a condition like:

```json
{
  "Condition": {
    "StringEquals": {
      "aws:ResourceTag/AmazonBedrockManaged": "true"
    }
  }
}
```

This means only resources **tagged as managed by Bedrock** are allowed through the permissions boundary.

### What the Script Does

The `setup-inference-profile.sh` script creates inference profiles with all the required elements:

1. **Correct Naming Pattern**: `{domain_id} {project_id} {model}`
   - Matches the pattern used by Bedrock IDE

2. **Required Tags**:
   ```
   AmazonBedrockManaged = true      ← THE KEY!
   AmazonDataZoneProject = {project_id}
   AmazonDataZoneDomain = {domain_id}
   ```

3. **Auto-Detection**: Extracts the correct DataZone IDs from Bedrock IDE exports
   - Project ID comes from `bedrockServiceRoleArn` (not `exportProjectId`!)
   - Domain ID comes from the `dzd-*` pattern

### Comparison: Before vs After

| Profile Type | Has `AmazonBedrockManaged=true` | Works in Studio? |
|--------------|--------------------------------|------------------|
| Bedrock IDE created | ✅ Yes (automatic) | ✅ Yes |
| Old CLI-created | ❌ No | ❌ No |
| **Script-created** | ✅ Yes | ✅ **Yes!** |

### Verifying Your Profiles

Use the `--list` command to see which profiles have the magic tag:

```bash
./setup-inference-profile.sh --list
```

Output shows:
```
Profiles with AmazonBedrockManaged=true:
  ✓ dzd-xxx yyy haiku        ← Will work
  ✓ dzd-xxx yyy sonnet       ← Will work
  ✗ langgraph-lab            ← Won't work (missing tag)
```

### The Notebook Configuration

In your notebook, use the ARN with the `provider` parameter:

```python
from langchain_aws import ChatBedrockConverse

INFERENCE_PROFILE_ARN = "arn:aws:bedrock:us-west-2:ACCOUNT:application-inference-profile/ID"
REGION = "us-west-2"

llm = ChatBedrockConverse(
    model=INFERENCE_PROFILE_ARN,
    provider="anthropic",  # REQUIRED when using ARN!
    region_name=REGION,
    temperature=0,
)
```

**Important**: The `provider="anthropic"` parameter is **required** when using an ARN. Without it, you'll get errors.

### For More Details

See [MODEL.md](MODEL.md) for the full investigation history and troubleshooting guide.
