# Neo4j MCP Agent - AgentCore Runtime

A ReAct agent that connects to the Neo4j MCP server via AWS Bedrock AgentCore Gateway and answers natural language questions using Claude. Deployed on Amazon Bedrock AgentCore Runtime.

## Prerequisites

1. **Python 3.10+** and **uv** package manager
2. **AWS CLI** configured with credentials
3. **Bedrock Claude Sonnet model access** enabled in AWS console
4. **Deployed Neo4j MCP Server** with AgentCore Gateway (`.mcp-credentials.json`)

## Step-by-Step Deployment Guide

### Step 1: Setup

Run the setup command to install all required dependencies:

```bash
./agent.sh setup
```

**What this does:** The `agent.sh` script uses the `uv` package manager to create a virtual environment and install all dependencies defined in `pyproject.toml`. These include:

- **bedrock-agentcore** and **bedrock-agentcore-starter-toolkit** - AWS libraries for deploying and running agents on AgentCore Runtime
- **langchain**, **langgraph**, and **langchain-aws** - The LangChain framework for building the ReAct agent pattern with AWS Bedrock integration
- **langchain-mcp-adapters** - Adapter library that converts MCP server tools into LangChain-compatible tools
- **httpx** - HTTP client used for OAuth2 token refresh with the Cognito token endpoint
- **boto3** - AWS SDK for Python, used to call the Bedrock Converse API

After setup completes, a `.venv` directory is created containing the isolated Python environment.

### Step 2: Configure Credentials

Copy the credentials file from your Neo4j MCP server deployment:

```bash
cp ../neo4j-agentcore-mcp-server/.mcp-credentials.json .
```

**What this does:** The agent needs OAuth2 credentials to authenticate with the AgentCore Gateway. The `.mcp-credentials.json` file is generated when you deploy the Neo4j MCP server and contains everything the agent needs to obtain access tokens and call the Gateway.

**How the code uses credentials:** The `aircraft-agent.py` file loads this JSON file at startup using the `load_credentials()` function. Before each request, it checks if the OAuth2 access token is expired using `check_token_expiry()`. If expired or missing, it calls `refresh_token()` which makes an HTTP POST request to the Cognito token endpoint using the client credentials grant flow. The refreshed token is saved back to the file for subsequent requests.

**Required fields in `.mcp-credentials.json`:**

| Field | Description |
|-------|-------------|
| `gateway_url` | The AgentCore Gateway endpoint URL that proxies requests to the MCP server |
| `token_url` | The Cognito token endpoint for obtaining OAuth2 access tokens |
| `client_id` | OAuth2 client ID registered in the Cognito User Pool |
| `client_secret` | OAuth2 client secret for the client credentials grant |
| `scope` | OAuth2 scope that grants permission to invoke the MCP server |
| `region` | AWS region where Bedrock is accessed (for Claude model calls) |

### Step 3: Test Locally

Start the agent locally on port 8080:

```bash
./agent.sh start
```

In another terminal, test with:

```bash
./agent.sh test
```

**What this does:** The `start` command runs `aircraft-agent.py` directly using the Python interpreter. The agent creates an HTTP server on port 8080 that accepts POST requests to the `/invocations` endpoint.

**How the agent works:** When a request arrives, the `invoke()` function in `aircraft-agent.py` is called (decorated with `@app.entrypoint`). This function:

1. Extracts the user's prompt from the request payload
2. Loads credentials and refreshes the OAuth2 token if needed
3. Creates a connection to the MCP server through the AgentCore Gateway using `MultiServerMCPClient` from langchain-mcp-adapters
4. Retrieves available tools from the MCP server (like `get_schema` and `execute_query`)
5. Initializes the Claude Sonnet model via AWS Bedrock's Converse API
6. Creates a ReAct agent using LangChain's `create_react_agent()` that combines the LLM with the MCP tools
7. Runs the agent loop which reasons about the question, calls tools as needed, and generates a final response
8. Streams the response back to the client

The agent includes a system prompt (defined in `aircraft-agent.py`) that instructs Claude how to use the Neo4j tools effectively—first retrieving the schema to understand the database structure, then formulating appropriate Cypher queries.

Stop the local agent with Ctrl+C or `./agent.sh stop`.

### Step 4: Configure for AWS Deployment

Run the AgentCore configure command:

```bash
./agent.sh configure
```

Accept all the defaults when prompted.

**What this does:** This runs the `agentcore configure` CLI command which analyzes your `aircraft-agent.py` file and creates a `.bedrock_agentcore.yaml` configuration file. This YAML file contains:

- The entrypoint file path (`aircraft-agent.py`)
- The AWS region for deployment
- Runtime configuration settings
- After deployment, the agent runtime ARN is also stored here

The configure command also prompts for deployment preferences and validates that your AWS credentials have the necessary permissions for AgentCore operations.

For a specific region, you can run: `uv run agentcore configure -e aircraft-agent.py -r us-east-1`

### Step 5: Deploy to AgentCore Runtime

Deploy the agent to AWS:

```bash
./agent.sh deploy
```

**What this does:** The `agentcore deploy` command packages your agent code and deploys it to Amazon Bedrock AgentCore Runtime. This process:

1. **Packages the code** - Bundles `aircraft-agent.py`, dependencies, and the `.mcp-credentials.json` file
2. **Creates an ECR image** - Builds a container image with your agent code and pushes it to Amazon ECR
3. **Provisions the runtime** - Creates an AgentCore Runtime resource that runs your containerized agent
4. **Sets up IAM roles** - Creates the necessary IAM roles for the agent to access Bedrock and other AWS services
5. **Configures CloudWatch** - Sets up log groups for monitoring agent execution

This process typically takes several minutes. The output includes the Agent ARN which uniquely identifies your deployed agent.

The deployment output also includes a **GenAI Observability Dashboard** URL. Open this URL in your browser to monitor your agent's performance and trace requests as you test it in the following steps.

Check deployment status anytime with:

```bash
./agent.sh status
```

### Step 6: Test Deployed Agent

Invoke the deployed agent using the CLI:

```bash
./agent.sh invoke-cloud "What is the database schema?"
./agent.sh invoke-cloud "How many aircraft are in the database?"
```

**What this does:** The `invoke-cloud` command uses the `agentcore invoke` CLI to send a request to your deployed agent in AWS. The request travels through the AgentCore Runtime infrastructure, which:

1. Routes the request to your running agent container
2. Executes the same `invoke()` function that runs locally
3. The agent connects to the Neo4j MCP server via the Gateway (using the bundled credentials)
4. Streams the response back through AgentCore to your terminal

This validates that the entire end-to-end flow works in the cloud environment.

### Step 7: Invoke Your Agent Programmatically

Use the `invoke_agent.py` script to call the deployed agent from Python:

```bash
uv run python invoke_agent.py "What is the database schema?"
```

**What this does:** The `invoke_agent.py` script demonstrates how to call your deployed agent from application code using the AWS SDK (boto3). This is the pattern you would use to integrate the agent into a larger application.

**How the script works:**

1. Reads the agent ARN from `.bedrock_agentcore.yaml` (created during configure/deploy)
2. Creates a boto3 client for the `bedrock-agentcore` service
3. Calls `invoke_agent_runtime()` with the agent ARN, a session ID, and the user's prompt as a JSON payload
4. Parses the streaming response chunks, handling different message types (chunks, errors, completion signals)
5. Assembles and displays the final response

This script serves as a reference implementation for integrating the Neo4j MCP Agent into your own applications.

### Step 8: Cleanup

Remove the agent from AgentCore Runtime:

```bash
./agent.sh destroy
```

**What this does:** The `agentcore destroy` command removes all AWS resources created during deployment:

- Deletes the AgentCore Runtime resource
- Removes the container image from ECR
- Cleans up associated IAM roles and policies
- Deletes CloudWatch log groups

This ensures you are not billed for resources you are no longer using. The local files (`.bedrock_agentcore.yaml`, `.mcp-credentials.json`) are preserved so you can redeploy later if needed.

## Observability & Monitoring

### CloudWatch Logs

Agent logs are automatically sent to Amazon CloudWatch Logs when running in AgentCore Runtime. The logs capture all output from your agent including startup messages, request processing, tool calls, and errors.

**Finding your logs in the AWS Console:**

1. Open the **AWS Management Console**
2. Navigate to **CloudWatch** → **Log groups** (in the left sidebar)
3. Search for `/aws/bedrock-agentcore/runtimes/`
4. Click on the log group named `/aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT`

The `{agent-id}` is the unique identifier for your agent runtime, which you can find by running `./agent.sh status`.

**View logs via CLI:**

```bash
# Get your agent runtime ID from status
./agent.sh status

# Tail logs in real-time (replace <agent-id> with your actual ID)
aws logs tail /aws/bedrock-agentcore/runtimes/<agent-id>-DEFAULT --follow

# View logs from the last hour
aws logs tail /aws/bedrock-agentcore/runtimes/<agent-id>-DEFAULT --since 1h
```

### AWS Console Resources

Here is where to find each resource type in the AWS Management Console:

| Resource | How to Find It |
|----------|----------------|
| Agent Logs | **CloudWatch** → **Log groups** → Search for `/aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT` |
| Agent Runtime | **Bedrock AgentCore** → **Runtimes** (lists all deployed agents) |
| Memory Resources | **Bedrock AgentCore** → **Memory** (if using AgentCore Memory features) |
| IAM Role | **IAM** → **Roles** → Search for "BedrockAgentCore" to find the execution role |

### Enabling Transaction Search (Tracing)

For enhanced tracing and observability across the entire request lifecycle, enable CloudWatch Transaction Search before deploying:

1. Open the **AWS Console**
2. Navigate to **CloudWatch** → **Settings** → **Transaction Search**
3. Follow the [AgentCore Observability Setup Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/userguide/runtime-observability.html)

This enables distributed tracing so you can see the full path of requests through your agent, including time spent in each component.

### CLI Commands for Monitoring

```bash
# Check deployment status and resource health
./agent.sh status

# Or directly with agentcore CLI
uv run agentcore status

# List all deployed agent runtimes in your account
aws bedrock-agentcore-control list-agent-runtimes --region us-west-2

# Get detailed information for a specific runtime
aws bedrock-agentcore-control get-agent-runtime \
    --agent-runtime-id <agent-id> \
    --region us-west-2
```

### Deployment Output

After running `./agent.sh deploy`, the output includes:
- **Agent ARN** - Full Amazon Resource Name used when invoking the agent programmatically
- **CloudWatch Log Group** - The log group path for debugging and monitoring
- **Endpoint URL** - The internal URL for direct API invocation (used by the agentcore CLI)

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

**How the components interact:**

1. **User Input** arrives via HTTP POST to the `/invocations` endpoint
2. **BedrockAgentCoreApp** (in `aircraft-agent.py`) receives the request and extracts the prompt
3. **LangChain ReAct Agent** reasons about the question and decides which tools to call
4. **langchain-mcp-adapters** converts MCP tool calls into the proper format and sends them through the Gateway
5. **AgentCore Gateway** authenticates the request using the OAuth2 JWT token and forwards it to the MCP server
6. **Neo4j MCP Server** executes the requested operation (schema retrieval or Cypher query) against the database
7. **Claude Sonnet 4** (via Bedrock Converse API) processes tool results and generates natural language responses

## Commands

| Command | Description |
|---------|-------------|
| `./agent.sh setup` | Install dependencies using uv package manager |
| `./agent.sh start` | Start the agent locally on port 8080 for testing |
| `./agent.sh stop` | Stop the locally running agent process |
| `./agent.sh test` | Send a test request to the local agent using curl |
| `./agent.sh configure` | Generate AWS deployment configuration in `.bedrock_agentcore.yaml` |
| `./agent.sh deploy` | Package and deploy the agent to AgentCore Runtime |
| `./agent.sh status` | Check the deployment status and health of the agent |
| `./agent.sh invoke-cloud "prompt"` | Send a prompt to the deployed agent in AWS |
| `./agent.sh destroy` | Remove the agent and all associated AWS resources |
| `./agent.sh help` | Display help message with all available commands |

## Files

| File | Description |
|------|-------------|
| `aircraft-agent.py` | Main agent implementation with the `@app.entrypoint` handler, OAuth2 token management, MCP client setup, and ReAct agent creation |
| `agent.sh` | Bash wrapper script that provides a simple CLI for all agent operations |
| `invoke_agent.py` | Example script showing how to invoke the deployed agent programmatically using boto3 |
| `simple-agent.py` | Simplified version of the agent for local testing and experimentation |
| `pyproject.toml` | Python project configuration with all dependencies for the uv package manager |
| `.mcp-credentials.json` | OAuth2 credentials for Gateway authentication (copied from MCP server deployment, not committed to git) |
| `.bedrock_agentcore.yaml` | AgentCore deployment configuration (created by `configure` command) |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MODEL_ID` | The Bedrock model identifier for Claude | `us.anthropic.claude-sonnet-4-20250514-v1:0` |
| `AWS_REGION` | AWS region for Bedrock API calls | `us-west-2` |

## Troubleshooting

### Token Refresh Failed
```
ERROR: Token refresh failed: 401
```
The OAuth2 client credentials are invalid. Verify that `client_id` and `client_secret` in `.mcp-credentials.json` match the values from your Cognito User Pool app client.

### AWS Credentials Not Found
```
botocore.exceptions.NoCredentialsError
```
AWS credentials are not configured. Run `aws configure` to set up your credentials, or set the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables.

### Bedrock Access Denied
```
AccessDeniedException: You don't have access to the model
```
You need to enable model access for Claude Sonnet 4 in your AWS account. Go to the AWS Bedrock console, navigate to Model access, and request access to the Claude models.

### Port 8080 Already in Use
```
{"timestamp":"...","status":404,"error":"Not Found","path":"/invocations"}
```
If you receive a 404 error with a JSON response containing a "timestamp" field, another service (often a Java application) is already running on port 8080.

Check what process is using the port:
```bash
lsof -i :8080
```

Kill the conflicting process and restart the agent:
```bash
lsof -ti :8080 | xargs kill
./agent.sh start
```

### Deployment Failed
```
agentcore deploy failed
```
Check `./agent.sh status` for detailed error messages. Common causes include insufficient IAM permissions for bedrock-agentcore actions or missing prerequisites like Docker for container builds.

## References

- [AgentCore Runtime Quickstart](https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/quickstart.html)
- [Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [neo4j-agentcore-mcp-server](../neo4j-agentcore-mcp-server/) - The MCP server this agent connects to
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
- [Model Context Protocol](https://modelcontextprotocol.io/)
