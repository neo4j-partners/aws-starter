#!/usr/bin/env python3
"""Finance Agent — demo client.

Showcases graph-native questions against the Neo4j transaction graph
(accounts, merchants, transfers, similarity, GDS metrics).

A thin client: it does not build an agent. It sends each question to a running
``server/runtime_app.py`` and streams the answer back. The default target is
the local server (``./agent.sh start``, port 7020); ``--remote`` sends the
same questions to the deployed AgentCore Runtime agent instead, so the demo is
identical locally and in the cloud.

Usage:
    uv run python -m client.demo                 # all questions, local server
    uv run python -m client.demo --remote        # all questions, deployed
    uv run python -m client.demo --memory        # Context Graph memory demo
    uv run python -m client.demo --list          # print questions, run none
    uv run python -m client.demo -n 3            # only question 3, local
    uv run python -m client.demo -n 3 --remote   # only question 3, deployed

Local use needs the server running in another terminal:
    ./agent.sh start

Prerequisites:
    - .mcp-credentials.json at the agent root (the server uses the Gateway)
    - AWS credentials with Bedrock access
    - --remote / --memory need a deployed agent (./agent.sh deploy) and the
      .bedrock_agentcore.yaml it writes
    - --memory needs a deployed agent that had NEO4J_URI/NEO4J_PASSWORD
      injected at deploy time; memory lives only in the deployed runtime
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable

from client.invoke import invoke_agent
from client.transport import Target, invoke

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


def make_runner(target: Target) -> Callable[[str], None]:
    """Build the runner for ``target``: a thin call to the running server.

    ``local`` posts to ``runtime_app.py`` on port 7020; ``deployed`` uses the
    boto3 data plane. Both stream the answer to the terminal live and only
    errors need surfacing here.
    """
    label = (
        "deployed AgentCore Runtime agent (--remote)"
        if target == "deployed"
        else "local server (runtime_app.py on port 7020)"
    )
    print(f"Mode:  {label}")

    def run(question: str) -> None:
        result = invoke({"prompt": question}, target=target, stream=True)
        if result.get("status") != "success":
            print(f"ERROR: {result.get('errors', ['Unknown error'])}")

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


# --- Memory demo -----------------------------------------------------------

# Distinctive preference taught in section 2 and recalled later. The needles
# (low-risk energy, NVIDIA) are specific enough to tell real recall apart
# from a generic hedge.
_MEM_TEACH = (
    "Please remember this about me: I prefer low-risk energy stocks, and I "
    "already hold a large position in NVIDIA. Just acknowledge for now."
)
_MEM_RECALL = (
    "Based on what you already know about me and my portfolio, what kinds of "
    "companies should I consider adding, and what should I be cautious about? "
    "If you have no information about me yet, say so plainly."
)


def _memory_section(
    n: int,
    total: int,
    title: str,
    explains: str,
    prompt: str,
    *,
    user_id: str,
    session_id: str,
    expect: str,
) -> None:
    """Run one labelled turn of the memory demo against the deployed agent.

    ``invoke_agent`` streams the answer to the terminal and returns a status
    dict. The scope (``user_id`` plus a fresh ``session_id`` per section) is
    printed so it is obvious which turns share a user and which do not.
    """
    print()
    print("=" * 72)
    print(f"  [{n}/{total}] {title}")
    print("=" * 72)
    print(explains)
    print(f"Scope:    user_id={user_id}  session_id={session_id}")
    print(f"Prompt:   {prompt}")
    print(f"Expected: {expect}")
    print("-" * 72)
    result = invoke_agent(prompt, user_id=user_id, session_id=session_id)
    if result.get("status") != "success":
        print(f"ERROR: {result.get('errors', ['Unknown error'])}")
    print()


def run_memory_demo() -> None:
    """Multi-section Context Graph memory showcase against the deployed agent.

    Memory exists only in the deployed runtime: ``server/runtime_app.py`` wires
    the user-scoped Context Graph tools. So this always targets the deployed
    agent through ``client.invoke.invoke_agent``. A per-run tag keeps the
    "before" section honest: a never-before-seen user starts with no memory
    regardless of how many times the demo has run.

    Sections, each isolating one property:
      1. Cold start          - same user, before teaching: nothing to recall
      2. Teaching             - same user: state a durable preference
      3. Cross-session recall - same user, brand-new session: it remembers
      4. Per-user isolation   - a different user: the memory does not leak
    """
    import time
    import uuid

    run_tag = uuid.uuid4().hex[:8]
    user = f"mem-demo-{run_tag}"
    other_user = f"mem-demo-other-{run_tag}"
    total = 4

    print("Mode:  deployed AgentCore Runtime agent, Context Graph memory")
    print(f"Run:   user_id={user!r} (isolation check uses {other_user!r})")

    _memory_section(
        1,
        total,
        "Cold start: the agent has never met this user",
        "Same user as the next sections, but nothing has been stored yet, so\n"
        "the agent should admit it knows nothing about this user's portfolio.",
        _MEM_RECALL,
        user_id=user,
        session_id="s1-cold",
        expect="agent states it has no information about you yet",
    )

    _memory_section(
        2,
        total,
        "Teaching: state a durable preference",
        "The user states a lasting preference. The agent should acknowledge\n"
        "it and persist it to the Context Graph via add_memory.",
        _MEM_TEACH,
        user_id=user,
        session_id="s2-teach",
        expect="agent acknowledges and stores the energy / NVIDIA preference",
    )

    print("Pausing 5s to let the write settle in Neo4j...")
    time.sleep(5)
    print()

    _memory_section(
        3,
        total,
        "Cross-session recall: a brand-new session, same user",
        "Different session_id, same user_id, and the preference is never\n"
        "restated. Recall here proves memory survives across sessions.",
        _MEM_RECALL,
        user_id=user,
        session_id="s3-recall",
        expect="agent recalls low-risk energy stocks and the NVIDIA holding",
    )

    _memory_section(
        4,
        total,
        "Per-user isolation: a different user asks the same question",
        "A different user_id asks the identical recall question. The first\n"
        "user's memory must not leak across the tenant boundary.",
        _MEM_RECALL,
        user_id=other_user,
        session_id="s4-other",
        expect="agent has no information for this different user",
    )

    print("=" * 72)
    print("  Summary")
    print("=" * 72)
    print(
        "If section 1 disclaimed any knowledge, section 3 recalled the energy\n"
        "/ NVIDIA preference without being told again, and section 4 knew\n"
        "nothing for the other user, then Context Graph memory is persisting,\n"
        "recalling across sessions, and isolating per user.\n"
        "\n"
        "Ground-truth check (re-runs a teach/recall for this user, then\n"
        "queries Neo4j directly for the persisted :Message node):\n"
        f"  uv run python -m client.invoke memory-demo --user-id {user} "
        "--verify-neo4j"
    )
    print("=" * 72)


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
        "--memory",
        action="store_true",
        help=(
            "Run the multi-section Context Graph memory demo against the "
            "deployed agent (ignores --remote / -n)"
        ),
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

    if args.memory:
        try:
            run_memory_demo()
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(130)
        except Exception as e:  # noqa: BLE001 - top-level CLI guard
            print(f"ERROR: {e}")
            sys.exit(1)
        return

    if args.number is not None:
        if not 1 <= args.number <= len(DEMO_QUESTIONS):
            parser.error(f"-n must be between 1 and {len(DEMO_QUESTIONS)}")
        questions = [DEMO_QUESTIONS[args.number - 1]]
    else:
        questions = DEMO_QUESTIONS

    target: Target = "deployed" if args.remote else "local"
    try:
        runner = make_runner(target)
        run_demo(runner, questions)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as e:  # noqa: BLE001 - top-level CLI guard
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
