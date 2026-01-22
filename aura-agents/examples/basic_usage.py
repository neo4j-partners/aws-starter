#!/usr/bin/env python3
"""Basic example of using the Neo4j Aura Agent client.

This example shows how to:
1. Create a client from environment variables
2. Invoke the agent with a question
3. Process the response

Before running:
1. Copy .env.example to .env
2. Fill in your Neo4j Aura API credentials
3. Run: uv run python examples/basic_usage.py
"""
import logging
import sys

# Add src to path for development
sys.path.insert(0, ".")

from src import AuraAgentClient
from src.client import AuthenticationError, InvocationError

# Enable debug logging to see API calls
logging.basicConfig(level=logging.INFO)


def main() -> None:
    """Run a basic agent invocation example."""
    print("=" * 60)
    print("Neo4j Aura Agent Client - Basic Usage Example")
    print("=" * 60)

    # Create client from environment variables
    # Requires: NEO4J_CLIENT_ID, NEO4J_CLIENT_SECRET, NEO4J_AGENT_ENDPOINT
    try:
        client = AuraAgentClient.from_env()
        print(f"\nClient created: {client}")
    except ValueError as e:
        print(f"\nError: {e}")
        print("\nMake sure you have set the required environment variables:")
        print("  - NEO4J_CLIENT_ID")
        print("  - NEO4J_CLIENT_SECRET")
        print("  - NEO4J_AGENT_ENDPOINT")
        print("\nCopy .env.example to .env and fill in your credentials.")
        return

    # Example question - customize this for your agent
    question = "What information can you tell me about the data in your graph?"

    print(f"\nAsking: {question}")
    print("-" * 60)

    try:
        response = client.invoke(question)

        # Print the response
        print(f"\nStatus: {response.status}")
        print(f"\nAnswer:\n{response.text}")

        # Show thinking/reasoning if available
        if response.thinking:
            print(f"\nAgent Thinking:\n{response.thinking}")

        # Show tool usage if available
        if response.tool_uses:
            print(f"\nTools Used: {len(response.tool_uses)}")
            for tool in response.tool_uses:
                print(f"  - {tool.type}: {tool.tool_use_id}")

        # Show token usage if available
        if response.usage:
            print(f"\nToken Usage:")
            if response.usage.request_tokens:
                print(f"  Request: {response.usage.request_tokens}")
            if response.usage.response_tokens:
                print(f"  Response: {response.usage.response_tokens}")
            if response.usage.total_tokens:
                print(f"  Total: {response.usage.total_tokens}")

    except AuthenticationError as e:
        print(f"\nAuthentication failed: {e}")
        print("Check your NEO4J_CLIENT_ID and NEO4J_CLIENT_SECRET")
    except InvocationError as e:
        print(f"\nAgent invocation failed: {e}")
        print("Check your NEO4J_AGENT_ENDPOINT URL")


if __name__ == "__main__":
    main()
