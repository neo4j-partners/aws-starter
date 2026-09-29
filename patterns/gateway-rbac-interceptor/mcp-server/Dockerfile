FROM public.ecr.aws/docker/library/python:3.11-slim

# uv binary from the official multi-arch image (works for the ARM64 build).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app

# Create non-root user for AgentCore Runtime
RUN useradd -m -u 1000 bedrock_agentcore

# Install dependencies into /app/.venv from the locked manifest. --frozen
# fails the build if uv.lock is out of sync with pyproject.toml, so the
# image always matches the committed lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code with correct ownership
COPY --chown=bedrock_agentcore:bedrock_agentcore server.py .

# Switch to non-root user
USER bedrock_agentcore

# Use the uv-managed virtualenv interpreter
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["python", "-m", "server"]
