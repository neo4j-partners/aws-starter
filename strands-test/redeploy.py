#!/usr/bin/env python
"""Redeploy Strands agent to AgentCore Runtime."""
import time
import json
import sys
from bedrock_agentcore_starter_toolkit import Runtime
from boto3.session import Session

boto_session = Session()
region = boto_session.region_name or "us-west-2"

print(f"Redeploying to region: {region}")

agentcore_runtime = Runtime()
agent_name = "strands_claude_getting_started"

# Configure first
print("\n=== Configuring AgentCore Runtime ===")
response = agentcore_runtime.configure(
    entrypoint="strands_claude_runtime.py",
    auto_create_execution_role=True,
    auto_create_ecr=True,
    requirements_file="requirements.txt",
    region=region,
    agent_name=agent_name
)
print(f"Configuration: {response}")

# Fix Dockerfile permissions issue
print("\n=== Patching Dockerfile for permissions ===")
with open("Dockerfile", "r") as f:
    dockerfile = f.read()
dockerfile = dockerfile.replace("COPY . .", "COPY --chown=bedrock_agentcore:bedrock_agentcore . .")
with open("Dockerfile", "w") as f:
    f.write(dockerfile)
print("Dockerfile patched")

# Launch
print("\n=== Relaunching to AgentCore Runtime ===")
launch_result = agentcore_runtime.launch()
print(f"Launch result: agent_id={launch_result.agent_id}, agent_arn={launch_result.agent_arn}")

# Wait for ready
print("\n=== Waiting for Runtime to be READY ===")
status_response = agentcore_runtime.status()
status = status_response.endpoint['status']
end_status = ['READY', 'CREATE_FAILED', 'DELETE_FAILED', 'UPDATE_FAILED']

while status not in end_status:
    print(f"  Status: {status}")
    time.sleep(10)
    status_response = agentcore_runtime.status()
    status = status_response.endpoint['status']

print(f"Final status: {status}")

if status == 'READY':
    # Wait a bit more for container to be fully ready
    print("\nWaiting for container to fully initialize...")
    time.sleep(15)

    # Test invocation
    print("\n=== Testing Invocation ===")
    try:
        invoke_response = agentcore_runtime.invoke({"prompt": "How is the weather now?"})
        print(f"Response: {invoke_response}")
    except Exception as e:
        print(f"Invocation error: {e}")
        print("\nChecking logs...")

    # Save info for cleanup
    with open("deployment_info.json", "w") as f:
        json.dump({
            "agent_id": launch_result.agent_id,
            "agent_arn": launch_result.agent_arn,
            "ecr_uri": launch_result.ecr_uri,
            "region": region
        }, f, indent=2)
    print("\nDeployment info saved to deployment_info.json")
else:
    print(f"Deployment failed with status: {status}")
    sys.exit(1)
