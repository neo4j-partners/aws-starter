#!/usr/bin/env python3
"""
Invoke Agent Programmatically

Demonstrates how to invoke the deployed Neo4j MCP Agent using boto3.

Usage:
    uv run python invoke_agent.py                          # Uses default prompt
    uv run python invoke_agent.py "What is the schema?"    # Custom prompt

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

# Configure logging (WARNING level to keep output clean)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_agent_config() -> tuple[str, str]:
    """
    Get the agent ARN and region from .bedrock_agentcore.yaml config file.

    This file is created by 'agentcore configure' command.

    Returns:
        Tuple of (agent_arn, region)
    """
    config_file = ".bedrock_agentcore.yaml"

    try:
        with open(config_file) as f:
            config = yaml.safe_load(f)

        # Get the default agent name
        default_agent = config.get("default_agent")
        if not default_agent:
            raise ValueError(f"default_agent not found in {config_file}")

        # Navigate to the agent's ARN
        agents = config.get("agents", {})
        agent_config = agents.get(default_agent, {})
        arn = agent_config.get("bedrock_agentcore", {}).get("agent_arn")
        region = agent_config.get("aws", {}).get("region", "us-west-2")

        if not arn:
            raise ValueError(f"agent_arn not found for agent '{default_agent}' in {config_file}")

        return arn, region

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
    agent_arn, region = get_agent_config()

    logger.info(f"Agent ARN: {agent_arn}")
    logger.info(f"Region: {region}")
    logger.info(f"Prompt: {prompt}")

    # Create the AgentCore client
    client = boto3.client("bedrock-agentcore", region_name=region)

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
    raw_buffer = ""

    for chunk in response.get("response", []):
        raw_buffer += chunk.decode("utf-8")

    # Parse SSE format - each message is "data: {...}\n\n"
    for message in raw_buffer.split("\n\n"):
        message = message.strip()
        if not message:
            continue

        # Strip "data: " prefix if present
        if message.startswith("data: "):
            message = message[6:]

        # Try to parse as JSON
        try:
            chunk_data = json.loads(message)

            # Handle different response types
            if chunk_data.get("type") == "chunk":
                content_parts.append(chunk_data.get("data", ""))
            elif chunk_data.get("type") == "error":
                errors.append(chunk_data.get("error", "Unknown error"))
            elif chunk_data.get("type") == "complete":
                pass  # End of response
            else:
                # Handle legacy format (direct response)
                if "response" in chunk_data:
                    content_parts.append(chunk_data["response"])
                elif "data" in chunk_data:
                    content_parts.append(chunk_data["data"])
        except json.JSONDecodeError:
            # Not JSON, could be raw text
            if message:
                content_parts.append(message)

    # Join content and clean up escaped newlines
    full_response = "".join(content_parts)
    full_response = full_response.replace("\\n", "\n")

    if errors:
        return {"status": "error", "errors": errors}

    return {
        "status": "success",
        "response": full_response,
    }


def main():
    # Get prompt from command line or use default
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = "How many aircraft are in the database?"

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
