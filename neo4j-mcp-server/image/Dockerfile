# Wraps the mcp-neo4j-cypher image that deploy.py builds from NEO4J_MCP_REPO.
# The entrypoint reads the Neo4j password from Secrets Manager when
# NEO4J_PASSWORD_SECRET_ARN is set, then starts the server in the same process.
# Without that variable the server reads NEO4J_PASSWORD as before.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

RUN pip install --no-cache-dir "boto3==1.42.42"

COPY secret_entrypoint.py /app/secret_entrypoint.py

CMD ["python", "/app/secret_entrypoint.py"]
