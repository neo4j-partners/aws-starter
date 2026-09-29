# Databricks Integration

These notebooks connect Databricks to a Neo4j graph through the Neo4j MCP
server on AWS AgentCore. Databricks reaches the server through a Unity Catalog
HTTP connection.

## Overview

- **MCP server:** The Neo4j MCP server runs on AgentCore Runtime. The AgentCore Gateway sits in front of it and checks OAuth2 tokens.
- **HTTP connection:** Unity Catalog stores the Gateway URL and the OAuth2 machine-to-machine credentials. Databricks gets and refreshes tokens for you.
- **Secrets:** A setup script copies the OAuth2 credentials into a Databricks secret scope.
- **Notebooks:** One notebook creates and tests the connection. A second notebook tests, evaluates, and deploys a LangGraph agent.
- **Read-only access:** The MCP server only exposes read tools. Databricks cannot change the graph.

## Quick start

Run these commands from the repo root:

```bash
# 1. Generate the Gateway credentials (once, after deploying the MCP server)
cd neo4j-mcp-server
./deploy.py credentials

# 2. Store the credentials in Databricks secrets
cd ../integrations/databricks
./setup_databricks_secrets.sh --profile <profile-name>
```

Then finish in the Databricks workspace:

1. Import and run `neo4j-mcp-http-connection.ipynb` to create the connection.
2. Turn on **Is MCP connection** for the new connection.
3. Optional: Import and run `neo4j-mcp-agent-deploy.ipynb` to deploy the agent.

## Prerequisites

- **Neo4j MCP server:** Deploy the server to AgentCore first. See [`neo4j-mcp-server/`](../../neo4j-mcp-server/).
- **Databricks CLI:** Install the CLI and log in. The commands are below.
- **Cluster:** Use Databricks Runtime 15.4 LTS or later. Install the [required libraries](#cluster-setup).
- **Unity Catalog:** Your workspace must have Unity Catalog turned on.
- **jq:** The setup script uses `jq` to read JSON. On macOS, install it with `brew install jq`.

Log in to the Databricks CLI:

```bash
# First login. This creates a profile in ~/.databrickscfg.
databricks auth login --host <workspace-url> --profile <profile-name>

# Log in again when the credentials expire.
databricks auth login --profile <profile-name>

# Check that the login works.
databricks auth describe --profile <profile-name>
```

## Step 1: Generate AgentCore credentials

Run this from the repo root. You only need to do it once after you deploy the
MCP server.

```bash
cd neo4j-mcp-server
./deploy.py credentials
```

This command writes `neo4j-mcp-server/.mcp-credentials.json`. The setup script
in Step 2 reads the file from that location. You do not need to copy it.

## Step 2: Configure Databricks secrets

Run this from the repo root:

```bash
cd integrations/databricks
./setup_databricks_secrets.sh                              # default scope and profile
./setup_databricks_secrets.sh --profile my-workspace       # a specific CLI profile
./setup_databricks_secrets.sh my-scope --profile staging   # a custom scope and profile
```

- **Scope name:** The first argument sets the secret scope. The default scope is `mcp-neo4j-secrets`.
- **`--profile`:** This flag picks a Databricks CLI profile from `~/.databrickscfg`.

The script reads `neo4j-mcp-server/.mcp-credentials.json`. It stores five
secrets in the scope: `gateway_host`, `client_id`, `client_secret`,
`token_endpoint`, and `oauth_scope`.

## Step 3: Run the HTTP connection notebook

1. Import `neo4j-mcp-http-connection.ipynb` into your Databricks workspace.
2. Attach it to a cluster that runs Databricks Runtime 15.4 LTS or later.
3. Set your secret scope name in the configuration cell. The default is `mcp-neo4j-secrets`.
4. Run all cells. The notebook creates the connection and tests it.

## Step 4: Turn on MCP for the connection

The notebook creates an HTTP connection. You must mark it as an MCP connection
by hand:

1. In the Databricks sidebar, click **Catalog**.
2. Go to **External Data** > **Connections**.
3. Click your connection name, for example `neo4j_agentcore_mcp`.
4. Click the **three-dot menu** and select **Edit**.
5. Check the **Is MCP connection** box.
6. Click **Update** to save.

## Step 5 (optional): Deploy the LangGraph agent

1. Create a Unity Catalog catalog named `mcp_demo_catalog` with a schema named `agents`.
2. Import `neo4j_mcp_agent.py` and `neo4j-mcp-agent-deploy.ipynb` into your workspace.
3. Run `neo4j-mcp-agent-deploy.ipynb`. It tests, evaluates, and deploys the agent.

## Cluster setup

Set up the cluster before you run the notebooks.

### Create or edit a cluster

1. Go to **Compute** in the Databricks sidebar.
2. Create a new cluster or edit an existing one.
3. Under **Performance**, check **Machine learning** to use the ML Runtime.
4. Select a **Databricks Runtime**. Use 17.3 LTS ML or later.
5. Optional: Turn on **Single node** for development and testing.

### Install the required libraries

Open the **Libraries** tab on your cluster. Install these packages from PyPI:

| Library | Version | Notes |
|---------|---------|-------|
| `databricks-agents` | `>=1.2.0` | Agent deployment framework |
| `databricks-langchain` | `>=0.11.0` | Databricks LangChain integration |
| `langgraph` | `==1.0.5` | LangGraph agent framework |
| `langchain-core` | `>=1.2.0` | LangChain core |
| `langchain-openai` | `==1.1.2` | OpenAI integration for embeddings |
| `mcp` | latest | Model Context Protocol |
| `databricks-mcp` | latest | Databricks MCP client |
| `pydantic` | `==2.12.5` | Data validation |
| `neo4j` | `==6.0.2` | Neo4j Python driver (optional) |
| `neo4j-graphrag` | `>=1.10.0` | Neo4j GraphRAG (optional) |

To add a library:

1. Click **Install new** on the Libraries tab.
2. Select **PyPI** as the source.
3. Enter the package name and version, for example `langgraph==1.0.5`.
4. Click **Install**.

## How it works

Databricks does not connect to Neo4j directly. It calls the MCP server through
a Unity Catalog HTTP connection.

- **Gateway:** The AgentCore Gateway checks the OAuth2 token. It adds the target name to each tool name.
- **HTTP connection:** The connection stores the Gateway URL and the OAuth2 client ID, client secret, and token endpoint. Databricks exchanges and refreshes tokens on its own.
- **Proxy:** Databricks sends MCP calls through its proxy at `/api/2.0/mcp/external/{connection_name}`. The proxy adds the OAuth2 token and forwards the request to the Gateway.
- **Tool calls:** The Gateway routes each call to the MCP server. For example, `neo4j-mcp-server-target___read-cypher` goes to the `read-cypher` tool. The server runs the Cypher query against Neo4j and returns the results.

This setup gives you these benefits:

- **Central credentials:** Databricks secrets hold all the credentials in one place.
- **Automatic token refresh:** Databricks handles the OAuth2 token lifecycle.
- **Governance:** Unity Catalog governs and audits access to the connection.
- **Network isolation:** You can lock down the MCP server to accept requests only from approved sources.
- **One interface:** Notebooks and agents both use the same MCP protocol.

## Why the server runs outside Databricks

The official Neo4j MCP server ([github.com/neo4j/mcp](https://github.com/neo4j/mcp))
is written in Go. It ships as a compiled binary or a Docker container.
Databricks Apps cannot run it.

| Capability | Databricks Apps | Neo4j MCP Server |
|------------|-----------------|------------------|
| **Runtime** | Python, Node.js only | Go (compiled binary) |
| **Containers** | Not supported | Requires Docker |
| **Frameworks** | Streamlit, Dash, Gradio, React | Native HTTP server |
| **File size** | Max 10 MB | Binary exceeds limit |
| **Dependencies** | pip/npm packages only | System-level binary |

Databricks recommends external hosting for MCP servers that cannot run in
Databricks Apps. You can host the server on AWS AgentCore or Azure Container
Apps. This gives you:

- **Full compatibility:** You can run any MCP server, in any language or runtime.
- **Managed infrastructure:** AgentCore handles scaling, security, and availability.
- **Secure integration:** Unity Catalog HTTP connections add governance.
- **Automatic auth:** Databricks manages the OAuth2 token lifecycle.

The same pattern works for any MCP server built in Go, Rust, C++, or another
compiled language.

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

### Request flow

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

## Files

| File | Description |
|------|-------------|
| [neo4j-mcp-http-connection.ipynb](./neo4j-mcp-http-connection.ipynb) | Creates and tests an HTTP connection that queries Neo4j through MCP |
| [neo4j_mcp_agent.py](./neo4j_mcp_agent.py) | LangGraph agent that queries Neo4j through the MCP HTTP connection |
| [neo4j-mcp-agent-deploy.ipynb](./neo4j-mcp-agent-deploy.ipynb) | Tests, evaluates, and deploys the Neo4j MCP agent |
| [setup_databricks_secrets.sh](./setup_databricks_secrets.sh) | Stores the AgentCore OAuth2 credentials in Databricks secrets |
| [MANUAL-SETUP.md](./MANUAL-SETUP.md) | Creates the HTTP connection by hand in the Databricks UI instead of the notebook |
| [databricks-mcp-setup.md](./databricks-mcp-setup.md) | Registers the Gateway as a Unity Catalog MCP Service for AI Playground and Databricks agents |

## Available MCP tools

The AgentCore Gateway adds the target name to each tool name:

| Tool | Gateway name | Description |
|------|--------------|-------------|
| `get-schema` | `neo4j-mcp-server-target___get-schema` | Returns the database schema |
| `read-cypher` | `neo4j-mcp-server-target___read-cypher` | Runs read-only Cypher queries |

## Example usage

After the quick start, you can query Neo4j from any notebook:

```python
# Use the helper function from the HTTP connection notebook
result = query_neo4j("MATCH (n:Person) RETURN n.name LIMIT 10")

# Or call the tool from SQL. Use the Gateway tool name.
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

## Agent configuration

Edit these settings in `neo4j_mcp_agent.py`:

| Setting | Description | Default |
|---------|-------------|---------|
| `LLM_ENDPOINT_NAME` | Databricks LLM endpoint | `databricks-claude-3-7-sonnet` |
| `CONNECTION_NAME` | HTTP connection name | `neo4j_agentcore_mcp` |
| `SECRET_SCOPE` | Secret scope name | `mcp-neo4j-secrets` |
| `system_prompt` | Agent instructions | Neo4j query assistant |

## Security

This integration gives **read-only access** to Neo4j. The MCP server runs with
`NEO4J_READ_ONLY=true`. That setting turns off the `write-cypher` tool on the
server.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Secret not found | Run `./setup_databricks_secrets.sh` from `integrations/databricks/`. |
| Connection already exists | Drop it with `DROP CONNECTION IF EXISTS neo4j_agentcore_mcp`. |
| HTTP timeout | Check that the MCP server is running. From the repo root, run `cd neo4j-mcp-server && ./cloud.sh`. |
| 401 Unauthorized | Run `./deploy.py credentials` in `neo4j-mcp-server/`. Then run `./setup_databricks_secrets.sh` again. |
| Tool not found | Use the Gateway tool name, for example `neo4j-mcp-server-target___get-schema`. |

## Related documentation

- [`neo4j-mcp-server/`](../../neo4j-mcp-server/): Deploys the MCP server to AWS AgentCore.
- [Databricks HTTP Connections](https://docs.databricks.com/aws/en/query-federation/http)
- [Databricks External MCP](https://docs.databricks.com/aws/en/generative-ai/mcp/external-mcp)
- [Neo4j Cypher Manual](https://neo4j.com/docs/cypher-manual/current/)
