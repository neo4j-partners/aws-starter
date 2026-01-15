"""
Sample 2: MCP Server for AgentCore Runtime

A simple MCP (Model Context Protocol) server demonstrating:
- Tool definitions with @mcp.tool() decorator
- Stateless HTTP transport (required by AgentCore)
- Proper server configuration for cloud deployment
"""
from mcp.server.fastmcp import FastMCP

# Create MCP server instance
# - host="0.0.0.0" allows connections from any interface (required for containers)
# - stateless_http=True is REQUIRED for AgentCore Runtime
mcp = FastMCP(
    name="sample-mcp-server",
    host="0.0.0.0",
    stateless_http=True,
)


@mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@mcp.tool()
def multiply_numbers(a: int, b: int) -> int:
    """Multiply two numbers together."""
    return a * b


@mcp.tool()
def greet_user(name: str) -> str:
    """Greet a user by name."""
    return f"Hello, {name}! Welcome to AgentCore."


@mcp.tool()
def get_server_info() -> dict:
    """Get information about this MCP server."""
    return {
        "name": "Sample MCP Server",
        "version": "1.0.0",
        "description": "A learning sample for AgentCore MCP hosting",
        "tools_available": [
            "add_numbers",
            "multiply_numbers",
            "greet_user",
            "get_server_info",
        ],
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
