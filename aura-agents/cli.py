#!/usr/bin/env python3
"""Command-line interface for Neo4j Aura Agent.

Usage:
    uv run python cli.py "What data is in the graph?"
    uv run python cli.py --json "List all node types"
    echo "What relationships exist?" | uv run python cli.py -

Examples:
    # Single question
    uv run python cli.py "What contracts mention Motorola?"

    # JSON output (for scripting)
    uv run python cli.py --json "Give me a summary" | jq .text

    # Read from stdin
    echo "What's in the graph?" | uv run python cli.py -

    # Verbose mode with debug output
    uv run python cli.py -v "Explain the schema"
"""
import argparse
import json
import logging
import sys

from src import AuraAgentClient
from src.client import AuraAgentError


def main() -> int:
    """Run the CLI."""
    parser = argparse.ArgumentParser(
        description="Query a Neo4j Aura Agent from the command line",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "question",
        nargs="?",
        default="-",
        help="Question to ask (use '-' to read from stdin)",
    )
    parser.add_argument(
        "--json", "-j", action="store_true", help="Output response as JSON"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose/debug output"
    )
    parser.add_argument(
        "--raw", "-r", action="store_true", help="Output raw API response"
    )
    parser.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=60,
        help="Request timeout in seconds (default: 60)",
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    # Get the question
    if args.question == "-":
        if sys.stdin.isatty():
            print("Reading from stdin (Ctrl+D to end):", file=sys.stderr)
        question = sys.stdin.read().strip()
    else:
        question = args.question

    if not question:
        print("Error: No question provided", file=sys.stderr)
        return 1

    # Create client
    try:
        client = AuraAgentClient.from_env()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        print(
            "\nSet environment variables or create a .env file:", file=sys.stderr
        )
        print("  NEO4J_CLIENT_ID=...", file=sys.stderr)
        print("  NEO4J_CLIENT_SECRET=...", file=sys.stderr)
        print("  NEO4J_AGENT_ENDPOINT=...", file=sys.stderr)
        return 1

    # Invoke agent
    try:
        response = client.invoke(question)

        # Output
        if args.raw and response.raw_response:
            print(json.dumps(response.raw_response, indent=2))
        elif args.json:
            output = {
                "text": response.text,
                "status": response.status,
                "thinking": response.thinking,
                "tool_uses": (
                    [tu.model_dump() for tu in response.tool_uses]
                    if response.tool_uses
                    else None
                ),
                "usage": response.usage.model_dump() if response.usage else None,
            }
            print(json.dumps(output, indent=2))
        else:
            if response.text:
                print(response.text)
            else:
                print("(No text response)", file=sys.stderr)
                if args.verbose and response.raw_response:
                    print(
                        f"Raw response: {json.dumps(response.raw_response, indent=2)}",
                        file=sys.stderr,
                    )

        return 0

    except AuraAgentError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
