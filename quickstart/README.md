# Neo4j MCP LangGraph Agent

This LangGraph ReAct agent answers plain-language questions about a Neo4j
graph. It reaches Neo4j through an AgentCore Gateway and uses Claude on
Bedrock to reason.

## Overview

- **Neo4j over MCP:** The Neo4j MCP server exposes `get_neo4j_schema` and `read_neo4j_cypher` as tools. Claude uses them to explore and query the graph.
- **AgentCore Gateway:** The agent talks to one HTTPS endpoint. The Gateway forwards tool calls to the Neo4j MCP server on AgentCore Runtime.
- **OAuth2 machine login:** The agent logs in to the Gateway with a Cognito token. The agent renews the token before it expires.
- **Claude on Bedrock:** The agent calls Claude through the Bedrock Converse API. It uses your normal AWS credentials, so you manage no model keys.
- **SageMaker Unified Studio:** Notebooks and an inference profile script let the agent run inside a SageMaker Studio project.

## Quick start

You need a deployed MCP server first. See [`neo4j-mcp-server/`](../neo4j-mcp-server/README.md).

Run these commands from the repo root:

```bash
cd quickstart
uv sync
cp ../neo4j-mcp-server/.mcp-credentials.json .   # copy the Gateway credentials

./agent.sh "How many aircraft are in the database?"   # ask one question
./agent.sh                                              # run the demo questions
```

The agent loads the credentials, renews the token if needed, connects to the
Gateway, and answers.

You can also copy the credentials with
[`scripts/sync-credentials.sh`](../scripts/sync-credentials.sh). Run it from
the repo root. It copies each deployment's credentials to the samples that use
it.

The agent works with any graph the MCP server points at. The sample question
and the demo questions expect the aircraft fleet graph. The pipeline in
[`demos/aircraft-fleet/pipeline/`](../demos/aircraft-fleet/pipeline/) loads
that graph. On another graph, the schema question still works. The other demo
questions return nothing, so ask about your own labels instead.

## Architecture

```
You ──question──▶ LangGraph Agent ──reasoning──▶ Claude (Bedrock)
                        │
                        │ MCP tool calls over HTTPS + OAuth2
                        ▼
                AgentCore Gateway
                        │
                        ▼
            Neo4j MCP Server (AgentCore Runtime)
                        │
                        ▼
                   Neo4j database
```

The agent uses two separate logins:

- **OAuth2 (Cognito):** This token logs the agent in to the Gateway.
- **AWS credentials:** These credentials let the agent call Claude on Bedrock.

## How it works

- **The agent loop:** The agent asks Claude what to do next. Claude either answers or asks for a tool call. The agent runs the tool and sends the result back to Claude. This repeats until Claude has the final answer. This loop is the ReAct pattern, and LangGraph runs it.
- **Tool discovery:** The tools are not hardcoded. At startup the agent asks the Gateway for its tools. The Gateway returns the Neo4j tools, and Claude decides when to call them.
- **The Gateway:** The agent knows one URL instead of the Neo4j address. The Gateway checks the agent's token, forwards each tool call to the Neo4j MCP server, and returns the result.
- **Token renewal:** The production agent checks the token on every run. If the token expires within 5 minutes, the agent gets a new one from Cognito. It saves the new token to `.mcp-credentials.json`.

The agent has two versions:

- **Production agent:** Run it with `./agent.sh`. It renews the OAuth2 token for you. Use it for anything that runs a long time.
- **Simple agent:** Run it with `uv run python -m neo4j_mcp_quickstart.simple_agent "..."`. It uses the saved token and never renews it. The token lasts about 1 hour, so use this version for quick one-off tests.

## Configuration

| Setting | Where | Default |
|---------|-------|---------|
| Model | `MODEL_ID` in `neo4j_mcp_quickstart/core.py` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Region | `region` in `.mcp-credentials.json` | `DEFAULT_REGION` in `core.py`, which is `us-east-1` |
| Credentials | `.mcp-credentials.json` in `quickstart/` | Written by `./deploy.py credentials` in `neo4j-mcp-server/` |

## SageMaker Unified Studio

SageMaker Unified Studio blocks direct Bedrock model access with a
permissions boundary. To get past it, create a Bedrock application inference
profile with the tag `AmazonBedrockManaged=true`. Then paste the profile ARN
into the notebook config cell.

Run these commands from `quickstart/`:

```bash
./inference-profiles/setup-inference-profile.sh --list          # show profiles and tag status
./inference-profiles/setup-inference-profile.sh haiku           # create a Haiku profile
./inference-profiles/setup-inference-profile.sh sonnet          # create a Sonnet profile
./inference-profiles/setup-inference-profile.sh --test haiku    # create and test a profile
./inference-profiles/setup-inference-profile.sh --all           # create profiles for all models
./inference-profiles/setup-inference-profile.sh --delete haiku  # delete one profile
./inference-profiles/setup-inference-profile.sh --delete-all    # delete all lab profiles
```

With no arguments, the script asks you to pick a model.

| Notebook | Purpose |
|----------|---------|
| `notebooks/minimal_langgraph_agent.ipynb` | Test LangGraph and Bedrock with no MCP |
| `notebooks/neo4j_simple_mcp_agent.ipynb` | Run a simple MCP agent through the Gateway |
| `notebooks/neo4j_strands_mcp_agent.ipynb` | Run a Strands MCP agent through the Gateway |

[docs/SAGEMAKER-MODELS.md](docs/SAGEMAKER-MODELS.md) has more detail.

## Still to be verified

One claim in [docs/SAGEMAKER-MODELS.md](docs/SAGEMAKER-MODELS.md) is not yet
tested end to end. The claim is that a profile made by the script, with
`AmazonBedrockManaged=true`, works inside the SageMaker Unified Studio
permissions boundary.

Local tests could not answer this for two reasons:

- **No DataZone:** The test account and region have no DataZone. The script never applied the SageMaker Unified Studio tag to the profile.
- **Broad local credentials:** The local `--test` run called Bedrock with broad local credentials. It did not run under the restricted project role.

To verify it, create a profile with
`./inference-profiles/setup-inference-profile.sh`. Then run
`notebooks/minimal_langgraph_agent.ipynb` in a SageMaker Unified Studio space
with the project execution role. If it works, the docs are correct. If it
fails, update [docs/SAGEMAKER-MODELS.md](docs/SAGEMAKER-MODELS.md) with the
real result.

## Testing

Run these commands from `quickstart/`:

```bash
uv sync --extra test
uv run python tests/test_fastmcp.py
```

`test_fastmcp.py` lists the Gateway tools. It then calls `get_neo4j_schema` and
`read_neo4j_cypher` with the FastMCP client. It uses no LLM, so it is the fastest
way to check that the Gateway and Neo4j are reachable.

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `Token refresh failed: 401` | The `client_id` or `client_secret` in `.mcp-credentials.json` is wrong. |
| `NoCredentialsError` | AWS credentials are not set. Run `aws configure` or set the AWS environment variables. |
| `AccessDeniedException` on the model | Claude model access is off. Turn it on in the Bedrock console. |
| `httpx.ConnectError` | The `gateway_url` is wrong, or the MCP server is not deployed. |

## Run the notebooks in SageMaker Studio

Each notebook has a config cell near the top. Paste your inference profile
ARN there. Some notebooks also need the Gateway values from
`.mcp-credentials.json`. Then run all cells.

### `notebooks/minimal_langgraph_agent.ipynb`

This notebook tests LangGraph and Bedrock with simple time and math tools. It
needs no MCP server or database.

1. Open the notebook in JupyterLab.
2. Paste your inference profile ARN in the config cell.
3. Run all cells to check that Claude works.

```python
INFERENCE_PROFILE_ARN = "arn:aws:bedrock:us-east-1:123456789:application-inference-profile/abc123"
REGION = "us-east-1"
```

### `notebooks/neo4j_strands_mcp_agent.ipynb`

This notebook runs a Strands MCP agent through the Gateway. Strands Agents is
the AWS agent library. Copy the values from `.mcp-credentials.json` into the
config cell:

```python
INFERENCE_PROFILE_ARN = "your-inference-profile-arn"
GATEWAY_URL = "https://...amazonaws.com/mcp"  # from gateway_url
ACCESS_TOKEN = "eyJ..."                        # from access_token
REGION = "us-east-1"
```

### `notebooks/neo4j_simple_mcp_agent.ipynb`

This notebook runs a simple MCP agent through the Gateway. Paste your
credentials into the config cell:

```python
INFERENCE_PROFILE_ARN = "your-inference-profile-arn"
GATEWAY_URL = "your-gateway-url"
ACCESS_TOKEN = "your-access-token"
REGION = "us-east-1"
```

The notebook shows these parts:

- **Low-level MCP client:** The notebook connects with `streamablehttp_client`.
- **ReAct agent:** The notebook builds a LangGraph `create_react_agent` from the MCP tools it loads.
- **Multi-step queries:** The agent uses the ReAct loop to answer questions that need more than one query.

## References

- [`neo4j-mcp-server/`](../neo4j-mcp-server/README.md) is the MCP server this agent connects to.
- [LangGraph](https://langchain-ai.github.io/langgraph/)
- [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [AWS Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html)
