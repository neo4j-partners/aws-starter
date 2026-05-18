"""Shared logic for the Neo4j MCP ReAct agents.

Both the production agent (`agent.py`, auto-refreshing OAuth2) and the simple
agent (`simple_agent.py`, static token) build on these helpers. The only
difference between them is how credentials are resolved, which callers inject
as the `load` callable.
"""

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient

# Credentials live at the project root (agent.sh runs from there).
CREDENTIALS_FILE = Path(".mcp-credentials.json")

# Single source of truth for model and region. The region here is only a
# fallback: the actual region is read from `.mcp-credentials.json` at runtime.
MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_REGION = "us-east-1"

SYSTEM_PROMPT = """You are a helpful Neo4j database assistant with access to tools that let you query a Neo4j graph database.

Your capabilities include:
- Retrieve the database schema to understand node labels, relationship types, and properties
- Execute read-only Cypher queries to answer questions about the data
- Do not execute any write Cypher queries

When answering questions about the database:
1. First retrieve the schema to understand the database structure
2. Formulate appropriate Cypher queries based on the actual schema
3. If a query returns no results, explain what you looked for and suggest alternatives
4. Format results in a clear, human-readable way
5. Cite the actual data returned in your response

Important Cypher notes:
- Use MATCH patterns that align with the actual schema
- For counting, use MATCH (n:Label) RETURN count(n)
- For listing items, add LIMIT to avoid overwhelming results
- Handle potential NULL values gracefully

Be concise but thorough in your responses."""

DEMO_QUESTIONS = [
    ("Database Schema Overview", "What is the database schema? Give me a brief summary."),
    ("Count of Aircraft", "How many Aircraft are in the database?"),
    ("List Airports", "List 5 airports with their city and country."),
    ("Recent Maintenance Events", "Show me 3 recent maintenance events with their severity."),
    ("Flight Statistics", "How many flights are in the database and what operators fly them?"),
]

# A loader returns the resolved credentials dict (production refreshes the
# token first; the simple agent just reads the file).
CredentialsLoader = Callable[[], dict]


def load_credentials() -> dict:
    """Load credentials from .mcp-credentials.json."""
    if not CREDENTIALS_FILE.exists():
        print("ERROR: Credentials file not found: .mcp-credentials.json")
        print()
        print("Copy it from your neo4j-agentcore-mcp-server deployment:")
        print("  cp ../neo4j-agentcore-mcp-server/.mcp-credentials.json .")
        sys.exit(1)

    with open(CREDENTIALS_FILE) as f:
        return json.load(f)


def get_llm(region: str = DEFAULT_REGION):
    """Get the LLM for the agent (AWS Bedrock Claude via Converse API)."""
    return init_chat_model(
        MODEL_ID,
        model_provider="bedrock_converse",
        region_name=region,
        temperature=0,
    )


async def run_agent(question: str, load: CredentialsLoader, label: str = "") -> None:
    """Run the ReAct agent for a single question.

    `load` resolves credentials each call so the production agent can refresh
    an expiring token before every query.
    """
    title = f"Neo4j MCP Agent{label}"
    print("=" * 70)
    print(title)
    print("=" * 70)
    print()

    print("Loading credentials...")
    credentials = load()

    gateway_url = credentials["gateway_url"]
    access_token = credentials["access_token"]
    region = credentials.get("region", DEFAULT_REGION)

    print(f"Gateway: {gateway_url}")
    if credentials.get("token_expires_at"):
        print(f"Token expires: {credentials['token_expires_at']}")
    print()

    print(f"Initializing LLM (Bedrock, region: {region})...")
    llm = get_llm(region)
    print(f"Using: {MODEL_ID}")
    print()

    print("Connecting to MCP server...")
    client = MultiServerMCPClient(
        {
            "neo4j": {
                "transport": "streamable_http",
                "url": gateway_url,
                "headers": {"Authorization": f"Bearer {access_token}"},
            }
        }
    )

    tools = await client.get_tools()
    print(f"Loaded {len(tools)} tools:")
    for tool in tools:
        print(f"  - {tool.name}")
    print()

    print("Creating agent...")
    agent = create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)

    print("=" * 70)
    print(f"Question: {question}")
    print("=" * 70)
    print()

    result = await agent.ainvoke({"messages": [("human", question)]})

    messages = result.get("messages", [])
    if not messages:
        print("No response from agent")
        return

    final_message = messages[-1]
    if hasattr(final_message, "content"):
        print("Answer:")
        print("-" * 70)
        print(final_message.content)
        print("-" * 70)
    else:
        print("Answer:", final_message)


async def run_demo(load: CredentialsLoader, label: str = "") -> None:
    """Run the demo queries to showcase the agent capabilities."""
    print()
    print("#" * 76)
    print("#" + f"NEO4J MCP AGENT DEMO{label}".center(74) + "#")
    print("#" * 76)
    print()

    for i, (heading, question) in enumerate(DEMO_QUESTIONS, 1):
        print()
        print("=" * 76)
        print(f"  QUERY {i}: {heading}")
        print("=" * 76)
        print()
        await run_agent(question, load, label)
        print()

    print()
    print("#" * 76)
    print("#" + "DEMO COMPLETE".center(74) + "#")
    print("#" * 76)


def main(load: CredentialsLoader, label: str = "") -> None:
    """CLI entry point: run a demo with no args, or answer a question."""
    if len(sys.argv) < 2:
        asyncio.run(run_demo(load, label))
    else:
        question = " ".join(sys.argv[1:])
        asyncio.run(run_agent(question, load, label))
