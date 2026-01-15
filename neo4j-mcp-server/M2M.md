# Alternative Authentication Approach: MCP Bearer Token Authentication

---

## Glossary of Terms

This section defines key terms used throughout this document to ensure clarity.

### AWS Bedrock AgentCore Components

**AgentCore Runtime**
A managed container service within AWS Bedrock AgentCore that hosts and executes MCP servers or agent applications. The Runtime pulls a container image from Amazon ECR and runs it in an isolated environment. It handles incoming requests, manages container lifecycle, and provides a standardized invocation endpoint. The Runtime validates requests using JWT or IAM authorization before passing them to the hosted application.

**AgentCore Gateway**
A public HTTPS endpoint that acts as an entry point for clients to interact with MCP servers hosted in AgentCore Runtimes. The Gateway handles client authentication, request routing, and protocol translation. It can be configured with interceptors for request/response transformation and requires clients to provide valid authorization credentials.

**Gateway Target**
A configuration that links an AgentCore Gateway to a specific AgentCore Runtime. The Gateway Target defines how the Gateway routes requests to the Runtime and how it authenticates those requests. It can use different credential provider types: Gateway IAM Role credentials, OAuth2 credentials from a credential provider, or no credentials.

**OAuth2 Credential Provider**
A configuration resource that enables the AgentCore Gateway to obtain OAuth2 tokens for authenticating requests to a Runtime. When configured on a Gateway Target, the Gateway automatically obtains tokens from the specified identity provider (such as AWS Cognito) and includes them in requests to the Runtime. This creates machine-to-machine authentication between Gateway and Runtime.

**Gateway Request Interceptor**
A Lambda function that processes requests before they reach the Runtime. Interceptors can validate, transform, or reject requests. They receive the original request headers and body, and can modify them before forwarding. However, when an OAuth2 Credential Provider is configured, its token generation happens after interceptor processing and can overwrite headers set by the interceptor.

### Authentication Concepts

**Client**
In this document, "client" refers to any software that sends requests to the AgentCore Gateway. This could be an AI agent, a backend service, a command-line tool, or any other application that needs to invoke MCP tools. The client must authenticate with the Gateway, typically using a JWT token or AWS IAM credentials.

**M2M (Machine-to-Machine) Authentication**
An OAuth2 authentication flow where automated services authenticate themselves without human interaction. In M2M authentication, a client application uses its own credentials (client ID and client secret) to obtain access tokens, rather than acting on behalf of a human user. This is also called the "client credentials grant" in OAuth2 terminology.

**JWT (JSON Web Token)**
A compact, URL-safe token format that contains claims about an entity (typically a user or service) encoded as a JSON object. JWTs are digitally signed, allowing recipients to verify their authenticity. In AgentCore, JWTs are used for client-to-Gateway authentication and Gateway-to-Runtime authentication.

**Bearer Token**
An access token that grants access to a protected resource simply by possessing (bearing) it. Bearer tokens are typically included in HTTP requests using the Authorization header with the format `Authorization: Bearer <token>`. Anyone who has the token can use it, so they must be transmitted securely.

**Basic Authentication**
An HTTP authentication scheme where credentials are sent as a base64-encoded string in the format `username:password`. Basic auth uses the Authorization header with the format `Authorization: Basic <base64-encoded-credentials>`. It provides no encryption, so it should only be used over HTTPS.

**OIDC (OpenID Connect)**
An identity layer built on top of OAuth2 that enables clients to verify user identity and obtain basic profile information. OIDC adds an ID token (a JWT containing identity claims) to the OAuth2 authorization flow. Identity providers like Okta, Azure AD, and AWS Cognito implement OIDC.

**SSO (Single Sign-On)**
An authentication scheme allowing users to log in once and access multiple applications without re-authenticating. SSO is typically implemented using protocols like OIDC or SAML. In the context of this document, Neo4j's SSO feature allows users to authenticate using enterprise identity providers.

**JWKS (JSON Web Key Set)**
A set of cryptographic keys published by an identity provider that token recipients use to verify JWT signatures. When Neo4j receives a bearer token, it fetches the issuer's JWKS to validate that the token was genuinely issued by the claimed identity provider.

### Neo4j Terms

**Neo4j MCP Server**
The official Model Context Protocol server for Neo4j databases, written in Go. It exposes Neo4j database operations (schema inspection, Cypher queries) as MCP tools that AI agents can invoke. The server supports two transport modes: STDIO for local desktop clients and HTTP for web-based deployments.

**Neo4j Aura**
Neo4j's fully managed cloud database service. Aura handles infrastructure, scaling, and maintenance. It comes in different tiers (Free, Professional, Enterprise) with varying feature sets. SSO authentication is only available on Aura Enterprise.

**BearerAuth**
A Neo4j driver authentication method that passes a JWT token to the database for validation. When using BearerAuth, Neo4j validates the token against a configured OIDC identity provider rather than checking a local username/password.

### Protocol Terms

**HTTP Authorization Header**
A standard HTTP header used to send credentials from client to server. The HTTP specification permits only one Authorization header per request. This is the fundamental constraint that causes the conflict described in this document.

**AWS Secrets Manager**
An AWS service for storing and retrieving sensitive data such as passwords, API keys, and certificates. Applications can fetch secrets at runtime without hardcoding credentials. This is the approach used in the current working custom MCP server implementation.

**SSM Parameter Store**
An AWS Systems Manager capability for storing configuration data, including plain text or encrypted parameters. It is commonly used for non-secret configuration values like table names, API endpoints, and feature flags.

---

## Executive Summary

This document investigates whether using the Neo4j MCP server's bearer token authentication feature could solve the Authorization header conflict that currently blocks deploying the official Neo4j MCP server to AWS Bedrock AgentCore.

**Conclusion: The bearer token approach would not solve the problem.** While the Neo4j MCP server does support bearer token authentication, deploying it to AgentCore with this authentication mode faces the same fundamental HTTP Authorization header conflict, plus additional infrastructure complexity that makes it impractical.

---

## Background: The Current Problem

The neo4j-mcp-server project is currently blocked because both AWS Bedrock AgentCore and the Neo4j MCP server require the HTTP Authorization header for different, incompatible purposes:

1. **AgentCore Gateway** validates incoming client requests using a JWT bearer token in the Authorization header. This JWT is issued by AWS Cognito and proves the client is authorized to access the Gateway.

2. **AgentCore Gateway Target with OAuth Credential Provider** authenticates requests from the Gateway to the Runtime using a machine-to-machine JWT token. The Gateway obtains this token from Cognito using the OAuth2 client credentials flow and places it in the Authorization header when calling the Runtime.

3. **Neo4j MCP server** needs credentials to authenticate with the Neo4j database. In the current approach, it expects these credentials in the Authorization header using HTTP Basic authentication format.

The HTTP specification only permits one Authorization header per request. When the Gateway's OAuth credential provider is configured, it generates its own Authorization header for Runtime authentication, which overwrites any custom header the interceptor might produce. The Neo4j Basic auth credentials never reach the MCP server.

---

## The Bearer Token Alternative

The official Neo4j MCP server supports an alternative authentication mode: JWT bearer token authentication. In this mode, instead of expecting username and password credentials, the MCP server accepts a JWT bearer token in the Authorization header and passes this token directly to the Neo4j database using the driver's BearerAuth mechanism. Neo4j then validates the token against a configured OpenID Connect identity provider.

This feature was designed to enable Single Sign-On scenarios where users authenticate through an enterprise identity provider like Okta, Azure Active Directory, or similar OIDC-compliant systems. The MCP server acts as a pass-through, forwarding the bearer token to Neo4j without validating it locally.

The question this document investigates is whether this bearer token mode could enable deploying the Neo4j MCP server to AgentCore by aligning the authentication mechanism with how AgentCore already operates.

---

## Investigation Findings

### Finding 1: Bearer Token Mode Uses the Same Authorization Header

The first and most significant finding is that bearer token authentication uses the exact same HTTP Authorization header as the current Basic authentication approach. The only difference is the token format:

- Basic authentication: `Authorization: Basic <base64-encoded-credentials>`
- Bearer authentication: `Authorization: Bearer <jwt-token>`

Both approaches require the MCP server to receive credentials through the standard HTTP Authorization header. This means the fundamental conflict persists: AgentCore's OAuth credential provider will still generate its own Authorization header for Runtime authentication, and this header will still contain the Gateway-to-Runtime JWT, not the credentials Neo4j needs.

The bearer token mode does not introduce a second header or alternative credential delivery mechanism. It simply changes what type of credential the server expects to find in the Authorization header.

### Finding 2: AgentCore OAuth Tokens Are Not Compatible with Neo4j

Even if there were a mechanism to pass the AgentCore OAuth token through to Neo4j, this token would not be valid for Neo4j authentication. Here is why:

AgentCore's OAuth tokens are issued by AWS Cognito with specific claims and audience configurations designed for authenticating with AgentCore services. The tokens include:

- Audience claim pointing to the AgentCore resource server
- Scopes defined for AgentCore operations
- Issuer URL pointing to the Cognito user pool

For Neo4j to accept a JWT bearer token, the database must be configured with OIDC authentication pointing to an identity provider that:

- Issues tokens with claims Neo4j can map to database roles
- Has a JWKS endpoint Neo4j can use to validate token signatures
- Issues tokens with an audience claim Neo4j recognizes

Neo4j's OIDC configuration is completely independent of AgentCore's Cognito configuration. The tokens AgentCore uses to authenticate Gateway-to-Runtime communication have no relationship to Neo4j authentication. Using Cognito tokens for Neo4j authentication would require:

1. Configuring Neo4j Enterprise (self-hosted or Aura Enterprise) with OIDC pointing to the same Cognito user pool
2. Creating appropriate Cognito scopes and claims that map to Neo4j database roles
3. Ensuring the tokens issued for AgentCore operations contain the correct claims for Neo4j

This creates a tight coupling between the AWS Cognito configuration for AgentCore and the Neo4j database authentication configuration, which is impractical for most deployments.

### Finding 3: Neo4j Aura SSO and Machine-to-Machine Authentication

Neo4j Aura supports Single Sign-On (SSO) that enables organization owners and admins to use their organization's identity provider to authenticate users for access to both the Aura console and Aura database instances. While the documentation highlights Microsoft Entra ID, Okta, and Google as primary identity providers, Aura's SSO configuration supports any OIDC-compliant provider through two configuration methods:

1. **Discovery URI**: Automatically populates OIDC endpoints by providing the provider's well-known configuration URL
2. **Manual Configuration**: Allows direct specification of Issuer, Authorization Endpoint, Token Endpoint, and JWKS URI

The Neo4j Aura team has confirmed that the Okta configuration pattern can be applied to AWS Cognito, since both implement the OIDC standard. This means Cognito could theoretically serve as an identity provider for Neo4j Aura SSO.

#### Machine-to-Machine Authentication with Neo4j

A critical distinction exists between browser-based SSO flows and machine-to-machine (M2M) authentication. The standard Aura SSO documentation describes the Authorization Code Flow, which requires redirecting users to an identity provider's login page in a browser. This flow is unsuitable for automated services, backend applications, and MCP servers that operate without human interaction.

However, Neo4j does support M2M authentication using the OAuth2 Client Credentials Grant. This approach allows applications to authenticate directly with an identity provider using a client ID and client secret, without requiring a browser or user interaction. The identity provider issues a JWT access token that the application presents to Neo4j as a bearer token.

This M2M pattern has been demonstrated with Okta and the Neo4j Query API, as documented in the blog post "App Token Authentication with Neo4j Query API" (https://www.pm50plus.com/2024/10/24/app-token-query-api.html). The configuration involves:

1. **Identity Provider Setup**: Creating an API Services application in Okta (or equivalent in another OIDC provider), capturing the client ID and client secret, and configuring an authorization server with a custom scope that maps to Neo4j database roles

2. **Neo4j OIDC Configuration**: Configuring Neo4j to accept tokens from the identity provider by specifying the discovery URI, audience, and claim mappings (username claim mapped to "sub", groups claim mapped to "scp" for scopes)

3. **Token Acquisition**: The application requests a token from the identity provider's token endpoint using the client credentials grant, receiving a JWT access token with limited lifespan (typically 3600 seconds)

4. **Bearer Token Usage**: The application includes the JWT in requests to Neo4j using the standard Authorization header format: `Authorization: Bearer <token>`

#### AWS Cognito M2M Capability

AWS Cognito fully supports machine-to-machine authentication through its User Pools feature. The configuration requires:

1. **Resource Server Definition**: Creating a resource server in Cognito with a unique identifier and custom scopes that define the permissions for Neo4j access

2. **App Client Configuration**: Creating a confidential app client with a client secret, enabling the client credentials grant, and associating the custom scopes from the resource server

3. **User Pool Domain**: Configuring a domain for the token endpoint

The M2M flow with Cognito works as follows: the application sends a POST request to the Cognito token endpoint with the client ID, client secret, grant type of "client_credentials", and the requested custom scopes. Cognito validates the credentials and returns an access token containing the authorized scopes.

AWS documentation for this configuration is available at https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html

#### Why This Does Not Solve the AgentCore Problem

While M2M authentication with Cognito and Neo4j is technically feasible, it does not resolve the AgentCore Authorization header conflict for the following reasons:

1. **Same Header, Same Conflict**: The M2M bearer token must be delivered to Neo4j via the HTTP Authorization header. Whether using browser-based SSO or M2M client credentials, the Neo4j MCP server expects `Authorization: Bearer <token>`. This is the same header that AgentCore's OAuth credential provider overwrites.

2. **Token Purpose Mismatch**: Even if the same Cognito user pool were configured for both AgentCore and Neo4j, the tokens serve different purposes. The token AgentCore generates for Gateway-to-Runtime authentication contains scopes and audience claims configured for AgentCore operations, not for Neo4j database access. Neo4j would reject a token with incorrect audience or missing Neo4j-specific scopes.

3. **Dual Token Requirement Remains**: The fundamental architecture requires two different tokens: one for AgentCore Gateway-to-Runtime authentication and one for Neo4j database authentication. Both need to be delivered via the Authorization header, which HTTP does not permit.

The M2M approach would work well for scenarios where the Neo4j MCP server runs outside of AgentCore (for example, as a standalone HTTP service or in a traditional container deployment). In those environments, there is no intermediate authentication layer consuming the Authorization header, and the bearer token flows directly from client to MCP server to Neo4j.

The challenge specific to AgentCore is the multi-layer authentication architecture where the Gateway and Runtime have their own authentication requirements that operate independently of any downstream service authentication needs.

### Finding 4: Gateway IAM Role Authentication Does Not Help

The AgentCore samples demonstrate an alternative to OAuth credential providers: using Gateway IAM Role credentials for Gateway-to-Runtime authentication. In this mode, the Gateway uses its IAM role to sign requests to the Runtime rather than using OAuth tokens.

With IAM role authentication, the Gateway does not generate an Authorization header for Runtime communication. Instead, it uses AWS Signature Version 4 signing. This theoretically leaves the Authorization header available for passing through to the MCP server.

However, this approach has its own problems:

1. The Runtime must still validate incoming requests. If it uses JWT authorization, it expects a valid JWT in the Authorization header. If it uses IAM authorization, it expects SigV4-signed requests. Neither mode expects credentials for a downstream database.

2. The Neo4j bearer token must come from somewhere. In the bearer token flow, a client first authenticates with an identity provider to obtain a JWT, then includes that JWT in requests to the MCP server. With AgentCore in the middle, this would require:
   - The end client obtaining a Neo4j-compatible JWT from an OIDC provider
   - Passing this JWT through the AgentCore Gateway and Runtime to the MCP server
   - The MCP server forwarding the JWT to Neo4j for validation

3. The AgentCore Gateway still expects its own authorization for incoming requests. Whether using JWT or IAM authorization, the Gateway validates incoming client requests independently of any downstream authentication needs. The client would need to provide both AgentCore authorization and Neo4j authorization in a single HTTP request.

### Finding 5: The Request Interceptor Limitation Persists

The site-reliability-agent-workshop sample demonstrates using a Gateway REQUEST interceptor to read and transform headers before forwarding requests to the Runtime. The interceptor successfully reads the Authorization header and can include it in the transformed request.

However, as documented in the STATUS.md, when an OAuth credential provider is configured on the Gateway Target, the OAuth flow takes precedence. The credential provider obtains its own token and overwrites the Authorization header. Headers set by the interceptor's transformed request are not merged into the OAuth-authenticated request.

Switching to bearer token mode does not change this behavior. The OAuth credential provider operates at a different layer than the interceptor, and its token generation happens after interceptor processing.

---

## Why Bearer Token Authentication Cannot Solve the Problem

The fundamental issue is architectural, not protocol-based. AgentCore's design treats the Runtime as an internal service that requires authentication from the Gateway. This Gateway-to-Runtime authentication is separate from any authentication the Runtime's hosted application might need for its own downstream services.

The bearer token authentication mode assumes a simpler architecture where:

1. A client authenticates with an identity provider
2. The client sends the resulting JWT to the MCP server
3. The MCP server forwards the JWT to Neo4j
4. Neo4j validates the JWT against the same identity provider

AgentCore introduces additional authentication layers:

1. A client authenticates with Cognito to get a token for AgentCore
2. AgentCore Gateway validates this token
3. AgentCore Gateway obtains a separate token for Runtime communication
4. The Runtime receives this Gateway-to-Runtime token
5. The MCP server running in the Runtime needs credentials for Neo4j

The bearer token mode does not address the fact that there are now three separate authentication concerns (client-to-Gateway, Gateway-to-Runtime, and Runtime-to-Neo4j) and only one HTTP Authorization header available.

Even if the tokens could be unified (same Cognito pool, same scopes, same claims), the mechanical problem remains: the OAuth credential provider will generate its own Authorization header, and this header contains a token for Runtime authentication, not for Neo4j authentication.

---

## Technical Summary

| Aspect | Basic Auth Approach | Bearer Token Approach |
|--------|---------------------|----------------------|
| HTTP Header Used | Authorization | Authorization |
| Header Format | Basic base64(user:pass) | Bearer jwt-token |
| Conflict with OAuth Provider | Yes | Yes |
| Can Pass Through Interceptor | Blocked by OAuth flow | Blocked by OAuth flow |
| Neo4j Configuration Required | Username/password | OIDC provider setup |
| Cognito Compatibility | N/A | Not officially supported for Aura |
| Infrastructure Complexity | Low | High (OIDC configuration) |

Both approaches fail at the same point: the OAuth credential provider overwrites the Authorization header before the request reaches the Runtime.

---

## Alternative Approaches Not Evaluated

This document specifically evaluated bearer token authentication as requested. Other approaches exist but were not evaluated:

1. **Environment Variable Credentials**: Configure Neo4j credentials as environment variables in the Runtime. This works for single-tenant scenarios but does not support per-request credentials.

2. **Secrets Manager Integration**: Fetch credentials from AWS Secrets Manager at runtime. This is what the current custom MCP server implementation uses. It works but limits flexibility.

3. **Custom Header Support**: Request a feature in the Neo4j MCP server to read credentials from a configurable custom header instead of the standard Authorization header. This would require changes to the official server.

4. **Self-Hosted Proxy**: Deploy a proxy service that sits between AgentCore and Neo4j, handling credential injection. This adds operational complexity.

These alternatives were explicitly excluded from this evaluation per the investigation requirements.

---

## Conclusion

The MCP bearer token authentication approach would not enable deploying the official Neo4j MCP server to AWS Bedrock AgentCore. The approach suffers from the same fundamental limitation as Basic authentication: both methods require delivering credentials through the HTTP Authorization header, and AgentCore's OAuth credential provider overwrites this header during Gateway-to-Runtime communication.

Additionally, the bearer token approach introduces significant infrastructure complexity:

- Neo4j must be configured with OIDC authentication pointing to an identity provider
- AWS Cognito is not officially supported as a Neo4j Aura identity provider
- Token claims and scopes must be aligned across AgentCore and Neo4j configurations
- The multi-layer authentication architecture of AgentCore is fundamentally incompatible with the simple client-to-server token passthrough that bearer authentication assumes

The HTTP Authorization header conflict documented in STATUS.md cannot be circumvented by changing the authentication scheme from Basic to Bearer. The conflict exists at the protocol level (HTTP allows only one Authorization header) and at the architectural level (AgentCore's authentication layers operate independently of downstream service authentication needs).

---

## Authentication Patterns in Official AWS AgentCore Samples

This section examines how the official Amazon Bedrock AgentCore samples handle MCP server authentication to downstream services. The goal is to understand what authentication patterns AWS recommends and whether any samples demonstrate an MCP server authenticating to external services that require per-request credentials in the HTTP Authorization header.

### Overview of Samples Examined

The investigation examined all MCP server implementations in the amazon-bedrock-agentcore-samples repository, including:

- Travel Concierge Agent (three MCP servers: cart tools, travel tools, itinerary tools)
- Shopping Concierge Agent (shopping tools MCP server)
- Customer Support Assistant VPC (DynamoDB MCP server)
- Device Management Agent
- Site Reliability Agent Workshop
- Tutorial MCP servers (calculator, hello world)

### Pattern 1: AWS Service Authentication via IAM Roles

The most common pattern in AWS samples is MCP servers that authenticate to AWS services (DynamoDB, Secrets Manager, SES, SSM Parameter Store) using implicit IAM role credentials. In this pattern:

- The MCP server uses boto3 (the AWS Python SDK) to access AWS services
- No credentials are explicitly configured in the server code
- The boto3 credential chain automatically picks up the IAM role attached to the Runtime container
- Authentication happens at the SDK level without using HTTP headers

This pattern is demonstrated in the Travel Concierge cart tools MCP server, which accesses DynamoDB for user profiles, wishlists, and itineraries. The server creates a DynamoDB resource with only the region specified, and AWS handles all authentication transparently.

The Customer Support Assistant VPC sample uses the same pattern for DynamoDB access, with table names passed via environment variables and authentication handled by the container's IAM role.

**Key Insight**: AWS services do not require the HTTP Authorization header. They use AWS Signature Version 4 signing, which is handled by the SDK and does not conflict with AgentCore's authentication flow.

### Pattern 2: Third-Party API Keys via SSM Parameter Store

For third-party services that require API keys (not OAuth2 tokens), the AWS samples use SSM Parameter Store to inject credentials at runtime. The Travel Concierge travel tools MCP server demonstrates this pattern:

- At server startup, the MCP server calls SSM Parameter Store to retrieve API keys
- Keys are stored as SecureString parameters with paths like `/concierge-agent/travel/openweather-api-key`
- Retrieved values are set as environment variables for the server to use
- API keys are then included in outbound requests to third-party services (OpenWeather, SerpAPI, Google Maps)

These API keys are typically passed as query parameters or custom headers (not the Authorization header), so they do not conflict with AgentCore's authentication flow.

The Shopping Concierge shopping tools MCP server uses the same pattern for SerpAPI integration.

**Key Insight**: AWS recommends storing API keys in SSM Parameter Store and loading them at startup. This works because these third-party APIs accept credentials via query parameters or non-standard headers.

### Pattern 3: Sensitive Credentials via AWS Secrets Manager

For highly sensitive credentials such as certificates, private keys, and OAuth client secrets, the AWS samples use Secrets Manager with on-demand retrieval. The Travel Concierge Visa integration demonstrates this pattern:

- The MCP server fetches certificates and API keys from Secrets Manager when needed
- Lazy loading ensures secrets are only retrieved when first required
- mTLS certificates are loaded from secrets for services requiring mutual TLS authentication
- Graceful degradation handles cases where secrets are unavailable

This pattern is used for the Visa payment integration, which requires client certificates and API keys for mTLS authentication. The certificates are used at the transport layer (TLS), not in HTTP headers.

**Key Insight**: For credentials that require secure storage and rotation, AWS recommends Secrets Manager. This works well for API keys, certificates, and other credentials that are not passed in the HTTP Authorization header.

### Pattern 4: Gateway IAM Role Credentials for Runtime Authentication

Several samples use Gateway IAM Role credentials instead of OAuth2 credential providers for Gateway-to-Runtime authentication. In this pattern:

- The Gateway uses AWS Signature Version 4 signing to authenticate requests to the Runtime
- No OAuth token is generated for Gateway-to-Runtime communication
- The HTTP Authorization header is not used by the Gateway
- Request interceptors can potentially pass through client-provided headers

The Site Reliability Agent Workshop uses this pattern. The Gateway is configured with `GATEWAY_IAM_ROLE` credential type, and interceptors can read and forward the client's Authorization header to the Runtime.

**Key Insight**: Gateway IAM Role authentication leaves the HTTP Authorization header available for client-provided credentials. However, this only helps if the Runtime does not also require JWT authorization for incoming requests.

### Pattern 5: OAuth2 Credential Providers for M2M Authentication

For scenarios requiring OAuth2 machine-to-machine authentication, the AWS samples configure OAuth2 Credential Providers. The Device Management Agent and the simple-oauth-gateway sample demonstrate this pattern:

- A Cognito User Pool is created with a machine client (no user interaction)
- The client uses the client credentials grant to obtain tokens
- The Gateway validates client tokens, then obtains its own token for Runtime communication
- The Runtime validates the Gateway's token

This is the pattern used in the neo4j-mcp-server project and the source of the Authorization header conflict.

**Key Insight**: None of the samples using OAuth2 credential providers demonstrate an MCP server that also needs to authenticate to a downstream service using the HTTP Authorization header. The samples using OAuth either access AWS services (IAM auth) or do not require downstream authentication.

### What the Samples Do NOT Demonstrate

After examining all samples, several authentication scenarios are notably absent:

1. **No sample shows an MCP server authenticating to a third-party database using the HTTP Authorization header.** All database access in the samples is to DynamoDB, which uses IAM authentication.

2. **No sample demonstrates passing per-request credentials through the OAuth credential flow.** When OAuth2 credential providers are used, the downstream services either use IAM auth or require no authentication.

3. **No sample shows an MCP server that needs to forward a client's bearer token to a downstream service.** The bearer token authentication scenario (client token → MCP server → database) is not represented.

4. **No sample demonstrates multi-tenant database authentication.** All database access uses shared credentials via IAM roles or Secrets Manager, not per-request credentials.

5. **No sample shows custom header propagation through OAuth-protected targets.** The metadataConfiguration allowedRequestHeaders feature mentioned in AWS documentation is not demonstrated in any sample.

### Summary: AWS Authentication Patterns for MCP Servers

| Pattern | Downstream Service | Credential Source | Header Used | Conflict with OAuth? |
|---------|-------------------|-------------------|-------------|---------------------|
| IAM Role | AWS Services (DynamoDB, SES, etc.) | Container IAM Role | None (SigV4 signing) | No |
| SSM Parameter Store | Third-party APIs (weather, search) | SSM at startup | Query params or custom headers | No |
| Secrets Manager | Payment APIs (Visa) | Secrets at runtime | mTLS certificates, API keys | No |
| Gateway IAM Role | Runtime (no downstream) | Gateway IAM Role | None (SigV4 signing) | No |
| OAuth2 Provider | Runtime (no downstream) | Cognito | Authorization (Bearer) | Yes (conflicts with downstream Basic/Bearer) |

### Implications for Neo4j MCP Server Deployment

The AWS samples reveal an important gap: AWS does not currently demonstrate a pattern for MCP servers that need to authenticate to external databases using the HTTP Authorization header while also being protected by OAuth2 authentication at the Gateway level.

The patterns AWS demonstrates all avoid the Authorization header conflict by:
- Using IAM authentication (SigV4 signing, not HTTP headers) for AWS services
- Using query parameters or custom headers for third-party API keys
- Using mTLS at the transport layer for sensitive integrations
- Not having downstream authentication requirements when using OAuth2 credential providers

The Neo4j MCP server's requirement for HTTP Authorization header credentials (whether Basic or Bearer) represents a use case that the AWS samples do not address and the current AgentCore architecture does not support when OAuth2 credential providers are in use.

### AWS Documentation Claims vs Sample Reality

AWS documentation states that the Authorization header can be forwarded to targets when provided by an interceptor Lambda. However, this claim comes with unstated limitations:

1. The documentation does not specify that this only works without an OAuth2 credential provider
2. No sample demonstrates this forwarding with an OAuth2 credential provider configured
3. The samples that use interceptors to pass Authorization headers use Gateway IAM Role credentials, not OAuth

The absence of samples demonstrating Authorization header passthrough with OAuth2 providers suggests this combination is either not supported or requires undocumented configuration.

---

## Conclusion

The MCP bearer token authentication approach would not enable deploying the official Neo4j MCP server to AWS Bedrock AgentCore. The approach suffers from the same fundamental limitation as Basic authentication: both methods require delivering credentials through the HTTP Authorization header, and AgentCore's OAuth credential provider overwrites this header during Gateway-to-Runtime communication.

The official AWS samples confirm that no demonstrated pattern exists for MCP servers that need to authenticate to external services using the HTTP Authorization header while behind an OAuth-protected Gateway. AWS's recommended patterns for downstream authentication rely on IAM roles, query parameters, custom headers, or mTLS, all of which avoid the Authorization header conflict.

For the Neo4j MCP server use case, the options remain:
1. Use single-tenant credentials via environment variables or Secrets Manager (losing per-request authentication)
2. Request AWS add support for custom header propagation through OAuth credential flows
3. Request the Neo4j MCP server support reading credentials from a configurable custom header

---

*Investigation completed: 2026-01-07*
