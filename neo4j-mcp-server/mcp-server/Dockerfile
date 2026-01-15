# Neo4j MCP Server for AWS Bedrock AgentCore
#
# This Dockerfile builds the Neo4j MCP server with HTTPAuthMode support
# (currently from local modified repo, pending PR merge to official repo).
#
# The server receives Neo4j credentials via the Authorization header,
# which is transformed from X-Neo4j-Authorization by the Gateway
# REQUEST interceptor.
#
# NOTE: Once the HTTPAuthMode feature is merged to the official repo,
# update this Dockerfile to clone from github.com/neo4j/mcp instead.

# Builder stage - compile Go binary
FROM golang:1.25-alpine AS builder

LABEL io.modelcontextprotocol.server.name="io.github.neo4j/mcp"

WORKDIR /build

# Copy the local Neo4j MCP repo with HTTPAuthMode support
# This directory should be provided via docker build context
COPY neo4j-mcp-src/ .

# Download dependencies
RUN go mod download

# Build the binary for Linux ARM64 (AgentCore requirement)
RUN CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build \
    -C cmd/neo4j-mcp \
    -a -installsuffix cgo \
    -o ../../neo4j-mcp

# Runtime stage - minimal image
FROM alpine:3.21

LABEL io.modelcontextprotocol.server.name="io.github.neo4j/mcp"
LABEL io.modelcontextprotocol.server.description="Neo4j MCP Server on AWS Bedrock AgentCore"

WORKDIR /app

# Install CA certificates for TLS connections to Neo4j Aura
RUN apk add --no-cache ca-certificates

# Copy binary from builder
COPY --from=builder /build/neo4j-mcp /app/neo4j-mcp

# Create non-root user for AgentCore Runtime (required)
# Using standard UID 1000 as per AgentCore requirements
RUN adduser -D -u 1000 bedrock_agentcore

# Ensure app files are readable by the user
RUN chown -R bedrock_agentcore:bedrock_agentcore /app

USER bedrock_agentcore

# AgentCore Runtime expects port 8000
EXPOSE 8000

# Set entrypoint to the Neo4j MCP server binary
# Environment variables control behavior:
#   NEO4J_URI=... (required - database endpoint)
#   NEO4J_MCP_TRANSPORT=http (required for AgentCore)
#   NEO4J_MCP_HTTP_AUTH_MODE=header (per-request credentials via Authorization header)
#   NEO4J_MCP_HTTP_PORT=8000 (AgentCore port)
#   NEO4J_MCP_HTTP_HOST=0.0.0.0 (listen on all interfaces)
ENTRYPOINT ["/app/neo4j-mcp"]
