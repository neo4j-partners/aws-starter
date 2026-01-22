#!/usr/bin/env python
"""Test invoking the deployed agent."""
import sys
from bedrock_agentcore_starter_toolkit import Runtime

agentcore_runtime = Runtime()

# Need to configure to load the existing agent
agentcore_runtime.configure(
    entrypoint="strands_claude_runtime.py",
    auto_create_execution_role=True,
    auto_create_ecr=True,
    requirements_file="requirements.txt",
    region="us-west-2",
    agent_name="strands_claude_getting_started"
)

prompt = sys.argv[1] if len(sys.argv) > 1 else "What is the weather now?"
print(f"Prompt: {prompt}")
print()

response = agentcore_runtime.invoke({"prompt": prompt})
print(f"Response: {response['response']}")
