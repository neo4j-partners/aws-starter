# Neo4j MCP Agent (Strands) — Dockerfile for AgentCore Runtime
#
# Build context is the agent root (one level up), so the shared `common/`
# package and the root pyproject.toml/uv.lock are available:
#
#   docker build --platform linux/arm64 \
#       -f strands/Dockerfile -t neo4j-strands .
#   docker run -p 8080:8080 neo4j-strands
#
# AgentCore Requirements: ARM64 (aarch64), port 8080, HTTP server on 8080.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# The local project builds the `common` package, so it must be present
# before `uv sync` installs the project into the venv.
COPY pyproject.toml uv.lock ./
COPY common ./common
RUN uv sync --frozen --no-dev

COPY strands ./strands

# Copy MCP credentials if present (wildcard avoids failure when absent).
COPY .mcp-credentials.jso[n] ./

EXPOSE 8080

CMD ["uv", "run", "python", "strands/runtime_app.py"]
