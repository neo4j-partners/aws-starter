# Attempt of Running Neo4j MCP Server on Amazon Bedrock AgentCore

This project does not work. Please see STATUS.md for details.

Deploy a Neo4j MCP server to Amazon Bedrock AgentCore with OAuth2 M2M authentication using AWS CDK.

## Overview

This project deploys an MCP (Model Context Protocol) server to AWS Bedrock AgentCore, enabling LLM agents to securely access Neo4j databases. It demonstrates production-ready patterns for:

- **OAuth2 M2M Authentication**: Machine-to-machine authentication using Cognito client credentials
- **AgentCore Gateway**: Public HTTPS endpoint with JWT validation
- **Credential Injection**: Secure Neo4j credential management via Secrets Manager

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS Account                                     │
│                                                                             │
│  ┌──────────────┐    ┌──────────────────────────────────────────────────┐  │
│  │   Cognito    │    │           AgentCore Gateway                       │  │
│  │  User Pool   │◀───│  - Public HTTPS endpoint                         │  │
│  │  + M2M Client│    │  - JWT validation (machine_client)               │  │
│  └──────────────┘    │  - OAuth2 token acquisition for Runtime          │  │
│         │            └──────────────────────────────────────────────────┘  │
│         │                              │                                    │
│         │ OAuth2                       │ M2M Token                          │
│         │ Token                        ▼                                    │
│         │            ┌──────────────────────────────────────────────────┐  │
│  ┌──────▼──────┐    │           AgentCore Runtime                        │  │
│  │   OAuth2    │    │  - MCP Server container (ECR)                      │  │
│  │  Credential │◀───│  - JWT validation (same machine_client)            │  │
│  │  Provider   │    │  - Credential interceptor (Lambda)                 │  │
│  └─────────────┘    └──────────────────────────────────────────────────┘  │
│                                        │                                    │
│                                        ▼                                    │
│                      ┌──────────────────────────────────────────────────┐  │
│                      │        Secrets Manager                            │  │
│                      │  - Neo4j URI, username, password                  │  │
│                      └──────────────────────────────────────────────────┘  │
│                                        │                                    │
└────────────────────────────────────────┼────────────────────────────────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   Neo4j Database    │
                              │   (Aura or self-    │
                              │    hosted)          │
                              └─────────────────────┘
```

### Key Components

| Component | Purpose |
|-----------|---------|
| **Cognito User Pool** | OAuth2 identity provider with M2M client |
| **AgentCore Gateway** | Public HTTPS endpoint with JWT authentication |
| **AgentCore Runtime** | Container runtime for MCP server |
| **OAuth2 Credential Provider** | Enables Gateway to acquire M2M tokens |
| **Credential Interceptor** | Lambda that injects Neo4j credentials |
| **Secrets Manager** | Secure storage for Neo4j credentials |

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- AWS CLI configured with appropriate credentials
- Node.js 20+ (for CDK)

### 1. Install Dependencies

```bash
uv sync --no-install-project
```

### 2. Configure Neo4j Credentials

Create a `.env` file with your Neo4j credentials:

```bash
NEO4J_URI=neo4j+s://xxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
NEO4J_DATABASE=neo4j
```

The deployment script will automatically update Secrets Manager with these credentials.

### 3. Deploy

```bash
./deploy.sh
```

Or manually with CDK:

```bash
JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run cdk deploy
```

Deployment takes approximately 3-5 minutes. If you used the deploy script with `.env` configured, credentials are automatically set.

### 4. Test

```bash
uv run python client/demo.py
```

### 5. Cleanup

```bash
uv run cdk destroy
```

## Project Structure

```
neo4j-mcp-server/
├── app.py                    # CDK app entry point
├── neo4j_mcp_stack.py        # Main CDK stack (all infrastructure)
├── cdk.json                  # CDK configuration
├── pyproject.toml            # Python dependencies
├── infra_utils/
│   ├── __init__.py
│   ├── build_trigger.py      # CodeBuild trigger Lambda
│   ├── oauth_provider.py     # OAuth2 provider Lambda
│   └── credential_interceptor.py  # Neo4j credential injection
└── client/
    └── demo.py               # OAuth2 M2M demo client
```

## Stack Outputs

| Output | Description |
|--------|-------------|
| `GatewayUrl` | AgentCore Gateway HTTPS endpoint |
| `CognitoUserPoolId` | Cognito User Pool ID |
| `CognitoMachineClientId` | M2M Client ID for authentication |
| `CognitoTokenUrl` | Token endpoint for OAuth2 |
| `RuntimeArn` | MCP Server Runtime ARN |
| `Neo4jSecretArn` | Secrets Manager ARN for Neo4j credentials |
| `CredentialInterceptorArn` | Credential injection Lambda ARN |

## Authentication Flow

```
┌──────────┐                ┌──────────┐                ┌──────────┐                ┌──────────┐
│  Client  │                │ Cognito  │                │ Gateway  │                │ Runtime  │
└────┬─────┘                └────┬─────┘                └────┬─────┘                └────┬─────┘
     │                           │                           │                           │
     │  1. POST /oauth2/token    │                           │                           │
     │   grant_type=client_creds │                           │                           │
     │   scope=neo4j-mcp/invoke  │                           │                           │
     │ ─────────────────────────>│                           │                           │
     │                           │                           │                           │
     │  2. Access Token (JWT)    │                           │                           │
     │ <─────────────────────────│                           │                           │
     │                           │                           │                           │
     │  3. POST /mcp             │                           │                           │
     │   Authorization: Bearer   │                           │                           │
     │ ──────────────────────────────────────────────────────>                           │
     │                           │                           │                           │
     │                           │  4. Validate JWT          │                           │
     │                           │ <─────────────────────────│                           │
     │                           │                           │                           │
     │                           │  5. Acquire M2M token     │                           │
     │                           │   (OAuth2 Provider)       │                           │
     │                           │ <─────────────────────────│                           │
     │                           │                           │                           │
     │                           │                           │  6. Invoke Runtime        │
     │                           │                           │   Authorization: Bearer   │
     │                           │                           │ ─────────────────────────>│
     │                           │                           │                           │
     │                           │                           │  7. Validate JWT          │
     │                           │                           │ <─────────────────────────│
     │                           │                           │                           │
     │                           │                           │  8. Fetch Neo4j creds     │
     │                           │                           │   from Secrets Manager    │
     │                           │                           │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ >│
     │                           │                           │                           │
     │                           │                           │  9. MCP Response          │
     │ <──────────────────────────────────────────────────────────────────────────────────
     │                           │                           │                           │
```

**Key Points:**
- Single M2M client used for all authentication (Gateway + Runtime)
- Gateway acquires its own token to call Runtime via OAuth2 Credential Provider
- Runtime fetches Neo4j credentials from Secrets Manager at request time

## Deployment Phases

The CDK stack deploys in phases to ensure proper ordering:

| Phase | Resources | Wait Condition |
|-------|-----------|----------------|
| 1 | ECR, Cognito, IAM roles, CodeBuild | Image build completes |
| 2 | AgentCore Runtime | - |
| 3 | RuntimeReady custom resource | Runtime status = READY |
| 4 | AgentCore Gateway | - |
| 5 | Gateway Target with OAuth2 | Depends on phase 3 |

This phased approach prevents the "Unable to connect to MCP server" error that occurs when creating a Gateway Target before the Runtime is fully ready.

---

## Project Status

**This project is BLOCKED due to an unsolvable HTTP Authorization header conflict.**

Both AWS AgentCore and the Neo4j MCP server require the `Authorization` header for different purposes (OAuth JWT vs Neo4j Basic credentials), and HTTP only allows one Authorization header per request.

See **[STATUS.md](STATUS.md)** for:
- Complete technical analysis of the problem
- All approaches attempted and their results
- Lessons learned
- Recommendations for alternative approaches

The custom Python MCP server in this repository provides a **working single-tenant solution** using AWS Secrets Manager for credentials, but multi-tenant per-request authentication is not achievable with AgentCore's current architecture.

---

## Resources

- [Amazon Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [AWS CDK Python Reference](https://docs.aws.amazon.com/cdk/api/v2/python/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Neo4j MCP Server](https://github.com/neo4j/mcp)
- [AgentCore Samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples)
