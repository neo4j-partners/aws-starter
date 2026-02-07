# Databricks Samples

Sample notebooks for integrating Neo4j MCP Server with Databricks via AWS AgentCore.

## Overview

This sample demonstrates how to connect Databricks to a Neo4j graph database through the Model Context Protocol (MCP). Instead of connecting directly to Neo4j, Databricks uses a Unity Catalog HTTP connection that acts as a secure proxy to an external MCP server running on AWS AgentCore.

Here's how it works:

1. **MCP Server Deployment**: The Neo4j MCP server runs on AWS AgentCore Runtime, accessible via the AgentCore Gateway. The Gateway provides OAuth2 authentication and tool name prefixing.

2. **Unity Catalog HTTP Connection**: Databricks creates an HTTP connection in Unity Catalog that stores the Gateway endpoint URL and OAuth2 M2M credentials (client ID, client secret, token endpoint). Databricks automatically handles token exchange and refresh.

3. **Secure Proxy**: When notebooks or SQL queries call the MCP tools, Databricks routes requests through its internal proxy (`/api/2.0/mcp/external/{connection_name}`). This proxy handles OAuth2 authentication and forwards requests to the AgentCore Gateway.

4. **Tool Execution**: The Gateway prefixes tool names with the target name (e.g., `neo4j-mcp-server-target___read-cypher`), then routes to the MCP Runtime. The MCP server parses JSON-RPC requests, executes Cypher queries against Neo4j, and returns results.

This architecture provides several benefits:
- **Centralized credential management** via Databricks secrets
- **Automatic token refresh** - Databricks handles OAuth2 token lifecycle
- **Governance and auditing** through Unity Catalog
- **Network isolation** - the MCP server can be locked down to only accept requests from authorized sources
- **Consistent interface** - notebooks and agents use the same MCP protocol

## Why External Hosting?

You might wonder: "Why not just run the Neo4j MCP server directly in Databricks?" The answer lies in fundamental technology constraints.

### The Problem: Technology Stack Mismatch

The official Neo4j MCP server ([github.com/neo4j/mcp](https://github.com/neo4j/mcp)) is **written in Go** and distributed as a **compiled binary or Docker container**. This creates an incompatibility with Databricks Apps, which has strict runtime limitations.

### Databricks Apps Limitations

| Capability | Databricks Apps | Neo4j MCP Server |
|------------|-----------------|------------------|
| **Runtime** | Python, Node.js only | Go (compiled binary) |
| **Containers** | Not supported | Requires Docker |
| **Frameworks** | Streamlit, Dash, Gradio, React | Native HTTP server |
| **File size** | Max 10 MB | Binary exceeds limit |
| **Dependencies** | pip/npm packages only | System-level binary |

### The Databricks-Recommended Solution

This external hosting pattern is **Databricks' recommended approach** for MCP servers that cannot run natively in Databricks Apps. By deploying the MCP server to AWS AgentCore (or Azure Container Apps), you get:

1. **Full compatibility** - Run any MCP server regardless of language or runtime
2. **Managed infrastructure** - AgentCore handles scaling, security, and availability
3. **Secure integration** - Unity Catalog HTTP connections provide governance
4. **Automatic auth** - Databricks manages OAuth2 token lifecycle

This pattern applies to any MCP server built with Go, Rust, C++, or other compiled languages, not just Neo4j.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    DATABRICKS WORKSPACE (AWS)                            │
│                                                                                          │
│  ┌──────────────────┐      ┌─────────────────────────────────────────────────────────┐  │
│  │                  │      │                   UNITY CATALOG                          │  │
│  │   Notebooks /    │      │  ┌─────────────────┐    ┌────────────────────────────┐  │  │
│  │   SQL Queries    │─────▶│  │  HTTP Connection │    │  Secrets Scope             │  │  │
│  │                  │      │  │  (neo4j_agentcore│◀───│  - gateway_host            │  │  │
│  │  http_request()  │      │  │   _mcp)          │    │  - client_id               │  │  │
│  │  or LangGraph    │      │  │                  │    │  - client_secret           │  │  │
│  │                  │      │  │  Is MCP: ✓       │    │  - token_endpoint          │  │  │
│  │                  │      │  │  OAuth2 M2M      │    │  - oauth_scope             │  │  │
│  └──────────────────┘      │  └────────┬────────┘    └────────────────────────────┘  │  │
│                            └───────────┼──────────────────────────────────────────────┘  │
│                                        │                                                 │
│  ┌─────────────────────────────────────┼─────────────────────────────────────────────┐  │
│  │                    DATABRICKS HTTP PROXY                                           │  │
│  │                    /api/2.0/mcp/external/{connection_name}                         │  │
│  │                                                                                    │  │
│  │    OAuth2 Token Exchange ──▶  Forwards JSON-RPC  ──▶  Returns MCP Response        │  │
│  │    (automatic refresh)                                                             │  │
│  └─────────────────────────────────────┬─────────────────────────────────────────────┘  │
│                                        │                                                 │
└────────────────────────────────────────┼─────────────────────────────────────────────────┘
                                         │
                                         │ HTTPS (OAuth2 JWT Bearer Token)
                                         │ JSON-RPC 2.0 over HTTP
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              AWS AGENTCORE                                               │
│                                                                                          │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐  │
│  │                           AGENTCORE GATEWAY                                        │  │
│  │                                                                                    │  │
│  │   - OAuth2 token validation via Cognito                                           │  │
│  │   - Tool name prefixing: {target}___{tool}                                        │  │
│  │   - Routes requests to MCP Runtime                                                │  │
│  └───────────────────────────────────────────────────────────────────────────────────┘  │
│                                        │                                                 │
│                                        ▼                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐  │
│  │                           NEO4J MCP SERVER (AgentCore Runtime)                     │  │
│  │                                                                                    │  │
│  │   Tools (Gateway-prefixed):                                                        │  │
│  │   - neo4j-mcp-server-target___get-schema: Returns node labels, relationships      │  │
│  │   - neo4j-mcp-server-target___read-cypher: Executes read-only Cypher queries      │  │
│  │                                                                                    │  │
│  │   Config: NEO4J_READ_ONLY=true (write-cypher disabled)                            │  │
│  └───────────────────────────────────────────────────────────────────────────────────┘  │
│                                        │                                                 │
└────────────────────────────────────────┼─────────────────────────────────────────────────┘
                                         │
                                         │ Bolt Protocol (neo4j+s://)
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              NEO4J AURA                                                  │
│                                                                                          │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐  │
│  │                           GRAPH DATABASE                                           │  │
│  │                                                                                    │  │
│  │   (Nodes)──[:RELATIONSHIPS]──▶(Nodes)                                             │  │
│  │                                                                                    │  │
│  └───────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### Request Flow

```
1. Notebook calls http_request() or agent invokes MCP tool
                    │
                    ▼
2. Unity Catalog resolves connection settings (OAuth2 M2M credentials)
                    │
                    ▼
3. Databricks proxy exchanges credentials for JWT, forwards to Gateway
                    │
                    ▼
4. Gateway validates token, prefixes tool name, routes to Runtime
                    │
                    ▼
5. MCP server parses JSON-RPC, executes Cypher against Neo4j
                    │
                    ▼
6. Results returned through Gateway and proxy to notebook
```

## Cluster Setup

Before running these notebooks, configure your Databricks cluster with the required libraries.

### 1. Create or Edit a Cluster

1. Navigate to **Compute** in the Databricks sidebar
2. Create a new cluster or edit an existing one
3. Under **Performance**, check **Machine learning** to enable ML Runtime
   - This provides pre-installed PyTorch, TensorFlow, XGBoost, and MLflow
4. Select **Databricks Runtime**: 17.3 LTS ML or later recommended
5. Enable **Single node** for development/testing (optional)

### 2. Install Required Libraries

Go to the **Libraries** tab on your cluster and install these packages from PyPI:

| Library | Version | Notes |
|---------|---------|-------|
| `databricks-agents` | `>=1.2.0` | Agent deployment framework |
| `databricks-langchain` | `>=0.11.0` | Databricks LangChain integration |
| `langgraph` | `==1.0.5` | LangGraph agent framework |
| `langchain-core` | `>=1.2.0` | LangChain core |
| `langchain-openai` | `==1.1.2` | OpenAI integration (for embeddings) |
| `mcp` | latest | Model Context Protocol |
| `databricks-mcp` | latest | Databricks MCP client |
| `pydantic` | `==2.12.5` | Data validation |
| `neo4j` | `==6.0.2` | Neo4j Python driver (optional) |
| `neo4j-graphrag` | `>=1.10.0` | Neo4j GraphRAG (optional) |

**To add a library:**
1. Click **Install new** on the Libraries tab
2. Select **PyPI** as the source
3. Enter the package name with version (e.g., `langgraph==1.0.5`)
4. Click **Install**

**Tip:** Check [PyPI](https://pypi.org/) for the latest compatible versions if you encounter dependency conflicts.

## Files

| File | Description |
|------|-------------|
| [neo4j-mcp-http-connection.ipynb](./neo4j-mcp-http-connection.ipynb) | Setup and test an HTTP connection to query Neo4j via MCP |
| [neo4j_mcp_agent.py](./neo4j_mcp_agent.py) | LangGraph agent that connects to Neo4j via external MCP HTTP connection |
| [neo4j-mcp-agent-deploy.ipynb](./neo4j-mcp-agent-deploy.ipynb) | Test, evaluate, and deploy the Neo4j MCP agent |
| [setup_databricks_secrets.sh](./setup_databricks_secrets.sh) | Setup script to configure OAuth2 secrets from AgentCore credentials |

## Neo4j MCP HTTP Connection

The `neo4j-mcp-http-connection.ipynb` notebook demonstrates how to create a Databricks HTTP connection to the Neo4j MCP server via AWS AgentCore. This enables querying Neo4j graph data directly from SQL using the `http_request` function.

### Prerequisites

1. **MCP Server Deployed**: The Neo4j MCP server must be deployed on AWS AgentCore
2. **Credentials Generated**: Run `./deploy.sh credentials` in `neo4j-agentcore-mcp-server/`
3. **Databricks Runtime**: 15.4 LTS or later, or SQL warehouse 2023.40+
4. **Unity Catalog**: Must be enabled on your workspace
5. **Secrets Configured**: Run the setup script before using the notebook

### Setup Steps

**Step 1: Deploy the MCP Server to AgentCore**

```bash
cd neo4j-agentcore-mcp-server
./deploy.sh              # Deploy the CDK stack
./deploy.sh credentials  # Generate .mcp-credentials.json
```

**Step 2: Configure Databricks Secrets**

From your local machine:

```bash
cd databrick_samples
./setup_databricks_secrets.sh                              # Uses default profile
./setup_databricks_secrets.sh --profile my-workspace       # Use a specific Databricks CLI profile
./setup_databricks_secrets.sh my-scope --profile staging   # Custom scope + profile
```

This reads the OAuth2 credentials from `.mcp-credentials.json` and stores them securely in Databricks secrets.

The `--profile` flag specifies which Databricks CLI profile to use (as configured in `~/.databrickscfg`). If omitted, the default profile is used. To set up a profile: `databricks auth login --profile my-workspace`.

**Step 3: Import and Run the Notebook**

1. Import `neo4j-mcp-http-connection.ipynb` into your Databricks workspace
2. Attach it to a cluster running Databricks Runtime 15.4 LTS or later
3. Update the configuration cell with your secret scope name (default: `mcp-neo4j-secrets`)
4. Run all cells to create the connection and test it

**Step 4: Enable MCP Connection**

The notebook creates an HTTP connection, but you must manually enable MCP functionality:

1. In the Databricks sidebar, click **Catalog**
2. Navigate to **External Data** > **Connections**
3. Click on your connection name (e.g., `neo4j_agentcore_mcp`)
4. Click the **three-dot menu** (⋮) and select **Edit**
5. Check the **Is MCP connection** box
6. Click **Update** to save

### What the Notebook Does

1. **Validates secrets** - Confirms OAuth2 credentials are configured
2. **Creates HTTP connection** - Sets up a Unity Catalog connection with OAuth2 M2M auth
3. **Lists MCP tools** - Verifies connectivity by listing available tools (with Gateway prefixes)
4. **Gets Neo4j schema** - Retrieves node labels, relationships, and properties
5. **Executes read queries** - Demonstrates running Cypher queries
6. **Provides helper function** - Reusable `query_neo4j()` function for your notebooks

### Security

This integration provides **read-only access** to Neo4j. The MCP server is deployed with `NEO4J_READ_ONLY=true`, which disables the `write-cypher` tool at the server level.

### Available MCP Tools

Tool names are prefixed by the AgentCore Gateway:

| Tool | Gateway Name | Description |
|------|--------------|-------------|
| `get-schema` | `neo4j-mcp-server-target___get-schema` | Retrieve database schema |
| `read-cypher` | `neo4j-mcp-server-target___read-cypher` | Execute read-only Cypher queries |

### Example Usage

After running the setup notebook, you can query Neo4j from any notebook:

```python
# Using the helper function
result = query_neo4j("MATCH (n:Person) RETURN n.name LIMIT 10")

# Or directly with SQL (note the prefixed tool name)
spark.sql("""
    SELECT http_request(
      conn => 'neo4j_agentcore_mcp',
      method => 'POST',
      path => '',
      headers => map('Content-Type', 'application/json'),
      json => '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"neo4j-mcp-server-target___get-schema","arguments":{}},"id":1}'
    )
""")
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Secret not found | Run `./setup_databricks_secrets.sh` |
| Connection already exists | Drop it with `DROP CONNECTION IF EXISTS neo4j_agentcore_mcp` |
| HTTP timeout | Verify MCP server is running with `cd neo4j-agentcore-mcp-server && ./cloud.sh` |
| 401 Unauthorized | Re-run `./deploy.sh credentials` then `./setup_databricks_secrets.sh` |
| Tool not found | Use the Gateway-prefixed name: `neo4j-mcp-server-target___get-schema` |

## Neo4j MCP Agent

The `neo4j_mcp_agent.py` and `neo4j-mcp-agent-deploy.ipynb` files provide a complete LangGraph agent that connects to Neo4j via the external MCP HTTP connection.

### Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  LangGraph      │────▶│ Unity Catalog HTTP   │────▶│ AgentCore       │────▶│ Neo4j Database  │
│  Agent          │     │ Connection Proxy     │     │ Gateway         │     │ (Aura)          │
│                 │     │ /api/2.0/mcp/external│     │                 │     │                 │
└─────────────────┘     └──────────────────────┘     └─────────────────┘     └─────────────────┘
       MCP tool calls           OAuth2 M2M            Cypher Queries
       (JSON-RPC)               (auto-refresh)        (read-cypher tool)
```

### How It Works

1. The agent uses the Unity Catalog HTTP connection proxy URL: `{host}/api/2.0/mcp/external/{connection_name}`
2. OAuth2 M2M authentication is handled automatically by Databricks (no manual token management)
3. The agent has access to Gateway-prefixed MCP tools: `neo4j-mcp-server-target___get-schema` and `neo4j-mcp-server-target___read-cypher`
4. Compatible with MLflow ResponsesAgent for deployment

### Usage

**Step 1: Create Unity Catalog Resources**

The agent is registered to Unity Catalog for governance. Create the catalog and schema if they don't exist:

Via Databricks UI:
1. Navigate to **Catalog** in the sidebar
2. Click **Create catalog** and enter `mcp_demo_catalog`
3. Click the catalog, then **Create schema** and enter `agents`

The model will be registered as: `mcp_demo_catalog.agents.neo4j_mcp_agent`

**Step 2: Deploy the Agent**

Import these files into your Databricks workspace:
- `neo4j_mcp_agent.py` - The agent code
- `neo4j-mcp-agent-deploy.ipynb` - The deployment notebook

Then run `neo4j-mcp-agent-deploy.ipynb`:

1. **Test the agent** - Verify it can query Neo4j
2. **Log as MLflow model** - Package for deployment
3. **Evaluate** - Assess quality with MLflow scorers
4. **Register to Unity Catalog** - Store for governance
5. **Deploy** - Create a serving endpoint

**Step 3: Verify Deployment**

Check the deployment status in **Serving endpoints**:
- Navigate to **Serving** in the sidebar (under AI/ML)
- Look for `agents_mcp_demo_catalog-...` endpoint
- Wait for **State** to show "Ready"

View the registered model in **Catalog Explorer**:
- Navigate to **Catalog** > **mcp_demo_catalog** > **agents**
- Click the **Models** tab to see `neo4j_mcp_agent`

### Agent Configuration

Edit `neo4j_mcp_agent.py` to customize:

| Setting | Description | Default |
|---------|-------------|---------|
| `LLM_ENDPOINT_NAME` | Databricks LLM endpoint | `databricks-claude-3-7-sonnet` |
| `CONNECTION_NAME` | HTTP connection name | `neo4j_agentcore_mcp` |
| `SECRET_SCOPE` | Secrets scope name | `mcp-neo4j-secrets` |
| `system_prompt` | Agent instructions | Neo4j query assistant |

## Related Documentation

- [AWS_DATABRICKS.md](../AWS_DATABRICKS.md) - Proposal and implementation details for AWS AgentCore integration
- [neo4j-agentcore-mcp-server](../neo4j-agentcore-mcp-server/) - MCP server deployment to AWS AgentCore
- [Databricks HTTP Connections](https://docs.databricks.com/aws/en/query-federation/http)
- [Databricks External MCP](https://docs.databricks.com/aws/en/generative-ai/mcp/external-mcp)
- [Neo4j Cypher Manual](https://neo4j.com/docs/cypher-manual/current/)
