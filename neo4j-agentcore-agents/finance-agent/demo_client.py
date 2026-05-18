#!/usr/bin/env python3
"""Finance Agent — demo client.

Showcases graph-native questions against the Neo4j transaction graph
(accounts, merchants, transfers, similarity, GDS metrics).

By default it runs an in-process Strands agent that talks to the Neo4j MCP
server through the AgentCore Gateway — no local server, no deployment, just
``uv run python demo_client.py``. Pass ``--remote`` to send the same
questions to the deployed AgentCore Runtime agent instead, so you can show
the identical demo locally and in the cloud.

Usage:
    uv run python demo_client.py                 # all questions, local
    uv run python demo_client.py --remote        # all questions, deployed
    uv run python demo_client.py --list          # print questions, run none
    uv run python demo_client.py -n 3            # only question 3, local
    uv run python demo_client.py -n 3 --remote   # only question 3, deployed

Prerequisites:
    - .mcp-credentials.json at the agent root (both modes use the Gateway)
    - AWS credentials with Bedrock access
    - --remote also needs a deployed agent (./agent.sh deploy) and the
      .bedrock_agentcore.yaml it writes
"""

import argparse
import logging
import sys
from collections.abc import Callable

# Configure logging before importing invoke_agent: logging.basicConfig is a
# no-op once handlers exist, so claiming it here keeps the demo output clean
# regardless of what the lazily-imported remote path would have set.
logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Curated to exercise what a graph database does that a flat store cannot:
# multi-hop transfer paths, pre-computed communities and centrality, and
# behavioral similarity. Mirrors the Demo table in README.md.
DEMO_QUESTIONS: list[str] = [
    "Which accounts have the highest risk scores, and who do they transfer "
    "money to?",
    "Find communities of accounts that transfer money among themselves but "
    "rarely transact with merchants.",
    "Show the accounts with the highest betweenness centrality and explain "
    "why they are money-flow intermediaries.",
    "Detect circular transfer chains where money leaves an account and "
    "returns to it, A to B to C to A.",
    "Pick a high-risk account, find behaviorally similar accounts via "
    "SIMILAR_TO, and check whether they share transfer counterparties.",
    "Which merchant categories see the most transaction volume by region?",
]


def make_local_runner() -> Callable[[str], None]:
    """Build the in-process Strands runner used for the default (local) mode.

    The model and MCP client are built once and the MCP context is entered
    once around the whole demo: the transport factory resolves a fresh OAuth2
    token on entry, and reusing the session avoids re-listing the Gateway
    tools for every question. Imports are local so ``--remote`` never pays
    the Strands import cost.
    """
    from mcp.client.streamable_http import streamablehttp_client
    from strands import Agent
    from strands.models import BedrockModel
    from strands.tools.mcp.mcp_client import MCPClient

    from common import AWS_REGION, MODEL_ID, SYSTEM_PROMPT, get_active_credentials

    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.0,
        max_tokens=4096,
        streaming=True,
    )

    def create_transport():
        credentials = get_active_credentials()
        return streamablehttp_client(
            credentials["gateway_url"],
            headers={"Authorization": f"Bearer {credentials['access_token']}"},
        )

    mcp_client = MCPClient(create_transport)
    print(f"Mode:  local in-process Strands agent (model: {MODEL_ID})")

    def run(question: str) -> None:
        # list_tools_sync / Agent require an open MCP scope; one scope wraps
        # the whole run so tools are listed once for the session.
        with mcp_client:
            tools = mcp_client.list_tools_sync()
            agent = Agent(model=model, tools=tools, system_prompt=SYSTEM_PROMPT)
            print(agent(question))

    return run


def make_remote_runner() -> Callable[[str], None]:
    """Build the deployed-agent runner used for ``--remote`` mode.

    Reuses ``invoke_agent.invoke_agent``, which reads the runtime ARN from
    ``.bedrock_agentcore.yaml`` and streams the SSE response to the terminal
    live. Errors are surfaced; success text has already been printed.
    """
    from invoke_agent import invoke_agent

    print("Mode:  deployed AgentCore Runtime agent (--remote)")

    def run(question: str) -> None:
        result = invoke_agent(question)
        if result.get("status") != "success":
            errors = result.get("errors", ["Unknown error"])
            print(f"ERROR: {errors}")

    return run


def run_demo(runner: Callable[[str], None], questions: list[str]) -> None:
    for i, question in enumerate(questions, 1):
        print()
        print("=" * 72)
        print(f"  [{i}/{len(questions)}] {question}")
        print("=" * 72)
        print()
        runner(question)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Showcase finance-agent demo questions, local or remote.",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Run against the deployed AgentCore agent instead of local",
    )
    parser.add_argument(
        "-n",
        "--number",
        type=int,
        metavar="N",
        help=f"Run only question N (1-{len(DEMO_QUESTIONS)})",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the demo questions and exit without running them",
    )
    args = parser.parse_args()

    if args.list:
        for i, question in enumerate(DEMO_QUESTIONS, 1):
            print(f"{i}. {question}")
        return

    if args.number is not None:
        if not 1 <= args.number <= len(DEMO_QUESTIONS):
            parser.error(
                f"-n must be between 1 and {len(DEMO_QUESTIONS)}"
            )
        questions = [DEMO_QUESTIONS[args.number - 1]]
    else:
        questions = DEMO_QUESTIONS

    try:
        runner = make_remote_runner() if args.remote else make_local_runner()
        run_demo(runner, questions)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as e:  # noqa: BLE001 - top-level CLI guard
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
