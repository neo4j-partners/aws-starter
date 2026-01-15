FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

ENV AWS_REGION=us-west-2
ENV AWS_DEFAULT_REGION=us-west-2

# Copy application code
COPY . .

# Create non-root user and set ownership
# IMPORTANT: Files must be readable by the non-root user
RUN useradd -m -u 1000 bedrock_agentcore && \
    chown -R bedrock_agentcore:bedrock_agentcore /app
USER bedrock_agentcore

# MCP servers run on port 8000
EXPOSE 8000

CMD ["python", "mcp_server.py"]
