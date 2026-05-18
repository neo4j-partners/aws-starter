# Neo4j Fleet Agent (Strands) — Dockerfile for AgentCore Runtime
#
# Build context is the agent root, so the shared `common/` package and the
# root pyproject.toml/uv.lock are available:
#
#   docker build --platform linux/arm64 -t neo4j-fleet-agent .
#   docker run -p 8080:8080 neo4j-fleet-agent
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

COPY runtime_app.py tools.py ./

# Neo4j connection (NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD) and AWS
# credentials are supplied as Runtime environment variables, not baked in.

EXPOSE 8080

CMD ["uv", "run", "python", "runtime_app.py"]
