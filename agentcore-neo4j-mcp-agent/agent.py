#!/usr/bin/env python3
"""
Neo4j MCP Agent - AgentCore Runtime

A ReAct agent that connects to the Neo4j MCP server via AgentCore Gateway
and answers natural language questions about the database.

Deployed on Amazon Bedrock AgentCore Runtime.

Local testing:
    python agent.py                     # Start server on port 8080
    curl -X POST http://localhost:8080/invocations \
        -H "Content-Type: application/json" \
        -d '{"prompt": "What is the database schema?"}'

Cloud deployment:
    agentcore configure -e agent.py
    agentcore deploy
    agentcore invoke '{"prompt": "What is the database schema?"}'
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Reduce noise from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Create the AgentCore app
app = BedrockAgentCoreApp()

# Configuration
CREDENTIALS_FILE = Path(__file__).parent / ".mcp-credentials.json"
MODEL_ID = os.getenv("MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")

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


def load_credentials() -> dict:
    """Load credentials from .mcp-credentials.json."""
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Credentials file not found: {CREDENTIALS_FILE}\n"
            "Create .mcp-credentials.json with gateway_url, access_token, etc."
        )

    with open(CREDENTIALS_FILE) as f:
        return json.load(f)


def check_token_expiry(credentials: dict) -> bool:
    """Check if the token is expired or expiring soon. Returns True if valid."""
    expires_at_str = credentials.get("token_expires_at")
    if not expires_at_str:
        return False

    try:
        expires_at = datetime.fromisoformat(expires_at_str)
        now = datetime.now(timezone.utc)
        return now < (expires_at - timedelta(minutes=5))
    except (ValueError, TypeError):
        return False


def refresh_token(credentials: dict) -> dict:
    """Refresh the OAuth2 access token using client credentials."""
    token_url = credentials.get("token_url")
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    scope = credentials.get("scope")

    if not all([token_url, client_id, client_secret]):
        raise ValueError(
            "Missing token refresh credentials (token_url, client_id, client_secret)"
        )

    logger.info("Refreshing OAuth2 token...")
    response = httpx.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    response.raise_for_status()
    token_data = response.json()

    expires_in = token_data.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    credentials["access_token"] = token_data["access_token"]
    credentials["token_expires_at"] = expires_at.isoformat()

    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(credentials, f, indent=2)

    logger.info(f"Token refreshed. Expires: {expires_at.isoformat()}")
    return credentials


def get_llm(region: str = AWS_REGION):
    """Get the LLM to use for the agent (AWS Bedrock Claude via Converse API)."""
    import boto3
    bedrock_client = boto3.client("bedrock-runtime", region_name=region)
    return init_chat_model(
        client=bedrock_client,
        model=MODEL_ID,
        model_provider="bedrock_converse",
        temperature=0,
    )


def extract_prompt_from_payload(payload: dict) -> tuple[str | None, str, str]:
    """
    Extract prompt and context from payload, supporting multiple field names.

    Args:
        payload: Request payload dictionary

    Returns:
        Tuple of (prompt, session_id, user_id)
    """
    # Support multiple field names for flexibility
    prompt = (
        payload.get("prompt")
        or payload.get("message")
        or payload.get("query")
        or payload.get("inputText")
        or payload.get("input")
    )

    session_id = payload.get("session_id", "default_session")
    user_id = payload.get("user_id", "default_user")

    return prompt, session_id, user_id


@app.entrypoint
async def invoke(payload: dict = None):
    """
    AgentCore Runtime handler function.

    Connects to Neo4j MCP server via Gateway and processes natural language queries.

    Args:
        payload: Event payload containing 'prompt', 'message', 'query', or 'inputText'

    Yields:
        dict: Response chunks for streaming
    """
    logger.info(f"Received request with payload keys: {list(payload.keys()) if payload else []}")

    if payload is None:
        payload = {}

    # Extract prompt from various possible fields
    prompt, session_id, user_id = extract_prompt_from_payload(payload)

    if not prompt:
        logger.warning("No prompt provided in request")
        yield {"type": "error", "error": "No prompt provided. Please include 'prompt' in your request."}
        return

    logger.info(f"Processing query for user {user_id}, session {session_id}: {prompt[:100]}...")

    try:
        # Load and validate credentials
        logger.info("Loading credentials...")
        credentials = load_credentials()

        # Auto-refresh token if expired
        if not check_token_expiry(credentials):
            credentials = refresh_token(credentials)

        gateway_url = credentials["gateway_url"]
        access_token = credentials["access_token"]
        region = credentials.get("region", AWS_REGION)

        logger.info(f"Gateway: {gateway_url}")
        logger.info(f"Model: {MODEL_ID}")

        # Initialize LLM
        llm = get_llm(region)

        # Connect to MCP server via Gateway using context manager
        logger.info("Connecting to MCP server...")
        mcp_client = MultiServerMCPClient(
            {
                "neo4j": {
                    "transport": "streamable_http",
                    "url": gateway_url,
                    "headers": {
                        "Authorization": f"Bearer {access_token}",
                    },
                }
            }
        )

        # Get available tools
        tools = await mcp_client.get_tools()
        logger.info(f"Loaded {len(tools)} tools: {[t.name for t in tools]}")

        # Create the ReAct agent (LangGraph best practice pattern)
        agent = create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)

        # Run the agent with streaming
        logger.info("Running agent...")
        response_text = ""
        async for message_chunk, metadata in agent.astream(
            {"messages": [("human", prompt)]},
            stream_mode="messages"
        ):
            if message_chunk.content:
                for content in message_chunk.content:
                    if isinstance(content, dict) and 'text' in content:
                        response_text += content['text']
                    elif isinstance(content, str):
                        response_text += content

        if not response_text:
            response_text = "No response from agent"

        # Stream the response in chunks (for compatibility with streaming clients)
        yield {"type": "chunk", "data": response_text}
        yield {"type": "complete"}

        logger.info("Request completed successfully")

    except FileNotFoundError as e:
        logger.error(f"Credentials error: {e}")
        yield {
            "type": "error",
            "error": str(e),
            "hint": "Ensure .mcp-credentials.json exists with gateway_url and access_token",
        }
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
        yield {
            "type": "error",
            "error": f"HTTP error {e.response.status_code}: {e.response.text}",
        }
    except Exception as e:
        logger.error(f"Error processing request: {e}", exc_info=True)
        yield {
            "type": "error",
            "error": f"Error processing your request: {str(e)}\n\nPlease try rephrasing your question or check the logs.",
        }


if __name__ == "__main__":
    logger.info(f"Starting Neo4j MCP Agent with model: {MODEL_ID}")
    app.run()
