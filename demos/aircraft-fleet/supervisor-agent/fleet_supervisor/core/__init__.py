"""Building blocks for the supervisor agent.

- :mod:`core.config`: model ID, region, token cap, effort, and local port
- :mod:`core.credentials`: reads ``.mcp-credentials.json``
- :mod:`core.mcp`: the Gateway ``MCPClient`` and its tool filters
- :mod:`core.model`: the shared ``BedrockModel``
- :mod:`core.prompts`: supervisor and specialist system prompts
- :mod:`core.agents`: builds the supervisor with its specialists as tools
- :mod:`core.events`: maps Strands stream events to client SSE events
"""
