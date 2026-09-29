"""Thin clients for the Neo4j fleet agent.

Nothing here builds an agent. ``runtime_app.py`` is the only agent builder;
everything in this package talks to it over the wire, distinguished only by a
``target``:

- ``"local"``    — HTTP+SSE to a locally running ``runtime_app.py`` (``./agent.sh start``).
- ``"deployed"`` — the boto3 ``bedrock-agentcore`` data plane (``./agent.sh deploy``).

The single transport (:mod:`client.transport`) parses the same SSE event
shapes for both, so :mod:`client.cli`, :mod:`client.demo`, and
:mod:`client.invoke` are unaware of which target they hit.
"""
