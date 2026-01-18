# Sample One CDK Migration - Challenges & Fixes

## Current Status: ✅ RESOLVED

**Date:** 2026-01-01
**Stack:** SampleOneAgentDemo (deployed and working)
**Runtime ARN:** `arn:aws:bedrock-agentcore:us-west-2:159878781974:runtime/SampleOneAgentDemo_QuickStartAgent-sKXHZG5z9Z`

---

## Problem Description

The CDK stack deploys successfully and the Docker image is built and pushed to ECR. However, when invoking the agent runtime, we get:

```
An error occurred (RuntimeClientError) when calling the InvokeAgentRuntime operation:
An error occurred when starting the runtime. Please check your CloudWatch logs for more information.
```

---

## Root Cause: FILE PERMISSIONS

After running the container locally for debugging, the actual error was revealed:

```
/usr/local/bin/python: can't open file '/app/agent.py': [Errno 13] Permission denied
```

**Problem:** The Dockerfile copied files BEFORE switching to a non-root user, but the files retained root ownership. The non-root `bedrock_agentcore` user couldn't read them.

```dockerfile
# BROKEN - files copied as root, then user switched
RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore
COPY . .  # <-- Files have root:root ownership, unreadable by bedrock_agentcore
```

**Fix:** Copy files first, then create user and set ownership:

```dockerfile
# WORKING - files copied, ownership changed, then user switched
COPY . .
RUN useradd -m -u 1000 bedrock_agentcore && \
    chown -R bedrock_agentcore:bedrock_agentcore /app
USER bedrock_agentcore
```

---

## Other Issues Investigated (NOT the root cause)

The following issues were initially suspected but turned out to NOT be the actual cause:

| Issue | Notes |
|-------|-------|
| async vs sync entrypoint | Both work - async is supported |
| Agent created per request vs global | Both patterns are valid |
| Return dict vs plain string | Both are valid return formats |
| OpenTelemetry instrumentation | Not causing the failure |

---

## Final Working Configuration

### Dockerfile
```dockerfile
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
```

### agent.py
```python
from strands import Agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

def create_agent() -> Agent:
    system_prompt = """You are a helpful assistant. Answer questions clearly and concisely."""
    return Agent(system_prompt=system_prompt, name="QuickStartAgent")

@app.entrypoint
async def invoke(payload=None):
    try:
        query = payload.get("prompt", "Hello!") if payload else "Hello!"
        agent = create_agent()
        response = agent(query)
        return {
            "status": "success",
            "response": response.message['content'][0]['text']
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

if __name__ == "__main__":
    app.run()
```

---

## Progress Log

| Time | Action | Result |
|------|--------|--------|
| 12:00 | Initial CDK deploy | Stack created, runtime fails |
| 12:15 | Removed HEALTHCHECK from Dockerfile | Still failing |
| 12:26 | Redeployed with fixed Dockerfile | Still failing |
| 12:30 | Deep investigation of samples | Found suspected issues |
| 12:35 | Applied various code fixes | Still failing |
| 12:55 | Ran container locally | Found real error: Permission denied |
| 12:56 | Fixed Dockerfile ownership | Container works locally |
| 13:00 | Redeployed to AgentCore | **SUCCESS - Agent responding** |

---

## Debugging Tip

When the agent fails with `RuntimeClientError`, run the container locally to see actual errors:

```bash
docker build -t test-agent .
docker run --rm -p 8080:8080 -e AWS_REGION=us-west-2 test-agent

# In another terminal:
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello"}'
```

CloudWatch logs may not show Python startup errors if the container fails immediately.
