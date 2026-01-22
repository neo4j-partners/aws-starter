#!/usr/bin/env python
"""Deploy Strands agent to AgentCore Runtime."""
import time
import json
import sys
from bedrock_agentcore_starter_toolkit import Runtime
from boto3.session import Session

boto_session = Session()
region = boto_session.region_name or "us-west-2"

print(f"Deploying to region: {region}")

agentcore_runtime = Runtime()
agent_name = "strands_claude_getting_started"

# Configure
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

# Launch
print("\n=== Launching to AgentCore Runtime ===")
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
    # Test invocation
    print("\n=== Testing Invocation ===")
    invoke_response = agentcore_runtime.invoke({"prompt": "How is the weather now?"})
    print(f"Response: {invoke_response}")

    # Save info for cleanup
    with open("deployment_info.json", "w") as f:
        json.dump({
            "agent_id": launch_result.agent_id,
            "agent_arn": launch_result.agent_arn,
            "ecr_uri": launch_result.ecr_uri,
            "region": region
        }, f, indent=2)
    print("\nDeployment info saved to deployment_info.json")
    print("Run cleanup.py to delete resources when done.")
else:
    print(f"Deployment failed with status: {status}")
    sys.exit(1)
