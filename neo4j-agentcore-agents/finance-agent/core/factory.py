"""Strands-specific factories shared by the runtime and the local clients.

The Bedrock model and the MCP client are constructed identically wherever the
agent runs (deployed runtime, local CLI, demo). Centralizing them here keeps
the hyperparameters and the transport wiring in one place; importing this
module is what pulls the Strands dependency, so the rest of ``core`` stays
framework-agnostic.
"""

from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient

from core.config import AWS_REGION, MODEL_ID
from core.transport import create_transport


def build_model() -> BedrockModel:
    """The shared Bedrock model — same hyperparameters everywhere."""
    return BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.0,
        max_tokens=4096,
        streaming=True,
    )


def build_mcp_client() -> MCPClient:
    """MCP client whose transport resolves a fresh OAuth2 token per scope."""
    return MCPClient(create_transport)
