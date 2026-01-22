#!/usr/bin/env python
"""Clean up AgentCore Runtime resources."""
import json
import boto3
from boto3.session import Session

# Load deployment info
try:
    with open("deployment_info.json") as f:
        info = json.load(f)
except FileNotFoundError:
    print("No deployment_info.json found. Nothing to clean up.")
    exit(0)

region = info.get("region", "us-west-2")
agent_id = info["agent_id"]
ecr_uri = info["ecr_uri"]
ecr_repo_name = ecr_uri.split('/')[1] if ecr_uri else None

print(f"Cleaning up resources in region: {region}")
print(f"  Agent ID: {agent_id}")
print(f"  ECR Repo: {ecr_repo_name}")

# Delete AgentCore Runtime
agentcore_control_client = boto3.client('bedrock-agentcore-control', region_name=region)
print("\nDeleting AgentCore Runtime...")
try:
    runtime_delete_response = agentcore_control_client.delete_agent_runtime(
        agentRuntimeId=agent_id,
    )
    print(f"  Deleted runtime: {agent_id}")
except Exception as e:
    print(f"  Error deleting runtime: {e}")

# Delete ECR repository
if ecr_repo_name:
    ecr_client = boto3.client('ecr', region_name=region)
    print("\nDeleting ECR repository...")
    try:
        response = ecr_client.delete_repository(
            repositoryName=ecr_repo_name,
            force=True
        )
        print(f"  Deleted ECR repo: {ecr_repo_name}")
    except Exception as e:
        print(f"  Error deleting ECR repo: {e}")

# Remove deployment info file
import os
os.remove("deployment_info.json")
print("\nCleanup complete!")
