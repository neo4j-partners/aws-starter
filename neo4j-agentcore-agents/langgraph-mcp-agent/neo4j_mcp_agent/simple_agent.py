#!/usr/bin/env python3
"""Simple Neo4j MCP Agent.

A minimal ReAct agent that connects to the Neo4j MCP server via AgentCore
Gateway using the static `access_token` from `.mcp-credentials.json`. There is
no token refresh, so it stops working once the token expires (~1 hour). Use it
for quick tests and for learning the agent flow; use `agent.py` for anything
long-running.

Usage:
    python -m neo4j_mcp_agent.simple_agent                    # Run demo queries
    python -m neo4j_mcp_agent.simple_agent "your question"    # Ask a question
"""

from neo4j_mcp_agent.core import load_credentials, main

if __name__ == "__main__":
    main(load_credentials, label=" (Simple)")
