#!/usr/bin/env python3
"""Interactive chat example with Neo4j Aura Agent.

This example shows how to:
1. Run an interactive Q&A session with the agent
2. Handle multiple queries in a session (with token reuse)
3. Gracefully handle errors

Before running:
1. Copy .env.example to .env
2. Fill in your Neo4j Aura API credentials
3. Run: uv run python examples/interactive_chat.py
"""
import logging
import sys

# Add src to path for development
sys.path.insert(0, ".")

from src import AuraAgentClient
from src.client import AuraAgentError

logging.basicConfig(level=logging.WARNING)


def main() -> None:
    """Run an interactive chat session with the Aura Agent."""
    print("=" * 60)
    print("Neo4j Aura Agent - Interactive Chat")
    print("=" * 60)
    print("\nType your questions and press Enter.")
    print("Type 'quit' or 'exit' to end the session.")
    print("Type 'debug' to toggle debug logging.")
    print("-" * 60)

    try:
        client = AuraAgentClient.from_env()
        print(f"Connected to: {client.endpoint_url[:50]}...")
    except ValueError as e:
        print(f"\nError: {e}")
        print("Copy .env.example to .env and fill in your credentials.")
        return

    debug_mode = False

    while True:
        try:
            question = input("\nYou: ").strip()

            if not question:
                continue

            if question.lower() in ("quit", "exit", "q"):
                print("\nGoodbye!")
                break

            if question.lower() == "debug":
                debug_mode = not debug_mode
                level = logging.DEBUG if debug_mode else logging.WARNING
                logging.getLogger().setLevel(level)
                print(f"Debug mode: {'ON' if debug_mode else 'OFF'}")
                continue

            if question.lower() == "clear":
                client.clear_token_cache()
                print("Token cache cleared.")
                continue

            print("\nAgent: ", end="", flush=True)
            response = client.invoke(question)

            if response.text:
                print(response.text)
            else:
                print("(No text response)")
                if response.raw_response:
                    print(f"Raw: {response.raw_response}")

        except AuraAgentError as e:
            print(f"\nError: {e}")
        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except EOFError:
            print("\n\nGoodbye!")
            break


if __name__ == "__main__":
    main()
