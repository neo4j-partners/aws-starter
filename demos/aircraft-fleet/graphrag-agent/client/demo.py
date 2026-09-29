#!/usr/bin/env python3
"""Fleet Agent functionality showcase — console demo.

Walks the agent's full surface area, section by section, in plain English:

  1. The live graph schema the agent reasons over.
  2. The ``graph_query`` retriever on its own (Text2Cypher).
  3. The ``vector_search`` retriever on its own (semantic search).
  4. The full Strands ReAct agent, choosing tools by itself.

This is a pure client. Every section is served by a running
``runtime_app.py`` through the matching payload mode — nothing is built
in-process:

  - section 1 -> ``{"mode": "schema"}``
  - section 2 -> ``{"mode": "graph_query", "query": ...}``
  - section 3 -> ``{"mode": "vector_search", "query": ..., "top_k": 2}``
  - section 4 -> ``{"prompt": ...}``  (the full agent)

The per-section questions below are hand-written narration for the showcase;
they are intentionally separate from ``queries.txt`` (the load/demo list).

    uv run python -m client.demo            # local server (./agent.sh start)
    uv run python -m client.demo --remote   # the deployed AgentCore runtime
"""

from __future__ import annotations

import argparse
import logging
import textwrap

from client.transport import Target, invoke

logging.basicConfig(level=logging.WARNING, format="%(message)s")

WIDTH = 78

# Set by main(); selects the transport for every section.
TARGET: Target = "local"


def banner(title: str, plain_english: str) -> None:
    """Print a ``====`` section header and a plain-English description."""
    print()
    print("=" * WIDTH)
    print(f"  {title}")
    print("=" * WIDTH)
    for line in textwrap.wrap(plain_english, WIDTH - 4):
        print(f"  {line}")
    print("=" * WIDTH)
    print()


def show(label: str, body: str) -> None:
    """Print a labeled, indented block of result text."""
    print(f"--- {label} ---")
    print(textwrap.indent(body.strip(), "    "))
    print()


def call(payload: dict) -> str:
    """Send one payload to the runtime and return its assembled text answer.

    Streaming is suppressed so each section can format the result with
    ``show()``.
    """
    result = invoke(payload, target=TARGET, stream=False)
    if result.get("status") != "success":
        return f"[error] {result.get('errors', ['Unknown error'])}"
    return result["response"]


def section_schema() -> None:
    banner(
        "SECTION 1 — What the agent knows about the database",
        "Before answering anything, the agent loads the live Neo4j schema "
        "(node types and how they connect) once per process and puts it in "
        "its system prompt. This is that schema — the map it reasons over.",
    )
    show("Live graph schema", call({"mode": "schema"}))


def section_graph_query() -> None:
    banner(
        "SECTION 2 — graph_query retriever, used directly (Text2Cypher)",
        "This calls the structured retriever with no agent in the loop. "
        "Claude turns each plain question into a READ-ONLY Cypher query from "
        "the schema, runs it, and returns the rows. Best for exact lookups, "
        "counts, aggregations, and relationship traversal.",
    )
    questions = [
        ("Simple count", "How many aircraft are in the fleet?"),
        (
            "Grouped aggregation",
            "How many aircraft do we have per manufacturer and model?",
        ),
        (
            "Relationship traversal",
            "List 5 maintenance events whose severity is 'CRITICAL', and for "
            "each show the affected aircraft tail_number and the fault.",
        ),
    ]
    for label, q in questions:
        print(f"Question ({label}): {q}")
        show("graph_query result", call({"mode": "graph_query", "query": q}))


def section_vector_search() -> None:
    banner(
        "SECTION 3 — vector_search retriever, used directly (semantic search)",
        "This calls the document retriever with no agent in the loop. The "
        "question is embedded and matched against maintenance-manual text "
        "chunks by meaning, not keywords. Best for 'what does the manual say "
        "about...' questions where exact wording varies.",
    )
    queries = [
        "What is the procedure for detecting a hydraulic system leak?",
        "How do I troubleshoot an engine exhaust gas temperature exceedance?",
    ]
    for q in queries:
        print(f"Search text: {q}")
        show(
            "Top matching manual chunks",
            call({"mode": "vector_search", "query": q, "top_k": 2}),
        )


def section_agent() -> None:
    banner(
        "SECTION 4 — The full ReAct agent, choosing tools by itself",
        "Now the real agent runs. Given only a question, Claude decides "
        "which tool to call (graph_query for structured facts, "
        "vector_search for manual text), may chain several calls, then "
        "writes a final answer. We feed it one structured question, one "
        "manual-text question, and one that needs both.",
    )
    questions = [
        ("Structured", "Which operator has the worst on-time performance, "
         "and how many delays do they have?"),
        ("Manual text", "What does the maintenance manual recommend for "
         "hydraulic reservoir low-level warnings?"),
        ("Needs both", "For maintenance events whose fault is 'Vibration "
         "exceedance', what corrective actions were taken, and what does "
         "the manual say the correct engine-vibration troubleshooting "
         "procedure is?"),
    ]
    for label, q in questions:
        print(f"User ({label}): {q}")
        print("--- Agent answer ---")
        # Streamed (unlike the buffered sections above) so the ``→ tool``
        # boundaries print live as the agent calls graph_query/vector_search.
        result = invoke({"prompt": q}, target=TARGET, stream=True)
        if result.get("status") != "success":
            print(f"[error] {result.get('errors', ['Unknown error'])}")
        print()


def main() -> None:
    global TARGET
    parser = argparse.ArgumentParser(
        description="Fleet Agent functionality showcase."
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help=(
            "Drive the deployed AgentCore runtime instead of the local "
            "server on port 8080."
        ),
    )
    TARGET = "deployed" if parser.parse_args().remote else "local"

    mode_line = (
        "DEPLOYED: AgentCore runtime"
        if TARGET == "deployed"
        else "LOCAL: runtime_app.py on port 8080"
    )
    print()
    print("#" * WIDTH)
    print("#" + "FLEET AGENT — FUNCTIONALITY SHOWCASE".center(WIDTH - 2) + "#")
    print("#" + mode_line.center(WIDTH - 2) + "#")
    print("#" * WIDTH)

    section_schema()
    section_graph_query()
    section_vector_search()
    section_agent()
    banner(
        "DONE",
        "You have seen the schema the agent reasons over, each GraphRAG "
        "retriever on its own, and the full agent choosing tools "
        "end to end.",
    )


if __name__ == "__main__":
    main()
