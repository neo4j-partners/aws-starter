#!/usr/bin/env python3
"""Async example of using the Neo4j Aura Agent client.

This example shows how to:
1. Use the async invoke method
2. Run multiple queries concurrently
3. Handle async context properly

Before running:
1. Copy .env.example to .env
2. Fill in your Neo4j Aura API credentials
3. Run: uv run python examples/async_usage.py
"""
import asyncio
import logging
import sys
import time

# Add src to path for development
sys.path.insert(0, ".")

from src import AuraAgentClient
from src.client import AuraAgentError

logging.basicConfig(level=logging.INFO)


async def ask_question(client: AuraAgentClient, question: str) -> str:
    """Ask a single question asynchronously."""
    print(f"Asking: {question[:50]}...")
    response = await client.invoke_async(question)
    return response.text or "No response"


async def main() -> None:
    """Run async agent invocation examples."""
    print("=" * 60)
    print("Neo4j Aura Agent Client - Async Usage Example")
    print("=" * 60)

    try:
        client = AuraAgentClient.from_env()
    except ValueError as e:
        print(f"\nError: {e}")
        print("Copy .env.example to .env and fill in your credentials.")
        return

    # Example questions - customize for your agent
    questions = [
        "What types of nodes exist in the graph?",
        "What relationships connect the nodes?",
        "Give me a summary of the data.",
    ]

    print(f"\nAsking {len(questions)} questions concurrently...")
    print("-" * 60)

    start = time.time()

    try:
        # Run all questions concurrently
        tasks = [ask_question(client, q) for q in questions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.time() - start
        print(f"\nCompleted in {elapsed:.2f} seconds")
        print("=" * 60)

        for question, result in zip(questions, results):
            print(f"\nQ: {question}")
            if isinstance(result, Exception):
                print(f"A: Error - {result}")
            else:
                # Truncate long responses
                answer = result if len(result) < 200 else result[:200] + "..."
                print(f"A: {answer}")
            print("-" * 40)

    except AuraAgentError as e:
        print(f"\nError: {e}")


if __name__ == "__main__":
    asyncio.run(main())
