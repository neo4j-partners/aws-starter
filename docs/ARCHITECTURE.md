# Architecture Overview

This document provides a comprehensive architecture overview of the Neo4j MCP ecosystem deployed on Amazon Bedrock AgentCore, covering both the MCP server deployment and the AI agents that consume it.

## Table of Contents

1. [System Overview](#system-overview)
2. [Neo4j MCP Server Deployment](#neo4j-mcp-server-deployment)
   - [High-Level Architecture](#high-level-architecture)
   - [Deployment Flow](#deployment-flow)
   - [CDK Stack Components](#cdk-stack-components)
   - [Authentication Architecture](#authentication-architecture)
3. [AI Agents Architecture](#ai-agents-architecture)
   - [Basic Agent](#basic-agent)
   - [Orchestrator Agent (Multi-Agent)](#orchestrator-agent-multi-agent)
4. [End-to-End Request Flow](#end-to-end-request-flow)

---

## System Overview

The system consists of three main components:

1. **Neo4j MCP Server** (`/Users/ryanknight/projects/mcp`) - Official Neo4j Model Context Protocol server written in Go
2. **MCP Server Deployment** (`neo4j-agentcore-mcp-server/`) - AWS CDK infrastructure to deploy the MCP server on AgentCore
3. **AI Agents** (`agentcore-neo4j-mcp-agent/`) - LangGraph-based agents that query Neo4j via the MCP server

```mermaid
flowchart TB
    subgraph External["External Services"]
        NEO4J[(Neo4j Database<br/>Aura / Self-hosted)]
    end

    subgraph MCP["Neo4j MCP Server<br/>(Go Binary)"]
        direction TB
        TOOLS[MCP Tools<br/>get-schema, read-cypher, write-cypher]
        DB_SVC[Database Service<br/>Neo4j Driver]
        TOOLS --> DB_SVC
    end

    subgraph AWS["AWS Cloud"]
        subgraph AgentCore["Amazon Bedrock AgentCore"]
            RUNTIME[AgentCore Runtime<br/>MicroVM Container]
            GATEWAY[AgentCore Gateway<br/>Tool Aggregation]
        end

        subgraph Agents["AI Agents"]
            BASIC[Basic Agent<br/>Single ReAct Loop]
            ORCH[Orchestrator<br/>Multi-Agent Router]
        end

        subgraph Auth["Authentication"]
            COGNITO[Amazon Cognito<br/>M2M OAuth2]
        end
    end

    RUNTIME --> MCP
    MCP --> NEO4J
    GATEWAY --> RUNTIME
    BASIC --> GATEWAY
    ORCH --> GATEWAY
    BASIC --> COGNITO
    ORCH --> COGNITO
```

---

## Neo4j MCP Server Deployment

### High-Level Architecture

The `neo4j-agentcore-mcp-server` project deploys the official Neo4j MCP server to Amazon Bedrock AgentCore Runtime with Gateway authentication.

```mermaid
flowchart TB
    subgraph Client["AI Agent / Client"]
        APP[LangGraph Agent<br/>or MCP Client]
    end

    subgraph AWS["AWS Cloud"]
        subgraph Auth["Authentication Layer"]
            COGNITO[Amazon Cognito<br/>User Pool + Machine Client]
            OAUTH[OAuth2 Credential<br/>Provider]
        end

        subgraph AgentCore["Amazon Bedrock AgentCore"]
            GATEWAY[AgentCore Gateway<br/>JWT Authorizer]
            TARGET[Gateway Target<br/>OAuth Credentials]
            RUNTIME[AgentCore Runtime<br/>MicroVM Isolation]
            subgraph Container["Container"]
                MCP[Neo4j MCP Server<br/>Port 8000]
            end
        end

        subgraph Supporting["Supporting Services"]
            ECR[Amazon ECR<br/>Container Registry]
            CW[Amazon CloudWatch<br/>Logs & Metrics]
            LAMBDA[Custom Resource<br/>Lambdas]
        end
    end

    subgraph External["External"]
        NEO4J[(Neo4j Database<br/>Aura or Self-hosted)]
    end

    APP -->|1. Client Credentials| COGNITO
    COGNITO -->|2. M2M JWT Token| APP
    APP -->|3. MCP Request + JWT| GATEWAY
    GATEWAY -->|4. Validate JWT| COGNITO
    GATEWAY --> TARGET
    TARGET -->|5. Get OAuth Token| OAUTH
    TARGET -->|6. Forward + OAuth| RUNTIME
    RUNTIME --> Container
    MCP -->|7. Cypher Queries| NEO4J
    NEO4J -->|8. Results| MCP
    MCP -->|9. MCP Response| APP

    ECR -.->|Container Image| RUNTIME
    RUNTIME -.->|Logs & Traces| CW
    LAMBDA -.->|Create| OAUTH
```

### Deployment Flow

The `deploy.sh` script orchestrates the entire deployment process:

```mermaid
flowchart LR
    subgraph Local["Local Machine"]
        ENV[.env Config<br/>Neo4j Credentials]
        MCPREPO[Neo4j MCP Repo<br/>/Users/ryanknight/projects/mcp]
    end

    subgraph Build["Build Phase"]
        DOCKER[Docker Buildx<br/>ARM64 Image]
    end

    subgraph Push["Push Phase"]
        ECR[Amazon ECR<br/>Container Registry]
    end

    subgraph Deploy["Deploy Phase"]
        CDK[AWS CDK<br/>CloudFormation]
        STACK[Neo4j MCP Stack<br/>All Resources]
    end

    subgraph Output["Outputs"]
        GW_URL[Gateway URL]
        CREDS[Credentials File<br/>.mcp-credentials.json]
    end

    ENV --> DOCKER
    MCPREPO --> DOCKER
    DOCKER -->|neo4j-mcp-server:latest| ECR
    ECR --> CDK
    ENV --> CDK
    CDK --> STACK
    STACK --> GW_URL
    STACK --> CREDS
```

**Deployment Commands:**

| Command | Description |
|---------|-------------|
| `./deploy.sh` | Full deployment (build, push, stack) |
| `./deploy.sh redeploy` | Fast redeploy (build, push, update runtime) |
| `./deploy.sh stack` | Deploy CDK stack only |
| `./deploy.sh status` | Show stack status and outputs |
| `./deploy.sh credentials` | Generate `.mcp-credentials.json` |
| `./deploy.sh cleanup` | Delete all resources |

### CDK Stack Components

The CDK stack (`cdk/neo4j_mcp_stack.py`) creates these AWS resources:

```mermaid
flowchart TB
    subgraph CDK["CDK Stack: neo4j-agentcore-mcp-server"]
        subgraph CognitoModule["Cognito Module"]
            UP[User Pool<br/>No users - M2M only]
            DOMAIN[User Pool Domain<br/>OAuth2 Token Endpoint]
            RS[Resource Server<br/>mcp/invoke scope]
            MC[Machine Client<br/>client_credentials grant]
        end

        subgraph IAMModule["IAM Module"]
            AGENT_ROLE[Agent Execution Role<br/>ECR, CloudWatch, X-Ray]
            GW_ROLE[Gateway Execution Role<br/>Runtime Invoke, OAuth]
            CR_ROLE[Custom Resource Role<br/>Cognito, AgentCore APIs]
        end

        subgraph LambdaModule["Lambda Custom Resources"]
            OAUTH_FUNC[OAuth Provider Function<br/>Creates OAuth2 Credential Provider]
            HEALTH_FUNC[Runtime Health Check<br/>Waits for Runtime Ready]
        end

        subgraph AgentCoreModule["AgentCore Resources"]
            RUNTIME_RES[MCP Server Runtime<br/>CfnRuntime - Container + JWT Auth]
            GATEWAY_RES[Gateway<br/>CfnGateway - JWT Authorizer]
            TARGET_RES[Gateway Target<br/>CfnGatewayTarget - OAuth Credentials]
        end
    end

    UP --> DOMAIN
    UP --> RS
    RS --> MC
    MC --> RUNTIME_RES
    MC --> GATEWAY_RES

    AGENT_ROLE --> RUNTIME_RES
    GW_ROLE --> GATEWAY_RES
    CR_ROLE --> OAUTH_FUNC
    CR_ROLE --> HEALTH_FUNC

    OAUTH_FUNC -->|CustomResource| TARGET_RES
    HEALTH_FUNC -->|Wait for Ready| TARGET_RES
    RUNTIME_RES --> TARGET_RES
    GATEWAY_RES --> TARGET_RES
```

**Key CDK Constructs:**

| Resource | Type | Purpose |
|----------|------|---------|
| User Pool | `cognito.UserPool` | OAuth2 identity provider |
| Machine Client | `cognito.CfnUserPoolClient` | M2M client credentials |
| Agent Execution Role | `iam.Role` | Runtime permissions |
| MCP Server Runtime | `bedrockagentcore.CfnRuntime` | Container hosting |
| Gateway | `bedrockagentcore.CfnGateway` | Entry point with JWT auth |
| Gateway Target | `bedrockagentcore.CfnGatewayTarget` | Routes to Runtime |

### Authentication Architecture

The system uses machine-to-machine (M2M) OAuth2 authentication:

```mermaid
sequenceDiagram
    participant Agent as AI Agent
    participant Cognito as Amazon Cognito
    participant Gateway as AgentCore Gateway
    participant OAuth as OAuth Provider
    participant Runtime as AgentCore Runtime
    participant MCP as Neo4j MCP Server
    participant Neo4j as Neo4j Database

    Note over Agent,Neo4j: Step 1: Agent Authentication (M2M)
    Agent->>Cognito: POST /oauth2/token<br/>(client_credentials grant)
    Cognito-->>Agent: Access Token (JWT)

    Note over Agent,Neo4j: Step 2: MCP Request via Gateway
    Agent->>Gateway: MCP Request<br/>Authorization: Bearer JWT
    Gateway->>Gateway: Validate JWT<br/>(allowed_clients check)

    Note over Agent,Neo4j: Step 3: Gateway to Runtime Authentication
    Gateway->>OAuth: Get OAuth Token for Runtime
    OAuth-->>Gateway: Runtime Access Token
    Gateway->>Runtime: Forward Request + OAuth Token

    Note over Agent,Neo4j: Step 4: Execute Query
    Runtime->>MCP: MCP Tool Call
    MCP->>Neo4j: Cypher Query<br/>(env credentials)
    Neo4j-->>MCP: Query Results
    MCP-->>Runtime: MCP Response
    Runtime-->>Gateway: Response
    Gateway-->>Agent: MCP Response
```

**Why M2M-Only via Gateway:**

1. **No User Management** - No passwords to rotate, no users to create/delete
2. **Simplified Auth** - Agents use client credentials, not interactive login
3. **Centralized Access** - Gateway provides single entry point with audit logging
4. **Automatic Token Handling** - Gateway manages OAuth tokens with Runtime
5. **Tool Discovery** - Gateway enables semantic tool search across MCP servers
6. **Security Isolation** - Runtime only accepts Gateway traffic

---

## AI Agents Architecture

Two agent implementations are provided in `agentcore-neo4j-mcp-agent/`:

### Basic Agent

A single ReAct (Reasoning + Acting) agent that handles all queries using LangChain and LangGraph.

```mermaid
flowchart TB
    subgraph Input["Input"]
        USER[User Query]
    end

    subgraph BasicAgent["Basic Agent (simple-agent.py)"]
        LLM[Claude Sonnet 4<br/>via Bedrock Converse]
        REACT[ReAct Loop<br/>Thought → Action → Observation]
        TOOLS[MCP Tools<br/>get-schema, read-cypher]
    end

    subgraph MCP["MCP Server"]
        GATEWAY[AgentCore Gateway]
        MCPSERVER[Neo4j MCP Server]
    end

    subgraph External["External"]
        NEO4J[(Neo4j Database)]
    end

    USER --> REACT
    REACT <--> LLM
    REACT --> TOOLS
    TOOLS --> GATEWAY
    GATEWAY --> MCPSERVER
    MCPSERVER --> NEO4J

    style REACT fill:#e1f5fe
```

**Key Components:**

| Component | Technology | Purpose |
|-----------|------------|---------|
| LLM | Claude Sonnet 4 (Bedrock) | Reasoning and response generation |
| Agent Framework | LangChain `create_agent` | ReAct agent pattern |
| MCP Client | `langchain_mcp_adapters` | Tool discovery and invocation |
| Transport | Streamable HTTP | Gateway communication |

**Usage:**

```bash
cd basic-agent
./agent.sh setup          # Install dependencies
./agent.sh start          # Run locally (port 8080)
./agent.sh test           # Test local agent
python simple-agent.py "What is the database schema?"
```

### Orchestrator Agent (Multi-Agent)

A supervisor agent that routes queries to specialized domain experts using LangGraph StateGraph.

```mermaid
flowchart TB
    subgraph Input["Input"]
        USER[User Query]
    end

    subgraph Orchestrator["Orchestrator Agent"]
        ROUTER[Router Node<br/>Query Classification]

        subgraph Workers["Specialist Workers"]
            MAINT[Maintenance Agent<br/>Faults, Components, Sensors]
            OPS[Operations Agent<br/>Flights, Delays, Routes]
        end
    end

    subgraph MCP["MCP Server"]
        GATEWAY[AgentCore Gateway]
        MCPSERVER[Neo4j MCP Server]
    end

    subgraph External["External"]
        NEO4J[(Neo4j Database)]
    end

    USER --> ROUTER
    ROUTER -->|maintenance keywords| MAINT
    ROUTER -->|operations keywords| OPS
    MAINT --> GATEWAY
    OPS --> GATEWAY
    GATEWAY --> MCPSERVER
    MCPSERVER --> NEO4J

    style ROUTER fill:#fff3e0
    style MAINT fill:#e8f5e9
    style OPS fill:#e3f2fd
```

**StateGraph Architecture:**

```mermaid
stateDiagram-v2
    [*] --> Router: User Query
    Router --> Maintenance: maintenance keywords
    Router --> Operations: operations keywords
    Maintenance --> [*]: Response
    Operations --> [*]: Response

    note right of Router
        Classifies query using LLM:
        - maintenance, fault, component → Maintenance
        - flight, delay, route → Operations
    end note

    note right of Maintenance
        Domain expertise:
        - Aircraft health monitoring
        - Component reliability
        - Fault code analysis
        - Sensor data interpretation
    end note

    note right of Operations
        Domain expertise:
        - Flight scheduling
        - Delay analysis
        - Route management
        - Airline performance
    end note
```

**Agent State Flow:**

```mermaid
flowchart LR
    subgraph State["OrchestratorState"]
        MSG[messages: list]
        NEXT[next_agent: str]
    end

    subgraph Nodes["Graph Nodes"]
        R[router]
        M[maintenance]
        O[operations]
    end

    START((START)) --> R
    R -->|next_agent=maintenance| M
    R -->|next_agent=operations| O
    M --> END((END))
    O --> END
```

**Domain Specialists:**

| Agent | Handles | Example Queries |
|-------|---------|-----------------|
| **Maintenance** | MaintenanceEvent, Component, Sensor, System, Fault | "Most common maintenance faults", "Hydraulic system issues" |
| **Operations** | Flight, Delay, Airport, Route, Operator | "Common delay causes", "Busiest routes" |

**Key Components:**

| Component | Technology | Purpose |
|-----------|------------|---------|
| Orchestrator | LangGraph `StateGraph` | Multi-agent coordination |
| Router | Claude LLM + Classification Prompt | Query routing |
| Workers | LangGraph `create_react_agent` | Domain-specific ReAct agents |
| State | `TypedDict` with `add_messages` | Conversation history |
| Memory | `MemorySaver` | Session persistence |

**Usage:**

```bash
cd orchestrator-agent
./agent.sh setup              # Install dependencies
./agent.sh start              # Run locally (port 8080)
./agent.sh test-maintenance   # Test routing to Maintenance Agent
./agent.sh test-operations    # Test routing to Operations Agent
./agent.sh deploy             # Deploy to AgentCore Runtime
```

---

## End-to-End Request Flow

Complete flow from user query to Neo4j response:

```mermaid
sequenceDiagram
    participant User
    participant Agent as Orchestrator Agent
    participant Router
    participant Worker as Specialist Agent
    participant LLM as Claude Sonnet
    participant Gateway as AgentCore Gateway
    participant Runtime as AgentCore Runtime
    participant MCP as Neo4j MCP Server
    participant Neo4j

    User->>Agent: "What are the most common faults?"

    Note over Agent,Router: Step 1: Query Routing
    Agent->>Router: Classify query
    Router->>LLM: ROUTER_PROMPT + query
    LLM-->>Router: "maintenance"
    Router-->>Agent: next_agent = maintenance

    Note over Agent,Worker: Step 2: Specialist Processing
    Agent->>Worker: Forward to Maintenance Agent
    Worker->>LLM: MAINTENANCE_PROMPT + query

    Note over Worker,Neo4j: Step 3: Tool Execution (ReAct Loop)
    loop ReAct: Thought → Action → Observation
        LLM-->>Worker: Thought: Need to query faults
        Worker->>Gateway: MCP call_tool(read-cypher, query)
        Gateway->>Runtime: Forward with OAuth
        Runtime->>MCP: Execute tool
        MCP->>Neo4j: MATCH (m:MaintenanceEvent)...
        Neo4j-->>MCP: Results
        MCP-->>Runtime: Tool response
        Runtime-->>Gateway: Response
        Gateway-->>Worker: Observation: [fault data]
        Worker->>LLM: Observation + continue
    end

    Note over Worker,User: Step 4: Response
    LLM-->>Worker: Final answer
    Worker-->>Agent: Response message
    Agent-->>User: "The most common faults are..."
```

---

## Technology Stack Summary

| Layer | Technology | Purpose |
|-------|------------|---------|
| **MCP Server** | Go, Neo4j Driver | Cypher query execution |
| **Container** | Docker, ARM64 | Cross-platform deployment |
| **Infrastructure** | AWS CDK (Python) | Infrastructure as Code |
| **Runtime** | Bedrock AgentCore | MicroVM container hosting |
| **Gateway** | Bedrock AgentCore | Tool aggregation, auth |
| **Auth** | Amazon Cognito | OAuth2 M2M tokens |
| **Agents** | LangGraph, LangChain | Multi-agent orchestration |
| **LLM** | Claude Sonnet 4 (Bedrock) | Reasoning, tool selection |
| **Observability** | CloudWatch, X-Ray | Logs, traces, metrics |

---

## References

- [Neo4j MCP Server](https://github.com/neo4j/mcp)
- [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [LangGraph Multi-Agent](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- [AWS CDK Python Reference](https://docs.aws.amazon.com/cdk/api/v2/python/)
