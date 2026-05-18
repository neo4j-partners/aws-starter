"""Finance Agent runtime server.

``runtime_app.py`` is the only place an Agent is built. It runs as a
standalone HTTP server: in the cloud under AgentCore Runtime (fixed port
8080), locally in the foreground of a terminal via ``uv run finance-server``
(port 7020, Ctrl+C to stop). The ``client`` package holds thin wire callers
that talk to it; nothing there builds an agent.
"""
