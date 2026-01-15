#!/usr/bin/env python3
"""Test script for invoking the deployed AgentCore agent."""
import boto3
import json
import sys


def get_runtime_arn(stack_name: str = "SampleOneAgentDemo") -> str:
    """Get the AgentCore Runtime ARN from CloudFormation stack outputs."""
    cf = boto3.client("cloudformation")
    response = cf.describe_stacks(StackName=stack_name)

    for output in response["Stacks"][0]["Outputs"]:
        if output["OutputKey"] == "AgentRuntimeArn":
            return output["OutputValue"]

    raise ValueError(f"AgentRuntimeArn not found in {stack_name} outputs")


def invoke_agent(runtime_arn: str, prompt: str) -> dict:
    """Invoke the agent with a prompt and return the response."""
    client = boto3.client("bedrock-agentcore")

    payload = json.dumps({"prompt": prompt})

    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        payload=payload.encode(),
    )

    body = response["response"].read().decode()
    return json.loads(body)


def main():
    prompts = [
        "What is 2+2?",
        "Say hello in three different languages.",
        "What's the capital of France?",
    ]

    if len(sys.argv) > 1:
        prompts = [" ".join(sys.argv[1:])]

    print("Getting AgentCore Runtime ARN...")
    try:
        runtime_arn = get_runtime_arn()
        print(f"Runtime ARN: {runtime_arn}\n")
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure the CDK stack is deployed: uv run cdk deploy")
        sys.exit(1)

    for prompt in prompts:
        print(f"Prompt: {prompt}")
        print("-" * 50)

        try:
            response = invoke_agent(runtime_arn, prompt)

            if response.get("status") == "success":
                print(f"Response: {response.get('response', 'No response')}")
            else:
                print(f"Error: {response.get('error', 'Unknown error')}")
        except Exception as e:
            print(f"Error invoking agent: {e}")

        print()


if __name__ == "__main__":
    main()
