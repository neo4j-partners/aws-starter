# Finance Agent (Strands) — Dockerfile for AgentCore Runtime
#
# Build context is the agent root (one level up), so the shared `common/`
# package and the root pyproject.toml/uv.lock are available:
#
#   docker build --platform linux/arm64 \
#       -f strands/Dockerfile -t finance-strands .
#   docker run -p 8080:8080 finance-strands
#
# AgentCore Requirements: ARM64 (aarch64), port 8080, HTTP server on 8080.

# Recommended uv ARM64 base image (uv preinstalled); AgentCore requires arm64.
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# The local project builds the `common` package, so it must be present
# before `uv sync` installs the project into the venv. `vendor/` holds the
# neo4j-agent-memory wheel the lockfile pins by relative path.
COPY pyproject.toml uv.lock ./
COPY common ./common
COPY vendor ./vendor
RUN uv sync --frozen --no-dev

COPY strands ./strands

# Copy MCP credentials if present (wildcard avoids failure when absent).
COPY .mcp-credentials.jso[n] ./

EXPOSE 8080

# opentelemetry-instrument (from aws-opentelemetry-distro) wraps the process
# so AgentCore emits traces/metrics to CloudWatch GenAI Observability.
CMD ["uv", "run", "opentelemetry-instrument", "python", "strands/runtime_app.py"]
