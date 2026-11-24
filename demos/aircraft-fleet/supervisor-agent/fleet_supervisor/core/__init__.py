"""Building blocks for the supervisor agent.

- :mod:`core.config`: model ID, region, token cap, effort, local port, and graph settings
- :mod:`core.secrets`: reads the Neo4j logins from Secrets Manager or the environment
- :mod:`core.graph`: the graph query and manual search tools, the schema, and the driver
- :mod:`core.model`: the shared ``BedrockModel``
- :mod:`core.prompts`: supervisor and specialist system prompts
- :mod:`core.agents`: builds the supervisor with its specialists as tools
- :mod:`core.events`: maps Strands stream events to client SSE events
- :mod:`core.tool_stream`: emits each tool result as a stream event when the trace is on
"""
