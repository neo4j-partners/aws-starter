# AWS Bedrock AgentCore Starter Kit

This repository deploys the Neo4j MCP server to Amazon Bedrock AgentCore. It
also shows several ways for AI agents to call that server.

## Overview

- **MCP server:** The Neo4j MCP server runs on AgentCore Runtime. It gives agents Neo4j graph tools.
- **Gateway:** An AgentCore Gateway sits in front of the MCP server. Agents connect to it with OAuth2.
- **GraphRAG on Bedrock:** The demos use the [`neo4j-graphrag`](https://neo4j.com/docs/neo4j-graphrag-python/current/) library. It adds Bedrock embeddings, LLM entity extraction, and vector search over a Neo4j graph.
- **Advanced patterns:** Other samples cover multi-agent routing, agent memory, observability, and cloud deployment.
- **Architecture:** The [Architecture Documentation](./docs/ARCHITECTURE.md) has diagrams, component descriptions, and request flows.
- **Slides:** The [AWS + Neo4j presentation gallery](https://neo4j-partners.github.io/aws-starter/) has the current decks on semantic data discovery and grounded enterprise AI.

## Quick start

Run these commands from the repo root. They deploy the MCP server and send a
first question through the Gateway.

```bash
cd neo4j-mcp-server
cp .env.sample .env          # add NEO4J_* values and NEO4J_MCP_REPO
./deploy.py                  # build, push, and deploy the stack
./deploy.py credentials      # write .mcp-credentials.json
../scripts/sync-credentials.sh

cd ../quickstart
uv sync
./agent.sh "What is in the graph?"
```

## Sample matrix

| Sample | Domain and dataset | How the data is loaded | How it reaches Neo4j | Needs the MCP server | MCP `--env` | Deploys to Runtime | Main AWS services |
|--------|--------------------|------------------------|----------------------|----------------------|-------------|--------------------|-------------------|
| [`neo4j-mcp-server/`](./neo4j-mcp-server/) | Any graph | Not applicable | It is the MCP server | Not applicable | Any | Yes, the MCP server | AgentCore Runtime, Gateway, Cognito, Secrets Manager |
| [`quickstart/`](./quickstart/) | Any graph the MCP server points at. The demo questions assume the aviation fleet graph | Not applicable | MCP Gateway | Yes | Default | No | AgentCore Gateway, Bedrock, SageMaker Unified Studio |
| [`demos/aircraft-fleet/pipeline/`](./demos/aircraft-fleet/pipeline/) | Aviation fleet digital twin | `pipeline/setup.sh` | Neo4j Python driver | No | Not applicable | No | Bedrock Titan embeddings, Bedrock Claude |
| [`demos/aircraft-fleet/graphrag-agent/`](./demos/aircraft-fleet/graphrag-agent/) | Aviation fleet digital twin | `pipeline/` | Neo4j Python driver | No | Not applicable | Yes | AgentCore Runtime, Bedrock |
| [`demos/aircraft-fleet/supervisor-agent/`](./demos/aircraft-fleet/supervisor-agent/) | Aviation fleet digital twin | `pipeline/` | MCP Gateway | Yes | `fleet` | Yes | AgentCore Runtime, Gateway, Bedrock, CloudWatch |
| [`demos/fraud-amazon-quick/fraud-iceberg/`](./demos/fraud-amazon-quick/fraud-iceberg/) | Synthetic fraud rings | `fraud-iceberg/` | Does not reach Neo4j | No | Not applicable | No | S3 Tables, Glue, Athena |
| [`demos/fraud-amazon-quick/graph-loader/`](./demos/fraud-amazon-quick/graph-loader/) | Synthetic fraud rings | `graph-loader/` from `data/` | Neo4j Python driver | No | Not applicable | No | None |
| [`demos/fraud-amazon-quick/fraud-memory-agent/`](./demos/fraud-amazon-quick/fraud-memory-agent/) | Synthetic fraud rings | `graph-loader/` | MCP Gateway for the graph, Neo4j Agent Memory Service for memory | Yes | `finance` | Yes | AgentCore Runtime, Gateway, Bedrock, Amazon Quick |
| [`demos/sec-filings-graphrag/`](./demos/sec-filings-graphrag/) | SEC 10-K filings | The notebook | Neo4j Python driver | No | Not applicable | No | Bedrock |
| [`integrations/databricks/`](./integrations/databricks/) | Any graph the MCP server points at | Not applicable | MCP Gateway through a Unity Catalog HTTP connection | Yes | Default | No | AgentCore Gateway, Cognito |
| [`integrations/neo4j-aura-agents/`](./integrations/neo4j-aura-agents/) | Any AuraDB graph | The Neo4j Aura console | Neo4j Aura Agents REST API | No | Not applicable | No | None |
| [`patterns/gateway-rbac-interceptor/`](./patterns/gateway-rbac-interceptor/) | None | Not applicable | Does not reach Neo4j | No, it has its own MCP server | Not applicable | Yes, its own MCP server | AgentCore Gateway, Cognito, Lambda |

The MCP `--env` column names the MCP server deployment that each sample uses:

- **`--env NAME`:** The command `./deploy.py --env fleet` reads `.env.fleet` and writes `.mcp-credentials.fleet.json`.
- **Default:** With no `--env`, `./deploy.py` reads `.env` and writes `.mcp-credentials.json`.
- **Credential sync:** The script [`scripts/sync-credentials.sh`](./scripts/sync-credentials.sh) copies each deployment's credentials to the samples that use it.

## Suggested learning path

Each step needs only what the earlier steps set up.

1. [`neo4j-mcp-server/`](./neo4j-mcp-server/) deploys the foundation.
2. [`quickstart/`](./quickstart/) makes the first Gateway call against the graph that the server points at.
3. [`demos/sec-filings-graphrag/`](./demos/sec-filings-graphrag/) introduces GraphRAG retrieval in one notebook.
4. [`demos/aircraft-fleet/`](./demos/aircraft-fleet/) loads the aviation graph and queries it with a direct-driver agent. It then deploys the MCP server with `--env fleet` and adds multi-agent routing with the supervisor.
5. [`demos/fraud-amazon-quick/`](./demos/fraud-amazon-quick/) combines Athena, Neo4j, agent memory, and Amazon Quick in one demo.

## Neo4j MCP server

Folder: [`neo4j-mcp-server/`](./neo4j-mcp-server/)

- **What it does:** This sample deploys the official Neo4j MCP server to AgentCore behind an AgentCore Gateway. Agents query Neo4j through MCP tools over one HTTPS endpoint secured with OAuth2.
- **Credentials:** Neo4j credentials live in container environment variables. This avoids a clash between the `Authorization` header that AgentCore uses and the one the Neo4j server expects.
- **Key features:** The sample uses AgentCore Runtime, a Gateway with Cognito machine-to-machine OAuth2, CDK infrastructure as code, and ARM64 Docker images. Agents discover the Neo4j tools, such as `get_neo4j_schema` and `read_neo4j_cypher`, at runtime.
- **Use case:** Use it to share one Neo4j database with Bedrock-hosted agents as MCP tools.

## Quickstart: LangGraph MCP agent

Folder: [`quickstart/`](./quickstart/)

- **What it does:** This standalone LangGraph ReAct agent answers plain-language questions about a Neo4j graph. It reaches Neo4j through the MCP server and the Gateway.
- **How it works:** The agent discovers the MCP tools at runtime. Claude on Bedrock then reads the schema and writes Cypher.
- **Key features:** The agent refreshes its Cognito OAuth2 token automatically. It calls Claude through the Bedrock Converse API and loads tools with `langchain-mcp-adapters`. A helper script sets up SageMaker Unified Studio inference profiles.
- **Use case:** Use it as a small, complete example of a Bedrock agent that queries Neo4j through the Gateway. It runs locally or in SageMaker Studio.

## Demos

### Aircraft fleet

Folder: [`demos/aircraft-fleet/`](./demos/aircraft-fleet/)

This end-to-end GraphRAG demo runs on Bedrock and Neo4j over an aircraft
digital twin fleet. Point every project at the same Neo4j instance with the
same embedder. The projects then work together with no code changes.

- **[`demos/aircraft-fleet/pipeline/`](./demos/aircraft-fleet/pipeline/):** The pipeline builds an operational graph in Neo4j from synthetic fleet data. It then reads maintenance manuals with `neo4j-graphrag`, using Bedrock Titan embeddings and Bedrock Claude entity extraction. The structured and extracted data end up in one Neo4j knowledge graph.
- **[`demos/aircraft-fleet/graphrag-agent/`](./demos/aircraft-fleet/graphrag-agent/):** This Strands ReAct agent answers questions over that graph. It connects to Neo4j directly with the driver. It combines Text2Cypher with vector search over the maintenance text chunks.
- **[`demos/aircraft-fleet/supervisor-agent/`](./demos/aircraft-fleet/supervisor-agent/):** This supervisor classifies each question and routes it to a Maintenance or Operations specialist agent. It then combines their answers. It reaches Neo4j through the MCP server and the Gateway with OAuth2.
- **Key features:** The command `pipeline/setup.sh` runs a five-stage Neo4j ingest. Entity extraction gets structured output from Bedrock by forcing `toolChoice`. The GraphRAG agent caches the live schema and deploys to AgentCore Runtime with `graphrag-agent/agent.sh`. The supervisor reports to CloudWatch.
- **Use case:** Use it as a reference for GraphRAG ingest on Bedrock and an agent over the result. One walkthrough runs it from start to finish.
- **Docs:** Start with the [`demos/aircraft-fleet/README.md`](./demos/aircraft-fleet/README.md) quick start. Then read the [`pipeline/`](./demos/aircraft-fleet/pipeline/README.md), [`graphrag-agent/`](./demos/aircraft-fleet/graphrag-agent/README.md), and [`supervisor-agent/`](./demos/aircraft-fleet/supervisor-agent/README.md) READMEs.

### Fraud investigation with Amazon Quick

Folder: [`demos/fraud-amazon-quick/`](./demos/fraud-amazon-quick/)

- **[`demos/fraud-amazon-quick/graph-loader/`](./demos/fraud-amazon-quick/graph-loader/):** The graph loader loads the fraud dataset into Neo4j with a direct driver. It can then add GDS fraud signals.
- **[`demos/fraud-amazon-quick/fraud-memory-agent/`](./demos/fraud-amazon-quick/fraud-memory-agent/):** This Strands agent investigates the synthetic fraud graph. It has `core/`, `client/`, and `server/` folders. It saves every turn in the Neo4j Agent Memory Service.
- **[`demos/fraud-amazon-quick/fraud-iceberg/`](./demos/fraud-amazon-quick/fraud-iceberg/):** This loader writes the same fraud dataset to Iceberg tables in S3 Tables so Athena can query it.

### SEC filings GraphRAG

Folder: [`demos/sec-filings-graphrag/`](./demos/sec-filings-graphrag/)

- **What it does:** One notebook teaches four levels of GraphRAG retrieval over SEC 10-K filings. It uses Bedrock embeddings.

## Integrations and patterns

These samples connect Neo4j to other platforms and secure the Gateway.

### Neo4j Aura Agents

Folder: [`integrations/neo4j-aura-agents/`](./integrations/neo4j-aura-agents/)

- **What it does:** This Python client calls Neo4j Aura Agents over the REST API. You build an Aura Agent in the Neo4j console and ground it in AuraDB. Neo4j then exposes it as an external endpoint.
- **How it works:** The client handles OAuth2 against `api.neo4j.io`. You can call the agent from code, a CLI, or an interactive chat.
- **Key features:** The client caches tokens and refreshes them automatically. It has sync and async versions. Responses are Pydantic models that include the agent's thinking and token usage.
- **Use case:** Use it to call a graph-grounded agent that Neo4j Aura hosts for you. You deploy no AWS infrastructure. It is the managed counterpart to the self-hosted AgentCore agents in this repo.

### Databricks

Folder: [`integrations/databricks/`](./integrations/databricks/)

- **What it does:** This integration connects Databricks workspaces to the Neo4j MCP server on AgentCore. A Unity Catalog HTTP connection forwards MCP requests from Databricks notebooks and LangGraph agents to the AgentCore Gateway.
- **Authentication:** The connection uses OAuth2 machine-to-machine auth through Cognito. Databricks refreshes the token for you.
- **Why AgentCore:** The official Neo4j MCP server is a compiled Go binary. Databricks Apps cannot host it, so the recommended pattern is to run it on AgentCore.
- **Key features:** The sample includes a LangGraph agent deployed with MLflow. Neo4j access is read-only.
- **Use case:** Use it when Databricks teams want to query Neo4j in plain language, or deploy agents that combine Spark processing with the graph.

### Gateway RBAC interceptor

Folder: [`patterns/gateway-rbac-interceptor/`](./patterns/gateway-rbac-interceptor/)

- **What it does:** This demo adds role-based access control to an OAuth2 Gateway with a Lambda interceptor. It uses the same Gateway layer that fronts the Neo4j MCP server.
- **How it works:** Cognito authenticates each caller. The Lambda interceptor reads the JWT claims and allows or denies each request based on `cognito:groups`.
- **Key features:** The demo supports both machine-to-machine and user OAuth flows. The interceptor passes identity headers to the downstream tools. Shell scripts wrap the deploy and test steps.
- **Use case:** Use it to secure MCP tools behind the Gateway for multiple tenants or for compliance needs.

## Documentation

- **[`CLAUDE.md`](CLAUDE.md):** This file lists detailed commands for Claude Code and for developers.
- **[`demos/aircraft-fleet/README.md`](demos/aircraft-fleet/README.md):** This walkthrough builds a GraphRAG ingest pipeline on Bedrock, loads the aircraft digital twin graph into Neo4j, and runs an agent over it.
