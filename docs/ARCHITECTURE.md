# Architecture Overview

This repository deploys the official Neo4j MCP server to Amazon Bedrock AgentCore and builds AI agents that query Neo4j. Some agents reach Neo4j through the AgentCore Gateway and the MCP server. Others connect with a direct Neo4j driver. This document covers the MCP server deployment first and the aircraft fleet agents second.

## Table of Contents

1. [System Overview](#system-overview)
2. [Neo4j MCP Server Deployment](#neo4j-mcp-server-deployment)
   - [High-Level Architecture](#high-level-architecture)
   - [Component Descriptions](#component-descriptions)
   - [Deployment Flow](#deployment-flow)
   - [CDK Stack Components](#cdk-stack-components)
   - [Authentication Architecture](#authentication-architecture)
3. [AI Agents Architecture](#ai-agents-architecture)
   - [Aircraft Fleet GraphRAG Agent](#aircraft-fleet-graphrag-agent)
   - [Supervisor Agent](#supervisor-agent)
   - [Agent Memory](#agent-memory)
4. [End-to-End Request Flow](#end-to-end-request-flow)
5. [Technology Stack Summary](#technology-stack-summary)
6. [Diagrams](#diagrams)
7. [References](#references)

---

## System Overview

![System overview: MCP clients reach Neo4j through Cognito, the AgentCore Gateway, and the AgentCore Runtime, while direct-driver projects connect to Neo4j over Bolt](images/system-overview.svg)

The repository has three parts.

- **Neo4j MCP server:** The [official Neo4j MCP server](https://github.com/neo4j/mcp) is written in Go. The build reads a local clone from the path in `NEO4J_MCP_REPO`.
- **MCP server deployment:** The `neo4j-mcp-server/` project uses AWS CDK to deploy the MCP server on AgentCore Runtime behind an AgentCore Gateway.
- **AI agents and demos:** The `quickstart/` and `demos/` projects query Neo4j in two ways.

The two access paths serve different needs.

| Path | Projects | How they reach Neo4j |
|------|----------|----------------------|
| MCP through the Gateway | Quickstart agent, fleet supervisor agent, fraud memory agent | Cognito token, AgentCore Gateway, AgentCore Runtime, Neo4j MCP server |
| Direct driver | Fleet pipeline, fleet GraphRAG agent, fraud graph loader, SEC filings notebook | Neo4j Python driver over Bolt |

- **Read-only MCP server:** The deployed MCP server runs with `NEO4J_READ_ONLY=true`. Agents on the MCP path get two tools, `get_neo4j_schema` and `read_neo4j_cypher`.
- **Writes:** Every write to Neo4j happens on the direct-driver path. The fleet pipeline and the fraud graph loader populate their graphs this way.

---

## Neo4j MCP Server Deployment

### High-Level Architecture

The `neo4j-mcp-server` project deploys one CloudFormation stack per deployment. Agents call the Gateway with a Cognito token. The Gateway calls the Runtime with a token of its own.

![Neo4j MCP server on AgentCore: the six-step request path from the agent through Cognito, the Gateway, the Gateway Target, the OAuth2 provider, and the Runtime to Neo4j](images/mcp-server-architecture.svg)

1. **Get a token:** The agent posts the `client_credentials` grant to Cognito and gets a JWT.
2. **Call the Gateway:** The agent sends the MCP request to the Gateway with the JWT as a bearer token.
3. **Validate:** The Gateway validates the JWT against the Cognito discovery URL. It accepts only tokens issued to the machine client.
4. **Get a Runtime token:** The Gateway Target gets a Runtime token from the OAuth2 credential provider.
5. **Forward:** The Gateway Target forwards the request to the Runtime with that token.
6. **Run the tool:** The Neo4j MCP server runs read-only Cypher on Neo4j and returns the result.

### Component Descriptions

#### AgentCore Runtime

AgentCore Runtime is a serverless compute environment for agents and tools. The MCP server container runs here.

- **MicroVM isolation:** Each session runs in its own microVM with isolated CPU, memory, and filesystem. The microVM is terminated and its memory is wiped when the session ends.
- **Long-running sessions:** A session can run for up to 8 hours.
- **Framework agnostic:** The Runtime hosts any agent framework or MCP server that meets its container contract.
- **Container contract:** The image must be arm64. An MCP server listens on port 8000 at `/mcp`.

**In this deployment:** The Runtime hosts the Neo4j MCP server with `protocol_configuration` set to `MCP`. It has its own custom JWT authorizer, which accepts only tokens issued to the stack's machine client. The container runs with `NEO4J_READ_ONLY=true`.

#### AgentCore Gateway

AgentCore Gateway is a managed front door that gives agents one MCP endpoint for many tool sources.

- **Protocol translation:** The Gateway turns MCP requests into calls to its targets.
- **Inbound auth:** The Gateway verifies each agent's identity before it forwards a request.
- **Outbound auth:** The Gateway attaches credentials when it calls a target.
- **Composition:** One Gateway can combine MCP servers, Lambda functions, and APIs behind one endpoint.
- **Semantic tool search:** The Gateway can index tools for semantic search. This stack does not enable it.

**In this deployment:** The Gateway is named `{stack}-gateway`. It uses a `CUSTOM_JWT` authorizer that allows only the machine client. It supports MCP protocol version `2025-03-26`.

#### Gateway Target

A Gateway Target tells the Gateway how to reach one backend and which credentials to use.

- **Endpoint:** The target holds the URL of the backend.
- **Credential provider:** The target names the OAuth2 provider the Gateway uses for outbound calls.
- **Tool indexing:** The Gateway calls the target's `tools/list` when the target is created.
- **Tool names:** Gateway tool names carry the target name as a prefix, as in `neo4j-mcp-server-target___read_neo4j_cypher`.

**In this deployment:** The target is named `neo4j-mcp-server-target`. Its endpoint is the Runtime invocation URL. It requests the `{stack}-mcp/invoke` scope from the OAuth2 provider.

#### OAuth2 Credential Provider

The OAuth2 credential provider is an AgentCore Identity resource. It stores OAuth2 client credentials and fetches tokens for the Gateway.

- **Secure storage:** AgentCore Identity stores the client secret in AWS Secrets Manager.
- **Token handling:** The provider gets new tokens when the Gateway needs them.
- **Two-legged OAuth:** The provider uses the machine-to-machine `client_credentials` flow.

**In this deployment:** The provider is named `{stack}_oauth_provider`. It holds the Cognito machine client ID and secret, so the Gateway can get Runtime tokens.

#### Custom Resource Lambdas

Two Python 3.12 Lambda functions run as CloudFormation custom resources during stack create, update, and delete.

- **OAuth provider function:** This function creates the OAuth2 credential provider. CloudFormation has no native resource for it, so the function calls the AgentCore Identity API directly.
- **Runtime health check function:** This function waits for the Runtime to reach `READY`. The Gateway Target depends on it, so the Gateway never indexes a Runtime that is still starting.

#### Amazon Cognito

Cognito issues the OAuth2 tokens. This deployment uses it only for machine-to-machine auth, so the user pool has no users.

- **User pool:** The pool has self sign-up disabled.
- **Domain:** The domain prefix is `{stack}-{account}`. It provides the `/oauth2/token` endpoint.
- **Resource server:** The resource server has the identifier `{stack}-mcp` and one scope, `invoke`.
- **Machine client:** The client has a secret and uses the `client_credentials` grant with the `{stack}-mcp/invoke` scope. Its access tokens are valid for 24 hours.

#### Amazon ECR

ECR stores the Neo4j MCP server image. `deploy.py` tags each build with the git SHA and with `latest`. The Runtime pulls the image by the URI in the `ECRImageUri` parameter.

#### AWS Secrets Manager

Secrets Manager stores the Neo4j password. `deploy.py` writes the secret and passes only its ARN to the stack. CloudFormation resolves the password into the Runtime environment at deploy time with a `{{resolve:secretsmanager}}` dynamic reference, so the password never appears in the template.

#### Amazon CloudWatch

CloudWatch receives the Runtime logs under `/aws/bedrock-agentcore/`. The agent execution role also allows X-Ray traces and metrics in the `bedrock-agentcore` namespace.

### Deployment Flow

`deploy.py` runs every deployment step in order. It reads `.env` by default. `--env NAME` reads `.env.NAME` instead, adds the suffix to the stack name, and writes `.mcp-credentials.NAME.json`.

![MCP server deploy flow: six steps from reading the config to writing credentials, with the steps each deploy.py command runs](images/mcp-deploy-flow.svg)

1. **Read the config:** `deploy.py` reads the `.env` file for the chosen deployment.
2. **Build the image:** Docker buildx builds the server from `NEO4J_MCP_REPO` for `linux/arm64`.
3. **Push to ECR:** The image gets a git SHA tag and the `latest` tag. The `IMAGE_TAG` environment variable overrides the SHA tag.
4. **Store the password:** The Neo4j password goes to Secrets Manager.
5. **Deploy the stack:** CDK deploys the stack with the image URI and the secret ARN as parameters.
6. **Write credentials:** `./deploy.py credentials` writes the Gateway URL, the client credentials, the token URL, and a fresh token.

| Command | Description |
|---------|-------------|
| `./deploy.py` | Runs a full deployment: build, push, and stack |
| `./deploy.py --skip-build` | Runs a full deployment with the image already in ECR |
| `./deploy.py redeploy` | Builds and pushes a new image, then points the existing Runtime at it |
| `./deploy.py stack` | Stores the password and deploys the CDK stack only |
| `./deploy.py synth` | Synthesizes the CloudFormation template without deploying |
| `./deploy.py status` | Shows the stack status and outputs |
| `./deploy.py credentials` | Writes the credentials file |
| `./deploy.py stack-name` | Prints the stack name for the chosen deployment |
| `./deploy.py cleanup` | Deletes the stack and the ECR repository |

- **Named deployments:** `./deploy.py --env fleet` deploys the stack `neo4j-mcp-server-fleet` for the supervisor agent. `./deploy.py --env finance` deploys `neo4j-mcp-server-finance` for the fraud memory agent.
- **Credential sync:** `scripts/sync-credentials.sh` copies each deployment's credentials file to the samples that use it.

### CDK Stack Components

The CDK stack in `cdk/neo4j_mcp_stack.py` builds every resource. Each resource name carries the stack name, so deployments do not collide.

![CDK stack components: Cognito resources, AgentCore resources, and the IAM roles and Lambda custom resources that support them](images/cdk-stack-components.svg)

| Resource | Type | Purpose |
|----------|------|---------|
| User pool | `cognito.UserPool` | OAuth2 identity provider with no users |
| User pool domain | `cognito.UserPoolDomain` | Hosts the `/oauth2/token` endpoint |
| Resource server | `cognito.CfnUserPoolResourceServer` | Defines the `{stack}-mcp/invoke` scope |
| Machine client | `cognito.CfnUserPoolClient` | M2M client with a secret and 24-hour tokens |
| Custom resource role | `iam.Role` | Lets the Lambdas call Cognito, AgentCore Identity, and Secrets Manager |
| Agent execution role | `iam.Role` | Gives the Runtime ECR pull, logs, X-Ray, metrics, and workload tokens |
| Gateway execution role | `iam.Role` | Lets the Gateway get OAuth2 tokens and invoke this Runtime only |
| OAuth provider function | `lambda_.Function` | Creates the OAuth2 credential provider |
| Runtime health check function | `lambda_.Function` | Waits for the Runtime to reach `READY` |
| MCP server Runtime | `bedrockagentcore.CfnRuntime` | Hosts the MCP server container with a JWT authorizer |
| Gateway | `bedrockagentcore.CfnGateway` | Entry point with a `CUSTOM_JWT` authorizer |
| Gateway Target | `bedrockagentcore.CfnGatewayTarget` | Routes tool calls to the Runtime with OAuth2 credentials |

The stack takes six parameters.

| Parameter | Description |
|-----------|-------------|
| `ECRImageUri` | The MCP server image in ECR |
| `Neo4jUri` | The Neo4j URI. It must start with `neo4j://`, `neo4j+s://`, or `neo4j+ssc://`. |
| `Neo4jDatabase` | The database name. The default is `neo4j`. |
| `Neo4jUsername` | The database user. The default is `neo4j`. |
| `Neo4jPasswordSecretArn` | The Secrets Manager ARN of the Neo4j password |
| `NetworkMode` | The Runtime network mode, `PUBLIC` or `PRIVATE`. The default is `PUBLIC`. |

- **Runtime environment:** The container gets `NEO4J_URI`, `NEO4J_DATABASE`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD`. It also gets `NEO4J_TRANSPORT=http`, port `8000`, path `/mcp`, and `NEO4J_READ_ONLY=true`.
- **Outputs:** The stack exports the Runtime ID, ARN, and invocation URL, the Gateway URL, ID, and target name, the Cognito pool ID, client ID, token URL, and scope, and the agent execution role ARN. `./deploy.py credentials` reads these outputs.

### Authentication Architecture

The system uses machine-to-machine OAuth2. One Cognito machine client backs both tokens. The agent's token gets it into the Gateway. The Gateway's token gets it into the Runtime.

![Machine-to-machine auth sequence: the agent gets a JWT from Cognito, the Gateway validates it, gets a Runtime token from the OAuth2 provider, and the Runtime runs read-only Cypher on Neo4j](images/m2m-auth-sequence.svg)

1. **Get a token:** The agent posts `client_credentials` to the Cognito `/oauth2/token` endpoint and gets a JWT.
2. **Call the Gateway:** The agent sends an MCP request with the JWT. The Gateway checks the issuer and the allowed client.
3. **Gateway to Runtime:** The Gateway gets a Runtime token from the OAuth2 provider and forwards the request with it.
4. **Run the tool:** The Runtime checks the allowed client. The MCP server runs read-only Cypher with the password that CloudFormation resolved from Secrets Manager. The response returns through the Runtime and the Gateway.

Machine-to-machine auth through the Gateway has these benefits.

- **No user management:** The user pool has no users, so there are no user passwords to rotate.
- **Simple agent auth:** Agents use client credentials instead of an interactive login.
- **One entry point:** The Gateway gives every agent one MCP endpoint.
- **Managed outbound tokens:** The Gateway gets and refreshes the Runtime token on its own.
- **Locked-down Runtime:** The Runtime accepts only tokens issued to the stack's machine client.

---

## AI Agents Architecture

The aircraft fleet demo in `demos/aircraft-fleet/` has two agents over the same graph. The GraphRAG agent uses a direct Neo4j driver. The supervisor agent uses the MCP Gateway. See the [aircraft fleet architecture diagram](../demos/aircraft-fleet/docs/images/architecture.svg) for how the pipeline, the agents, and the two Neo4j databases fit together.

### Aircraft Fleet GraphRAG Agent

The GraphRAG agent in `graphrag-agent/` is a single Strands agent. It connects to Neo4j with the Neo4j Python driver and does not use the MCP server or the Gateway.

![GraphRAG agent request flow: the Strands agent loads the live schema, then calls graph_query_tool or vector_search_tool against Neo4j](../demos/aircraft-fleet/docs/images/graphrag-request-flow.svg)

- **Live schema:** The agent reads the graph schema from Neo4j and puts it in the system prompt. It caches the schema for 10 minutes. `SCHEMA_TTL_S` changes the cache time.
- **Graph query tool:** `graph_query_tool` handles exact lookups, counts, aggregations, and traversals. It turns the question into Cypher with the `neo4j-graphrag` Text2Cypher retriever.
- **Read-only guard:** The graph query tool runs `EXPLAIN` on the generated Cypher first and rejects any query that writes. It also applies a query timeout and a row cap.
- **Vector search tool:** `vector_search_tool` handles descriptive questions. It uses the `HybridCypherRetriever` over the `maintenanceChunkEmbeddings` vector index and the `maintenanceChunkText` fulltext index.
- **Matching embedder:** The query embedder must match the one the pipeline used to load the chunks.
- **Direct modes:** A request can skip the agent loop and run the schema, graph query, or vector search step directly.
- **Streaming:** The server streams `tool`, `chunk`, `complete`, and `error` events as server-sent events.
- **Secrets:** On AgentCore Runtime, the agent reads the Neo4j passwords from Secrets Manager.

| Component | Technology | Purpose |
|-----------|------------|---------|
| LLM | Claude Sonnet 5.5 on Bedrock, global inference profile | Reasoning and answer writing |
| Agent framework | Strands `Agent` | Tool calling and streamed answers |
| Retrieval | `neo4j-graphrag` Text2Cypher and `HybridCypherRetriever` | Cypher generation and hybrid search |
| Database access | Neo4j Python driver | Direct connection with no MCP or Gateway |
| Embeddings | Amazon Titan Text Embeddings v2 | Query embeddings for vector search |
| Memory | `Neo4jSessionManager` from `neo4j_agent_memory` | Session memory in a separate Neo4j database |

```bash
cd demos/aircraft-fleet/graphrag-agent
uv sync                   # Install dependencies
uv run fleet-server       # Run locally (port 7070)
uv run fleet-cli "How many aircraft are in the database?"
./agent.sh deploy         # Deploy to AgentCore Runtime
```

The agent reads `NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD` from the shared `.env` at the `aircraft-fleet` root. It also needs `MEM_NEO4J_URI` and `MEM_NEO4J_PASSWORD` for memory. See the [GraphRAG agent README](../demos/aircraft-fleet/graphrag-agent/README.md) for the full command list.

### Supervisor Agent

The supervisor agent in `supervisor-agent/` is a Strands agent with two specialist agents as tools. The specialists reach Neo4j through the AgentCore Gateway and the Neo4j MCP server. It needs the `fleet` deployment from `./deploy.py --env fleet`.

![Supervisor agent request flow: the supervisor picks a specialist tool, and each specialist calls get_neo4j_schema and read_neo4j_cypher through the Gateway](../demos/aircraft-fleet/docs/images/supervisor-request-flow.svg)

**Routing:**

- **Specialists as tools:** The supervisor has two tools, `maintenance_specialist` and `operations_specialist`.
- **A fresh agent per call:** `SpecialistTool` wraps a new specialist Agent with `Agent.as_tool` on each call. A Strands agent serves one call at a time, so a fresh agent keeps parallel calls apart.
- **Routing by description:** The supervisor model picks a tool from the tool descriptions. No separate classifier runs.
- **Maintenance scope:** The maintenance description covers maintenance events, faults, components, systems, sensors, and severity.
- **Operations scope:** The operations description covers flights, delays, routes, airports, operators, and schedules. It also covers general questions such as the graph schema or simple counts.
- **One or both specialists:** The supervisor can call both specialists in one turn. Strands runs those tool calls concurrently. The supervisor then writes the final answer from the results.
- **Model-safe errors:** If a specialist fails, the supervisor model gets a generic error message. The details go to the server log.

**Gateway access:**

- **One MCP client:** The server starts one Strands `MCPClient` against the Gateway URL on the first request. It filters the Gateway tool list down to `get_neo4j_schema` and `read_neo4j_cypher`. Both specialists share these two tools.
- **Local auth:** A local run uses the OAuth2 client credentials grant. It posts the client ID and secret from the credentials file to the Cognito `token_url`.
- **Cloud auth:** On AgentCore Runtime, the client gets an M2M token from AgentCore Identity. The Runtime holds no client secret.
- **Token refresh:** The client fetches a new token before the old one expires. A 401 response forces one refresh and one retry.
- **Reconnects:** The Gateway can end the MCP session, for example when it restarts. `GatewayTool` rebuilds the client and retries the call once.

| Agent | Handles | Example questions |
|-------|---------|-------------------|
| **Maintenance** | MaintenanceEvent, Component, Sensor, System, Fault | "Most common maintenance faults", "Hydraulic system issues" |
| **Operations** | Flight, Delay, Airport, Route, Operator | "Common delay causes", "Busiest routes" |

| Component | Technology | Purpose |
|-----------|------------|---------|
| Supervisor | Strands `Agent` | Picks specialists and writes the answer |
| Routing | Specialist tool descriptions | The supervisor model chooses a tool for each question |
| Specialists | Strands `Agent` wrapped with `Agent.as_tool` | Domain agents built fresh for each call |
| Graph tools | Strands `MCPClient` to the AgentCore Gateway | `get_neo4j_schema` and `read_neo4j_cypher` |
| Memory | `Neo4jSessionManager` from `neo4j_agent_memory` | Session memory in a separate Neo4j database |
| Server | `BedrockAgentCoreApp` | Streams answers as server-sent events |

```bash
cd demos/aircraft-fleet/supervisor-agent
uv sync                       # Install dependencies
./agent.sh start              # Run locally (port 7071)
./agent.sh test-maintenance   # Test routing to the Maintenance Agent
./agent.sh test-operations    # Test routing to the Operations Agent
./agent.sh deploy             # Deploy to AgentCore Runtime
```

### Agent Memory

Both fleet agents remember each session and what they learn about a user. Memory lives in its own Neo4j database, apart from the fleet graph.

![Memory lifecycle: how both fleet agents open, use, and close conversation memory](../demos/aircraft-fleet/docs/images/memory-lifecycle.svg)

- **Shared connection:** Each server opens one `SharedMemory` connection to the memory database.
- **Per-request sessions:** Each request gets its own `Neo4jSessionManager` for its session and user.
- **Extraction:** The memory library extracts entities from the conversation with Claude Sonnet 5.5.
- **Configuration:** The memory database comes from the `MEM_NEO4J_*` variables in the shared `.env`.

---

## End-to-End Request Flow

This flow follows one supervisor question from the user to Neo4j and back.

![End-to-end request: the supervisor routes to a new Maintenance Agent, which loops with Claude and calls read_neo4j_cypher through the Gateway and the MCP server until it has an answer](images/end-to-end-sequence.svg)

1. **Route:** The user asks the supervisor a question. Claude on Bedrock reads the supervisor prompt and the specialist tool specs, then calls `maintenance_specialist`.
2. **Build the specialist:** The supervisor builds a new Maintenance Agent for this call. The specialist sends its own prompt and the question to Claude.
3. **Tool loop:** Claude calls `read_neo4j_cypher`. The specialist sends the MCP call to the Gateway with its bearer JWT. The Gateway forwards it to the Runtime with a Runtime token, and the MCP server runs read-only Cypher on Neo4j. The loop repeats until Claude has an answer.
4. **Answer:** The specialist answer returns to the supervisor as a tool result. Claude writes the final answer, and the supervisor streams it to the user as server-sent events.

---

## Technology Stack Summary

| Layer | Technology | Purpose |
|-------|------------|---------|
| **MCP server** | Go, Neo4j driver | Read-only Cypher execution |
| **Container** | Docker buildx, arm64 | AgentCore Runtime image |
| **Infrastructure** | AWS CDK in Python | Infrastructure as code |
| **Runtime** | Amazon Bedrock AgentCore Runtime | MicroVM container hosting |
| **Gateway** | Amazon Bedrock AgentCore Gateway | One MCP endpoint with inbound and outbound auth |
| **Auth** | Amazon Cognito, AgentCore Identity | OAuth2 M2M tokens |
| **Secrets** | AWS Secrets Manager | Neo4j passwords |
| **Agents** | Strands Agents, LangGraph | Tool calling and multi-agent orchestration |
| **LLM** | Claude on Amazon Bedrock | Reasoning and tool selection |
| **Embeddings** | Amazon Titan Text Embeddings v2 | Fleet chunk and query embeddings |
| **Observability** | CloudWatch, X-Ray | Logs, traces, and metrics |

The projects use different Claude models.

| Model | Used by |
|-------|---------|
| Claude Sonnet 5.5 | Both fleet agents, fleet pipeline extraction, and fleet memory extraction |
| Claude Haiku 4.5 | The quickstart agent and the fraud memory agent by default |
| Claude Sonnet 4.6 | The SEC filings notebook |

---

## Diagrams

| Diagram | Shows |
|---------|-------|
| [`system-overview.svg`](images/system-overview.svg) | The MCP path and the direct-driver path to Neo4j |
| [`mcp-server-architecture.svg`](images/mcp-server-architecture.svg) | The MCP server stack and its six-step request path |
| [`mcp-deploy-flow.svg`](images/mcp-deploy-flow.svg) | The `deploy.py` steps and which commands run them |
| [`cdk-stack-components.svg`](images/cdk-stack-components.svg) | The resources the CDK stack builds and how they connect |
| [`m2m-auth-sequence.svg`](images/m2m-auth-sequence.svg) | The machine-to-machine token flow from agent to Neo4j |
| [`end-to-end-sequence.svg`](images/end-to-end-sequence.svg) | One supervisor question through a specialist and the Gateway |
| [`architecture.svg`](../demos/aircraft-fleet/docs/images/architecture.svg) | The aircraft fleet demo components |
| [`graphrag-request-flow.svg`](../demos/aircraft-fleet/docs/images/graphrag-request-flow.svg) | One GraphRAG agent request |
| [`supervisor-request-flow.svg`](../demos/aircraft-fleet/docs/images/supervisor-request-flow.svg) | One supervisor agent request |
| [`memory-lifecycle.svg`](../demos/aircraft-fleet/docs/images/memory-lifecycle.svg) | How the fleet agents use conversation memory |

---

## References

### AWS Documentation

- [Amazon Bedrock AgentCore Overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html)
- [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
- [MCP Server Targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html)
- [Adding Gateway Targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-building-adding-targets.html)
- [AWS CDK Custom Resources](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.custom_resources-readme.html)
- [Lambda-backed Custom Resources](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/template-custom-resources-lambda.html)

### Project Resources

- [Neo4j MCP Server](https://github.com/neo4j/mcp)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Strands Agents](https://strandsagents.com/)
- [LangGraph Multi-Agent](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- [AWS CDK Python Reference](https://docs.aws.amazon.com/cdk/api/v2/python/)
