#!/usr/bin/env python3
"""
Invoke Agent Programmatically

Demonstrates how to invoke the deployed Neo4j MCP Agent using boto3.

Usage:
    python invoke_agent.py                          # Uses default prompt
    python invoke_agent.py "What is the schema?"    # Custom prompt

Prerequisites:
    - Agent deployed to AgentCore Runtime (./agent.sh deploy)
    - AWS credentials configured
    - .bedrock_agentcore.yaml exists with agent ARN (created by agentcore configure)
"""

import json
import logging
import sys
import uuid

import boto3
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_agent_arn() -> str:
    """
    Get the agent ARN from .bedrock_agentcore.yaml config file.

    This file is created by 'agentcore configure' command.
    """
    config_file = ".bedrock_agentcore.yaml"

    try:
        with open(config_file) as f:
            config = yaml.safe_load(f)

        arn = config.get("agent_runtime_arn")
        if not arn:
            raise ValueError(f"agent_runtime_arn not found in {config_file}")

        return arn

    except FileNotFoundError:
        logger.error(f"{config_file} not found")
        print(f"ERROR: {config_file} not found")
        print("")
        print("Run './agent.sh configure' and './agent.sh deploy' first")
        sys.exit(1)


def invoke_agent(prompt: str) -> dict:
    """
    Invoke the deployed agent with a prompt.

    Args:
        prompt: The user's question

    Returns:
        The agent's response as a dictionary
    """
    agent_arn = get_agent_arn()

    logger.info(f"Agent ARN: {agent_arn}")
    logger.info(f"Prompt: {prompt}")

    # Create the AgentCore client
    client = boto3.client("bedrock-agentcore")

    # Prepare the payload
    payload = json.dumps({"prompt": prompt}).encode()

    # Generate a unique session ID
    session_id = str(uuid.uuid4())

    # Invoke the agent
    logger.info("Invoking agent...")
    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=session_id,
        payload=payload,
        qualifier="DEFAULT",
    )

    # Read and parse the streaming response
    content_parts = []
    errors = []

    for chunk in response.get("response", []):
        try:
            chunk_data = json.loads(chunk.decode("utf-8"))

            # Handle different response types
            if chunk_data.get("type") == "chunk":
                content_parts.append(chunk_data.get("data", ""))
            elif chunk_data.get("type") == "error":
                errors.append(chunk_data.get("error", "Unknown error"))
            elif chunk_data.get("type") == "complete":
                logger.info("Response complete")
            else:
                # Handle legacy format (direct response)
                if "response" in chunk_data:
                    content_parts.append(chunk_data["response"])
                elif "data" in chunk_data:
                    content_parts.append(chunk_data["data"])

        except json.JSONDecodeError:
            # Raw text chunk
            content_parts.append(chunk.decode("utf-8"))

    if errors:
        return {"status": "error", "errors": errors}

    return {
        "status": "success",
        "response": "".join(content_parts),
    }


def main():
    # Get prompt from command line or use default
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = "What is the database schema?"

    print("=" * 70)
    print("Neo4j MCP Agent - Programmatic Invocation")
    print("=" * 70)
    print("")
    print(f"Prompt: {prompt}")
    print("")

    result = invoke_agent(prompt)

    print("")
    print("=" * 70)
    print("Response:")
    print("=" * 70)

    if result.get("status") == "success":
        print(result.get("response", "No response"))
    else:
        print(f"ERROR: {result.get('errors', ['Unknown error'])}")

    print("")


if __name__ == "__main__":
    main()
