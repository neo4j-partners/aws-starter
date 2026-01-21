# Neo4j MCP LangGraph ReAct Agents

This project provides LangGraph ReAct agents that connect to a Neo4j MCP server via AWS Bedrock AgentCore Gateway.

---

## Minimal LangGraph Agent (SageMaker Studio)

A simple notebook to test LangGraph with Bedrock in **SageMaker Unified Studio**.

### Prerequisites

1. **Bedrock IDE Export**: Create any app in SageMaker Unified Studio → Bedrock IDE, then export it. This creates the `amazon-bedrock-ide-app-export-*` folder needed for auto-detection of DataZone IDs.

2. **AWS CLI Access**: Run the setup script from your local machine or CloudShell (not from within SageMaker Studio notebooks).

### Setup

```bash
# Create the inference profile (auto-detects DataZone IDs)
./setup-inference-profile.sh sonnet

# Output will show:
# ==============================================
#   COPY THIS TO YOUR NOTEBOOK
# ==============================================
#
# INFERENCE_PROFILE_ARN = "arn:aws:bedrock:us-west-2:YOUR_ACCOUNT:application-inference-profile/YOUR_ID"
#
# ==============================================
```

### Using the Notebook

1. Upload `minimal_langgraph_agent.ipynb` to SageMaker Studio
2. Paste the `INFERENCE_PROFILE_ARN` from the script output into the configuration cell
3. Run all cells

### Script Commands

| Command | Description |
|---------|-------------|
| `./setup-inference-profile.sh` | Create profile with Claude 3.5 Sonnet (default) |
| `./setup-inference-profile.sh haiku` | Create profile with Claude 3.5 Haiku |
| `./setup-inference-profile.sh sonnet4` | Create profile with Claude Sonnet 4 |
| `./setup-inference-profile.sh --list` | List existing profiles |
| `./setup-inference-profile.sh --delete` | Delete the lab profile |
| `./setup-inference-profile.sh --help` | Show help |

### How It Works

The script creates an **application inference profile** that:
- Copies from a cross-region inference profile (us.anthropic.claude-*)
- Tags it with your DataZone project and domain IDs (auto-detected from Bedrock IDE export)
- Enables the SageMaker Unified Studio permissions boundary to allow invocation

### Troubleshooting

**AccessDeniedException on InvokeModel**: The inference profile must be tagged with `AmazonDataZoneProject`. Run `./setup-inference-profile.sh --delete` then `./setup-inference-profile.sh sonnet` to recreate with proper tags.

**"Model identifier is invalid"**: Make sure you're using the full ARN from the script output, not a model ID.

**Can't auto-detect DataZone IDs**: Export an app from Bedrock IDE first. The script looks for `amazon-bedrock-ide-app-export-*` folders.

### Files

| File | Description |
|------|-------------|
| `minimal_langgraph_agent.ipynb` | Jupyter notebook for SageMaker Studio |
| `minimal_agent.py` | Python script version (for local testing) |
| `setup-inference-profile.sh` | Creates Bedrock inference profiles |
| `IAM-SETUP.md` | Detailed IAM permissions documentation |

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
