#!/usr/bin/env python3
"""Multi-Agent Orchestrator — AgentCore Runtime deployment.

A supervisor agent that classifies an incoming query and routes it to a
specialized worker:

- Maintenance Agent: reliability, faults, components, sensors
- Operations Agent: flights, delays, routes, airports

Credential loading / OAuth2 token refresh, the Bedrock LLM and MCP tool
factories, and the LangGraph routing graph all live in the shared ``core``
package; this module only wires them into the AgentCore entrypoint.

Local testing:
    uv run orchestrator-server
    curl -X POST http://localhost:8080/invocations \
        -H "Content-Type: application/json" \
        -d '{"prompt": "What are the most common maintenance faults?"}'

Cloud deployment:
    ./agent.sh configure
    ./agent.sh deploy
    ./agent.sh invoke-cloud "What are the most common maintenance faults?"
"""

import logging

import httpx
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain_core.messages import HumanMessage

from core import AWS_REGION, MODEL_ID, get_active_credentials
from core.factory import get_llm, get_mcp_tools
from core.graph import create_orchestrator_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Reduce noise from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = BedrockAgentCoreApp()


def extract_prompt_from_payload(payload: dict) -> tuple[str | None, str, str]:
    """Extract prompt and context from payload."""
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
    """AgentCore Runtime handler — routes to Maintenance or Operations."""
    logger.info(
        "[Orchestrator] Received request: %s",
        list(payload.keys()) if payload else [],
    )

    if payload is None:
        payload = {}

    prompt, session_id, _user_id = extract_prompt_from_payload(payload)

    if not prompt:
        logger.warning("No prompt provided")
        yield {"type": "error", "error": "No prompt provided. Include 'prompt' in request."}
        return

    logger.info("[Orchestrator] Query: %s...", prompt[:100])

    try:
        credentials = get_active_credentials()

        gateway_url = credentials["gateway_url"]
        access_token = credentials["access_token"]
        region = credentials.get("region", AWS_REGION)

        logger.info("[Orchestrator] Gateway: %s", gateway_url)

        llm = get_llm(region)
        tools = await get_mcp_tools(gateway_url, access_token)

        graph = await create_orchestrator_graph(llm, tools)

        logger.info("[Orchestrator] Running multi-agent graph...")
        config = {"configurable": {"thread_id": session_id}}

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=prompt)], "next_agent": ""},
            config=config,
        )

        response_text = ""
        if result.get("messages"):
            last_msg = result["messages"][-1]
            if hasattr(last_msg, "content"):
                response_text = last_msg.content

        if not response_text:
            response_text = "No response from orchestrator"

        logger.info("[Orchestrator] Request completed successfully")

        yield {"type": "chunk", "data": response_text}
        yield {"type": "complete"}

    except FileNotFoundError as e:
        logger.error("Credentials error: %s", e)
        yield {"type": "error", "error": str(e)}
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error: %s", e.response.status_code)
        yield {"type": "error", "error": f"HTTP error {e.response.status_code}"}
    except Exception as e:  # noqa: BLE001 — surface any failure to the caller
        logger.error("Error: %s", e, exc_info=True)
        yield {"type": "error", "error": f"Error: {str(e)}"}


def main():
    """Console-script entry point (``orchestrator-server``)."""
    logger.info("Starting Multi-Agent Orchestrator with model: %s", MODEL_ID)
    app.run()


if __name__ == "__main__":
    main()
