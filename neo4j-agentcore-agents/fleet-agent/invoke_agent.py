#!/usr/bin/env python3
"""
Invoke Agent Programmatically

Demonstrates how to invoke the deployed Neo4j Fleet Agent using boto3.

The response is streamed: SSE events ("data: {...}\\n\\n") are parsed as they
arrive off the wire and the answer is printed to the terminal token by token,
not buffered and printed at the end. The parser understands exactly the three
event shapes the Strands runtime emits (chunk/error/complete); the deprecated
direct-response shapes are not supported.

Usage:
    uv run python invoke_agent.py                          # Uses default prompt
    uv run python invoke_agent.py "How many aircraft?"     # Custom prompt
    uv run python invoke_agent.py load-test                # Load test mode (random queries every 5s)
    uv run python invoke_agent.py load-test 10             # Load test with custom interval (10s)

Prerequisites:
    - Agent deployed to AgentCore Runtime (./agent.sh deploy)
    - AWS credentials configured
    - .bedrock_agentcore.yaml exists with agent ARN (created by agentcore configure)
"""

import json
import logging
import random
import re
import sys
import time
import uuid
from pathlib import Path

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


def _handle_sse_event(
    event: str,
    content_parts: list[str],
    errors: list[str],
    stream: bool = True,
) -> None:
    """Dispatch one SSE event from the Strands runtime, printing text live.

    The Strands ``runtime_app`` emits exactly three JSON event shapes:
    ``{"type": "chunk", "data": ...}``, ``{"type": "error", "error": ...}``,
    and ``{"type": "complete"}``. ``chunk`` text is printed as it arrives and
    also collected so callers still get the assembled response. ``json.loads``
    already yields real newlines, so no ``\\n`` unescaping is needed; anything
    that is not one of these shapes is ignored.
    """
    event = event.strip()
    if not event:
        return
    if event.startswith("data: "):
        event = event[6:]
    try:
        data = json.loads(event)
    except json.JSONDecodeError:
        return
    if data.get("type") == "chunk":
        text = data.get("data", "")
        if stream:
            print(text, end="", flush=True)
        content_parts.append(text)
    elif data.get("type") == "error":
        errors.append(data.get("error", "Unknown error"))


def _print_result(result: dict) -> None:
    """The success text already streamed live; only surface errors here."""
    if result.get("status") != "success":
        print(f"ERROR: {result.get('errors', ['Unknown error'])}")


def invoke_payload(payload: dict, stream: bool = True) -> dict:
    """Invoke the deployed runtime with an arbitrary payload.

    Args:
        payload: The request body. ``{"prompt": "..."}`` runs the full agent;
            ``{"mode": "schema"}``, ``{"mode": "graph_query", "query": "..."}``
            and ``{"mode": "vector_search", "query": "...", "top_k": N}`` hit
            the direct surfaces of the same runtime.
        stream: When True, print ``chunk`` text live as it arrives. Set False
            to collect the response silently and use the returned text.

    Returns:
        ``{"status": "success", "response": "..."}`` or
        ``{"status": "error", "errors": [...]}``.
    """
    agent_arn, region = get_agent_config()

    logger.info(f"Agent ARN: {agent_arn}")
    logger.info(f"Region: {region}")
    logger.info(f"Payload: {payload}")

    # Create the AgentCore client
    client = boto3.client("bedrock-agentcore", region_name=region)

    # Generate a unique session ID
    session_id = str(uuid.uuid4())

    # Invoke the agent
    logger.info("Invoking agent...")
    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=session_id,
        payload=json.dumps(payload).encode(),
        qualifier="DEFAULT",
    )

    # Parse and print SSE events ("data: {...}\n\n") as they arrive off the
    # wire rather than buffering the whole response, so the answer streams to
    # the terminal live.
    content_parts: list[str] = []
    errors: list[str] = []
    buffer = ""

    for raw in response.get("response", []):
        buffer += raw.decode("utf-8")
        while "\n\n" in buffer:
            event, buffer = buffer.split("\n\n", 1)
            _handle_sse_event(event, content_parts, errors, stream)
    if buffer.strip():
        _handle_sse_event(buffer, content_parts, errors, stream)

    if stream:
        print()  # terminate the streamed line

    if errors:
        return {"status": "error", "errors": errors}

    return {
        "status": "success",
        "response": "".join(content_parts),
    }


def invoke_agent(prompt: str, stream: bool = True) -> dict:
    """Invoke the deployed agent with a prompt (the full ReAct surface)."""
    return invoke_payload({"prompt": prompt}, stream=stream)


def load_queries() -> list[str]:
    """Load queries from queries.txt file."""
    queries_file = Path(__file__).parent / "queries.txt"

    if not queries_file.exists():
        logger.error(f"queries.txt not found at {queries_file}")
        return []

    queries = []
    with open(queries_file) as f:
        for line in f:
            # Match lines starting with a number followed by a period
            match = re.match(r'^\d+\.\s+(.+)$', line.strip())
            if match:
                queries.append(match.group(1))

    return queries


def run_load_test(interval: int = 5):
    """Run continuous load test with random queries at specified interval."""
    queries = load_queries()

    if not queries:
        print("ERROR: No queries found in queries.txt")
        sys.exit(1)

    print("=" * 70)
    print("Neo4j Fleet Agent - Load Test Mode")
    print("=" * 70)
    print(f"Loaded {len(queries)} queries from queries.txt")
    print(f"Running a random query every {interval} seconds...")
    print("Press Ctrl+C to stop")
    print("=" * 70)
    print("")

    iteration = 1

    try:
        while True:
            # Select a random query
            query_idx = random.randint(0, len(queries) - 1)
            query = queries[query_idx]

            print("=" * 70)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Iteration {iteration} - Query #{query_idx + 1}")
            print("=" * 70)
            print(f"Query: {query}")
            print("-" * 70)
            print("")

            _print_result(invoke_agent(query))

            print("")
            print("-" * 70)
            print(f"Waiting {interval} seconds before next query...")
            print("")

            iteration += 1
            time.sleep(interval)

    except KeyboardInterrupt:
        print("")
        print("=" * 70)
        print(f"Load test stopped after {iteration - 1} iterations")
        print("=" * 70)


def main():
    # Check for load-test mode
    if len(sys.argv) > 1 and sys.argv[1] == "load-test":
        # Parse optional interval argument (default 5 seconds)
        interval = 5
        if len(sys.argv) > 2:
            try:
                interval = int(sys.argv[2])
            except ValueError:
                print(f"ERROR: Invalid interval '{sys.argv[2]}'. Must be a number.")
                sys.exit(1)
        run_load_test(interval)
        return

    # Get prompt from command line or use default
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = "How many aircraft are in the database?"

    print("=" * 70)
    print("Neo4j Fleet Agent - Programmatic Invocation")
    print("=" * 70)
    print("")
    print(f"Prompt: {prompt}")
    print("")

    print("")
    print("=" * 70)
    print("Response:")
    print("=" * 70)
    result = invoke_agent(prompt)
    _print_result(result)
    print("")


if __name__ == "__main__":
    main()
