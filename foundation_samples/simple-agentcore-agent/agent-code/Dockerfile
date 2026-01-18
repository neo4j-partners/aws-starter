FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir aws-opentelemetry-distro==0.10.1

ENV AWS_REGION=us-west-2
ENV AWS_DEFAULT_REGION=us-west-2

# Copy application code
COPY . .

# Create non-root user and set ownership
RUN useradd -m -u 1000 bedrock_agentcore && \
    chown -R bedrock_agentcore:bedrock_agentcore /app
USER bedrock_agentcore

EXPOSE 8080
EXPOSE 8000

CMD ["opentelemetry-instrument", "python", "agent.py"]
