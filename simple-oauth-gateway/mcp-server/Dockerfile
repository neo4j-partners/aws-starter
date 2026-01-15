FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

# Create non-root user for AgentCore Runtime
RUN useradd -m -u 1000 bedrock_agentcore

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code with correct ownership
COPY --chown=bedrock_agentcore:bedrock_agentcore server.py .

# Switch to non-root user
USER bedrock_agentcore

EXPOSE 8000

CMD ["python", "-m", "server"]
