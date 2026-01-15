# Deploying Neo4j MCP Server to AWS App Runner with Bearer Token Authentication

## Executive Summary

This proposal describes how to deploy the official Neo4j MCP server to AWS App Runner using AWS CDK with Python, configured for bearer token authentication with AWS Cognito as the identity provider and Neo4j Aura as the database. This deployment pattern enables machine-to-machine authentication where automated clients obtain JWT tokens from Cognito and present them to the MCP server, which forwards them to Neo4j for validation.

This approach works because App Runner provides a standalone HTTP environment without intermediate authentication layers that would consume the HTTP Authorization header. The bearer token flows directly from client to MCP server to Neo4j without interference.

---

## Architecture Overview

The deployment consists of four primary components working together to provide secure, authenticated access to Neo4j through the MCP protocol.

### Component Summary

**AWS Cognito User Pool**: Acts as the OAuth 2.0 authorization server, issuing JWT tokens to authenticated clients using the machine-to-machine client credentials grant. Cognito provides the OIDC-compliant endpoints that Neo4j uses to validate tokens.

**AWS App Runner Service**: Hosts the Neo4j MCP server container, receiving HTTP requests from clients, extracting bearer tokens from the Authorization header, and forwarding them with each database query.

**Neo4j Aura Instance**: The graph database configured with SSO pointing to Cognito as the OIDC identity provider. Neo4j validates each bearer token by fetching Cognito's JSON Web Key Set and verifying the token signature, expiration, and claims.

**MCP Clients**: Automated services, agents, or applications that obtain tokens from Cognito and invoke MCP tools through the App Runner endpoint.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    AWS Cloud                                         │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐│
│  │                           Authentication Flow                                    ││
│  │                                                                                  ││
│  │   ┌──────────────┐                              ┌──────────────────────────┐    ││
│  │   │              │  1. POST /oauth2/token       │                          │    ││
│  │   │  MCP Client  │  grant_type=client_creds     │   AWS Cognito User Pool  │    ││
│  │   │  (AI Agent,  │ ────────────────────────────>│                          │    ││
│  │   │   Backend)   │                              │   - Machine App Client   │    ││
│  │   │              │  2. JWT Access Token         │   - Resource Server      │    ││
│  │   │              │ <────────────────────────────│   - Custom Scopes        │    ││
│  │   └──────┬───────┘                              │   - JWKS Endpoint        │    ││
│  │          │                                      └────────────┬─────────────┘    ││
│  │          │                                                   │                   ││
│  │          │                                                   │ 5. Fetch JWKS    ││
│  │          │                                                   │    (cached)      ││
│  │          │                                                   ▼                   ││
│  │          │ 3. POST /mcp                         ┌──────────────────────────┐    ││
│  │          │    Authorization: Bearer <jwt>       │                          │    ││
│  │          │    {"method": "tools/call", ...}     │   Neo4j Aura Instance    │    ││
│  │          │                                      │                          │    ││
│  │          ▼                                      │   - SSO/OIDC Configured  │    ││
│  │   ┌──────────────────────────────────┐          │   - Points to Cognito    │    ││
│  │   │                                  │          │   - Validates JWT        │    ││
│  │   │     AWS App Runner Service       │          │   - Maps Scopes to Roles │    ││
│  │   │                                  │          │                          │    ││
│  │   │   ┌────────────────────────┐     │          └────────────┬─────────────┘    ││
│  │   │   │                        │     │ 4. Query with         ▲                   ││
│  │   │   │  Neo4j MCP Server      │     │    BearerAuth(jwt)    │                   ││
│  │   │   │  Container (Go)        │─────┼───────────────────────┘                   ││
│  │   │   │                        │     │                                           ││
│  │   │   │  - HTTP Transport      │     │ 6. Query Results                         ││
│  │   │   │  - Extracts Bearer     │     │<──────────────────────                    ││
│  │   │   │  - Forwards to Neo4j   │     │                                           ││
│  │   │   │                        │     │                                           ││
│  │   │   └────────────────────────┘     │                                           ││
│  │   │                                  │                                           ││
│  │   │   Environment Variables:         │                                           ││
│  │   │   - NEO4J_URI                    │                                           ││
│  │   │   - NEO4J_MCP_TRANSPORT=http     │                                           ││
│  │   │   - NEO4J_MCP_HTTP_HOST=0.0.0.0  │                                           ││
│  │   │   - NEO4J_MCP_HTTP_PORT=8080     │                                           ││
│  │   │                                  │                                           ││
│  │   └──────────────────────────────────┘                                           ││
│  │                                                                                  ││
│  │   7. MCP Response returned to client                                             ││
│  │                                                                                  ││
│  └─────────────────────────────────────────────────────────────────────────────────┘│
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### Request Flow Sequence

1. **Token Acquisition**: The MCP client authenticates with Cognito's token endpoint using its client ID and client secret via the OAuth 2.0 client credentials grant. The client requests custom scopes that map to Neo4j database roles.

2. **Token Issuance**: Cognito validates the client credentials and issues a JWT access token. The token contains claims including the subject (client ID), issuer (Cognito user pool), audience (resource server identifier), expiration, and requested scopes.

3. **MCP Request**: The client sends an MCP protocol request to the App Runner endpoint, including the JWT in the HTTP Authorization header as a bearer token. The request body contains the JSON-RPC formatted MCP method call.

4. **Token Extraction and Forwarding**: The MCP server's authentication middleware extracts the bearer token from the Authorization header and stores it in the request context. When the tool handler executes a database query, the database service retrieves the token from context and uses the Neo4j driver's BearerAuth mechanism to authenticate the query.

5. **Token Validation**: Neo4j receives the query with the bearer token. It fetches the JSON Web Key Set from Cognito's JWKS endpoint (caching the keys for efficiency), validates the token signature, checks expiration, verifies the audience and issuer claims, and extracts the scopes.

6. **Authorization and Execution**: Neo4j maps the token's scopes to database roles using its configured group-to-role mapping. If the mapped role has permission, the query executes and results are returned.

7. **Response**: The MCP server formats the query results as an MCP protocol response and returns it to the client.

---

## How Bearer Token Authentication Works in the MCP Server

### HTTP Transport Mode

The Neo4j MCP server supports two transport modes: STDIO for local desktop clients and HTTP for web-based deployments. For App Runner deployment, HTTP transport mode is required because App Runner exposes services via HTTP endpoints.

In HTTP mode, the server starts an HTTP listener on a configurable host and port. The MCP protocol messages are exchanged as JSON-RPC requests and responses over HTTP POST requests to the server's endpoint path.

### Authentication Middleware

When the MCP server receives an HTTP request, it passes through authentication middleware before reaching the MCP protocol handler. The middleware examines the Authorization header to determine the authentication method.

For bearer token authentication, the middleware looks for an Authorization header with the "Bearer" prefix. If found, it extracts the token string (everything after "Bearer ") and stores it in the request context. The middleware does not validate the token itself; validation is deferred to Neo4j.

The middleware uses a method-aware authentication policy. Only the "tools/call" method, which executes database operations, requires authentication. Protocol handshake methods like "initialize" and capability discovery methods like "tools/list" are allowed without authentication. This enables health checks and service discovery without credentials.

### Per-Request Credentials

Unlike STDIO mode where credentials are configured once at startup, HTTP mode supports per-request credentials. Each incoming request can carry different credentials, enabling multi-tenant scenarios where different clients access Neo4j with different identities and permissions.

The MCP server achieves this by not establishing a persistent database connection at startup. Instead, each query execution retrieves credentials from the request context and uses the Neo4j driver's per-query authentication mechanism. This allows the same MCP server instance to serve requests from multiple clients with different access levels.

### Credential Priority

The MCP server's HTTP mode supports three credential sources in priority order:

1. **Bearer Token from Authorization Header**: If the request includes "Authorization: Bearer token", the bearer token is used with Neo4j's BearerAuth mechanism.

2. **Basic Auth from Authorization Header**: If the request includes "Authorization: Basic credentials", the username and password are decoded and used with Neo4j's BasicAuth mechanism.

3. **Environment Variable Fallback**: If no Authorization header is present but NEO4J_USERNAME and NEO4J_PASSWORD environment variables are configured, these credentials are used as a fallback.

For this deployment, only bearer token authentication is used. No username or password environment variables are configured, ensuring all authentication flows through Cognito-issued tokens.

### Token Flow to Neo4j

When a tool handler needs to execute a Cypher query, it calls the database service with the request context. The database service's query execution method checks if bearer token authentication is available in the context. If a bearer token is present, the service creates a Neo4j AuthToken using the driver's BearerAuth function and attaches it to the query execution options.

The Neo4j Go driver then includes this bearer token when communicating with the database over the Bolt protocol. Neo4j receives the token and performs validation according to its OIDC configuration.

---

## Cognito Configuration for Neo4j Authentication

### User Pool Setup

The Cognito User Pool serves as the OIDC authorization server. For machine-to-machine authentication, no actual users are created in the pool. Instead, the pool provides the OAuth 2.0 infrastructure: token endpoints, JWKS endpoints, and client credential management.

The user pool requires a domain to expose the token endpoint. This can be a Cognito-hosted domain (in the format prefix.auth.region.amazoncognito.com) or a custom domain. The domain provides the base URL for OAuth 2.0 endpoints.

### Resource Server Configuration

A resource server defines the API that clients will access and the scopes (permissions) available. For Neo4j access, the resource server represents the Neo4j database API.

The resource server identifier becomes part of the scope names and is included in the access token's audience claim. Neo4j uses this identifier to verify that tokens are intended for database access rather than some other service.

Custom scopes define the permissions clients can request. Each scope maps to a Neo4j database role. For example, a scope named "admin" might map to the Neo4j admin role, while a scope named "reader" might map to a read-only role. The scope names appear in the token's "scope" claim, which Neo4j uses for authorization.

### App Client for Machine-to-Machine

An app client represents an application that can request tokens. For M2M authentication, the app client must be configured as a confidential client with a client secret, and must have the client credentials grant type enabled.

The app client is associated with the resource server's scopes. Only scopes explicitly assigned to the app client can be requested in token requests. This allows different clients to have different permission levels.

### Token Characteristics

Tokens issued by Cognito for the client credentials grant have specific characteristics:

- **Token Type**: Access tokens (not ID tokens, which are for user authentication)
- **Format**: JWT (JSON Web Token) signed with RS256
- **Lifetime**: Configurable, default is 3600 seconds (one hour)
- **Claims**: Includes "sub" (client ID), "iss" (user pool issuer URL), "aud" or "client_id", "scope" (granted scopes), "exp" (expiration timestamp)
- **Refresh Tokens**: Not issued for client credentials grant; clients must re-authenticate when tokens expire

---

## Neo4j Aura SSO Configuration

### OIDC Provider Setup

Neo4j Aura SSO must be configured to recognize Cognito as an identity provider. This is done through the Aura console's organization security settings.

The OIDC configuration requires:

**Discovery URI**: The Cognito user pool's well-known OpenID configuration URL, which provides all other endpoint URLs automatically. The format is:
`https://cognito-idp.{region}.amazonaws.com/{userPoolId}/.well-known/openid-configuration`

**Audience**: The resource server identifier configured in Cognito. Neo4j validates that the token's audience claim matches this value.

**Claims Configuration**: Mapping between JWT claims and Neo4j concepts:
- Username claim: Typically "sub" (the client ID for M2M tokens)
- Groups claim: Typically "scope" for M2M tokens (contains the granted scopes)

**Group to Role Mapping**: Maps Cognito scopes to Neo4j roles. For example:
- "neo4j-admin" scope maps to Neo4j "admin" role
- "neo4j-reader" scope maps to Neo4j "reader" role

### M2M Visibility Setting

For deployments using only machine-to-machine authentication (no browser-based user login), the OIDC provider can be configured as invisible. This prevents the provider from appearing in Neo4j Browser's SSO login dropdown, avoiding confusion for users who might attempt browser-based login with a provider that only supports M2M.

### Token Validation Process

When Neo4j receives a bearer token, it performs the following validation steps:

1. **Signature Verification**: Fetches Cognito's JWKS (JSON Web Key Set) and verifies the token's signature using the appropriate public key. The JWKS is cached to avoid fetching on every request.

2. **Expiration Check**: Verifies the token's "exp" claim is in the future.

3. **Issuer Validation**: Confirms the "iss" claim matches the expected Cognito user pool URL.

4. **Audience Validation**: Confirms the "aud" or "client_id" claim matches the configured resource server identifier.

5. **Scope Extraction**: Extracts scopes from the "scope" claim for role mapping.

---

## App Runner Service Configuration

### Container Requirements

The Neo4j MCP server is distributed as a container image. For App Runner deployment, this image must be stored in Amazon Elastic Container Registry (ECR) in the same AWS account and region as the App Runner service.

The container runs the Neo4j MCP server binary in HTTP transport mode. It listens on a configurable port (default 8080 for App Runner compatibility) and serves MCP protocol requests.

### Environment Variables

The MCP server is configured entirely through environment variables:

**NEO4J_URI**: The connection string for the Neo4j Aura instance. For Aura, this is typically in the format "neo4j+s://xxxx.databases.neo4j.io" where the connection uses TLS encryption.

**NEO4J_MCP_TRANSPORT**: Set to "http" to enable HTTP transport mode instead of the default STDIO mode.

**NEO4J_MCP_HTTP_HOST**: Set to "0.0.0.0" to listen on all network interfaces. App Runner routes traffic to the container's port, so the container must accept connections from any source.

**NEO4J_MCP_HTTP_PORT**: Set to "8080" to match App Runner's default port expectation. App Runner can be configured to use other ports, but 8080 is conventional.

**NEO4J_DATABASE**: The database name within the Neo4j instance. Defaults to "neo4j" if not specified.

**NEO4J_READ_ONLY**: Optional. Set to "true" to disable write operations, limiting the MCP server to read-only queries.

Note that NEO4J_USERNAME and NEO4J_PASSWORD are intentionally not configured. The absence of these variables ensures the server operates in bearer-token-only mode, requiring all requests to include a valid JWT.

### Health Check Configuration

App Runner performs health checks to determine container readiness. The MCP server's "initialize" and "tools/list" endpoints respond without requiring authentication, making them suitable for health checks.

However, the MCP protocol uses JSON-RPC over POST, not simple GET requests. App Runner's default health check sends HTTP GET requests. For compatibility, App Runner should be configured with either:

- TCP health checks on the container port (simpler, verifies the server is listening)
- Custom health check path if the MCP server exposes a simple HTTP endpoint

The MCP server's path validation middleware returns 404 for paths other than "/mcp", which App Runner interprets as unhealthy. This behavior should be considered when configuring health checks.

### Networking

App Runner provides automatic HTTPS termination with AWS-managed certificates. The public endpoint receives HTTPS traffic and forwards it to the container over HTTP. The MCP server does not need to handle TLS directly.

App Runner services can optionally connect to VPC resources through VPC Connectors. If the Neo4j Aura instance is accessed over the public internet (the typical configuration), no VPC Connector is needed. If connecting to a self-hosted Neo4j in a VPC, a VPC Connector must be configured.

### Auto Scaling

App Runner automatically scales the number of container instances based on concurrent request load. The scaling parameters include:

- **Minimum instances**: The number of instances maintained even with no traffic. Set to 1 or higher to avoid cold starts.
- **Maximum instances**: The ceiling for scaling. Higher values handle traffic spikes but increase maximum cost.
- **Maximum concurrent requests per instance**: The number of simultaneous requests an instance handles before scaling triggers.

For the MCP server, each request may involve database queries that take variable time. Conservative concurrency settings (lower requests per instance) provide more predictable latency at the cost of scaling earlier.

---

## CDK Infrastructure Definition

### Stack Structure

The CDK stack creates all required AWS resources in a single, deployable unit. The stack includes:

1. **ECR Repository**: Stores the MCP server container image. The repository is created with image scanning enabled for security vulnerability detection.

2. **Cognito User Pool**: The identity provider infrastructure, including the user pool itself, the domain, the resource server with custom scopes, and the machine app client.

3. **App Runner Service**: The compute service running the MCP server container, configured with the appropriate environment variables and scaling parameters.

4. **IAM Roles**: Service roles that grant App Runner permission to pull images from ECR.

### Resource Naming

Resources are named using a configurable prefix to allow multiple deployments in the same account. The prefix appears in resource names, making it easy to identify related resources and enabling parallel deployments for development, staging, and production environments.

### Output Values

The stack exports key values needed by clients:

- **Cognito Token Endpoint**: The URL where clients request access tokens
- **App Runner Service URL**: The HTTPS endpoint for MCP requests
- **Client ID**: The app client identifier (client secret is retrieved separately for security)
- **Resource Server Identifier**: The audience value for token requests

These outputs can be queried after deployment using the AWS CLI or consumed by other CDK stacks.

---

## Implementation Plan

### Phase 1: Foundation Infrastructure

This phase establishes the core AWS infrastructure required for the deployment.

#### Tasks

- [ ] **Create CDK project structure**: Initialize a new CDK Python project with the standard directory layout, pyproject.toml for dependencies, and app.py entry point.

- [ ] **Define ECR repository construct**: Create the container registry that will store the MCP server image. Enable image scanning and configure lifecycle policies to manage image retention.

- [ ] **Implement image build automation**: Create a mechanism to build the Neo4j MCP server container image from the official source and push it to the ECR repository. This may use CodeBuild, a custom resource with Lambda, or external CI/CD integration.

- [ ] **Create base IAM roles**: Define the service roles required for App Runner to pull images from ECR and for any build automation.

- [ ] **Validate ECR image availability**: Ensure the MCP server image is successfully built and pushed before proceeding to service deployment.

#### Completion Criteria

The ECR repository exists and contains a valid Neo4j MCP server container image. The image can be pulled using appropriate IAM credentials.

---

### Phase 2: Cognito Identity Provider

This phase configures Cognito as the OAuth 2.0 authorization server for machine-to-machine authentication.

#### Tasks

- [ ] **Create Cognito User Pool**: Define the user pool with appropriate settings for M2M authentication. Password policies and MFA are not relevant for M2M but may be configured for future extensibility.

- [ ] **Configure User Pool Domain**: Set up either a Cognito-hosted domain or custom domain for the OAuth 2.0 endpoints. Document the token endpoint URL for client configuration.

- [ ] **Define Resource Server**: Create the resource server representing the Neo4j API. Define the identifier that will appear in token audience claims.

- [ ] **Create Custom Scopes**: Define scopes that map to Neo4j database roles. Document the scope names and their intended permissions for later mapping in Neo4j.

- [ ] **Create Machine App Client**: Configure an app client for M2M authentication with client credentials grant enabled. Associate the client with the appropriate scopes.

- [ ] **Store Client Secret Securely**: Store the app client secret in AWS Secrets Manager for secure retrieval by client applications. Do not include the secret in CDK outputs.

- [ ] **Document OIDC Endpoints**: Record the discovery URL, token endpoint, and JWKS endpoint for Neo4j configuration.

#### Completion Criteria

A Cognito User Pool exists with a configured domain, resource server, scopes, and app client. Tokens can be obtained using the client credentials grant. The OIDC discovery endpoint returns valid metadata.

---

### Phase 3: App Runner Service Deployment

This phase deploys the Neo4j MCP server container to App Runner with appropriate configuration.

#### Tasks

- [ ] **Define App Runner Service**: Create the App Runner service resource pointing to the ECR repository and image tag.

- [ ] **Configure Environment Variables**: Set the required environment variables for HTTP transport mode, including NEO4J_URI, transport mode, host, and port. Ensure no username/password variables are set.

- [ ] **Configure Auto Scaling**: Set minimum instances to 1 for production (avoiding cold starts) or 0 for development. Configure maximum instances and concurrency based on expected load.

- [ ] **Configure Health Checks**: Set up appropriate health check configuration compatible with the MCP server's HTTP behavior.

- [ ] **Enable Observability**: Configure CloudWatch logging for the App Runner service to capture MCP server output for debugging and monitoring.

- [ ] **Test Service Endpoint**: Verify the App Runner service starts successfully and the MCP server responds to health checks.

#### Completion Criteria

The App Runner service is running and accessible via its HTTPS endpoint. The MCP server logs indicate successful startup in HTTP mode.

---

### Phase 4: Neo4j Aura SSO Configuration

This phase configures Neo4j Aura to accept tokens from Cognito. This phase involves manual steps in the Aura console as Aura SSO is not configurable via API.

#### Tasks

- [ ] **Access Aura Organization Settings**: Navigate to the Aura console and access the organization's security settings.

- [ ] **Add OIDC Provider**: Configure a new SSO provider using Cognito's discovery URL. Enter the audience value matching the Cognito resource server identifier.

- [ ] **Configure Claim Mapping**: Map the "sub" claim to Neo4j username and the "scope" claim to groups (for role mapping).

- [ ] **Define Group to Role Mapping**: Create mappings from Cognito scopes to Neo4j roles. For example, map the "neo4j-admin" scope to the admin role.

- [ ] **Set M2M Visibility**: Configure the provider as invisible if only M2M access is intended.

- [ ] **Test Token Acceptance**: Obtain a token from Cognito and verify Neo4j accepts it for authentication using a direct driver connection (before involving the MCP server).

#### Completion Criteria

Neo4j Aura accepts bearer tokens issued by Cognito and correctly maps scopes to database roles. A test query using bearer auth succeeds.

---

### Phase 5: End-to-End Integration

This phase validates the complete authentication flow from client through MCP server to Neo4j.

#### Tasks

- [ ] **Create Test Client Script**: Write a Python script that obtains a token from Cognito using the client credentials grant.

- [ ] **Test MCP Tool List**: Send an unauthenticated request to tools/list to verify the MCP server responds correctly without requiring authentication.

- [ ] **Test Authenticated Query**: Send an authenticated tools/call request with a bearer token to execute a simple Cypher query. Verify the query succeeds and returns expected results.

- [ ] **Test Token Expiration Handling**: Wait for a token to expire and verify the MCP server returns an appropriate error. Verify the client can obtain a new token and retry successfully.

- [ ] **Test Invalid Token Rejection**: Send a request with an invalid or malformed token and verify appropriate error handling.

- [ ] **Test Scope-Based Authorization**: Test that tokens with different scopes result in different Neo4j role permissions. Verify that a read-only scope prevents write operations.

- [ ] **Document Client Integration**: Create documentation showing how client applications obtain tokens and call MCP tools.

#### Completion Criteria

The complete flow works end-to-end. Clients can obtain tokens from Cognito, call MCP tools through App Runner, and execute queries on Neo4j with proper authentication and authorization.

---

### Phase 6: Production Readiness

This phase addresses operational concerns for production deployment.

#### Tasks

- [ ] **Configure CloudWatch Alarms**: Set up alarms for App Runner service errors, high latency, and scaling events.

- [ ] **Implement Token Caching in Clients**: Document best practices for client-side token caching to avoid unnecessary token requests.

- [ ] **Configure Secret Rotation**: Set up rotation for the Cognito app client secret if long-lived deployments require it.

- [ ] **Document Runbook**: Create operational documentation covering deployment, updates, troubleshooting, and incident response.

- [ ] **Performance Testing**: Conduct load testing to validate scaling behavior and establish performance baselines.

- [ ] **Security Review**: Review the deployment for security best practices, including least-privilege IAM policies, encryption at rest and in transit, and access logging.

#### Completion Criteria

The deployment is documented, monitored, and validated for production use. Operational procedures are established and tested.

---

## Request Timeout Considerations

App Runner enforces a 120-second timeout on HTTP requests. This timeout includes the entire request lifecycle: reading the request body, processing, and writing the response.

For the Neo4j MCP server, this timeout affects:

**Cypher Query Execution**: Complex graph traversals, large result set retrievals, and write operations with many nodes may exceed 120 seconds. Queries should be designed to complete within this limit, or clients should implement pagination for large operations.

**Schema Inference**: The get-schema tool samples nodes and relationships to infer the graph schema. For large databases with many labels and relationship types, schema inference may approach the timeout limit.

**Tool List and Initialize**: These MCP protocol methods complete quickly and are not affected by the timeout.

If specific use cases consistently require longer processing times, the deployment architecture should be reconsidered. ECS Fargate with an Application Load Balancer supports configurable timeouts up to 4000 seconds.

---

## Security Considerations

### Token Security

JWT tokens grant access to the Neo4j database. Protecting tokens is essential:

- Tokens are transmitted only over HTTPS (enforced by App Runner's automatic TLS termination)
- Tokens have limited lifetime (default one hour) to reduce exposure window
- Client secrets must be stored securely (AWS Secrets Manager is recommended)
- Tokens should not be logged or included in error messages

### Network Security

The deployment exposes a public HTTPS endpoint. Security controls include:

- App Runner's managed TLS with automatic certificate rotation
- Neo4j Aura's encryption for database connections
- No VPC required for standard Aura connections (traffic secured by TLS)

### IAM Least Privilege

CDK-defined IAM roles follow least-privilege principles:

- App Runner's instance role has permission only to pull from the specific ECR repository
- No database credentials are stored in IAM or environment variables

### Audit Logging

Enable logging for security monitoring:

- App Runner logs capture all MCP server output including request metadata
- Cognito logs token issuance events
- Neo4j Aura logs query execution with authenticated identity

---

## Cost Estimation

### App Runner Costs

App Runner pricing includes:

- **Provisioned Instances**: Memory charges for instances maintained while idle, approximately seven dollars per GB-month
- **Active Instances**: CPU and memory charges during request processing
- **Minimum Charge**: With minimum instances set to one, expect baseline costs of twenty-five to fifty dollars per month depending on memory configuration

### Cognito Costs

Cognito pricing for machine-to-machine:

- **Monthly Active Users**: Not applicable for M2M (no users)
- **Token Requests**: Charged per request after free tier, but volume is typically low for M2M
- **Expected Cost**: Minimal, typically under five dollars per month for moderate token request volume

### Neo4j Aura Costs

Aura pricing depends on instance size and tier:

- **Free Tier**: Available for development with limitations
- **Professional**: Production-ready, priced by memory and storage
- **Enterprise**: Required for SSO features, contact Neo4j for pricing

### Total Estimated Cost

For a minimal production deployment with one App Runner instance and moderate usage:

- App Runner: Thirty to sixty dollars per month
- Cognito: Under five dollars per month
- Neo4j Aura: Varies by tier (Free for development, Professional starts around sixty-five dollars per month)

---

## Conclusion

Deploying the Neo4j MCP server to AWS App Runner with bearer token authentication provides a secure, scalable, and operationally simple solution for exposing Neo4j database capabilities through the MCP protocol. The integration of Cognito for identity management and Aura for database hosting creates a fully managed architecture with minimal infrastructure overhead.

The phased implementation plan provides a structured approach to deployment, with clear milestones and validation criteria at each stage. By following this plan, teams can establish a working deployment incrementally, validating each component before proceeding to the next.

This architecture is well-suited for scenarios where:

- Automated services and AI agents need database access without user interaction
- Multi-tenant access with different permission levels is required
- Operational simplicity is prioritized over maximum cost optimization
- Request processing completes within App Runner's 120-second timeout

---

*Document completed: 2026-01-07*
