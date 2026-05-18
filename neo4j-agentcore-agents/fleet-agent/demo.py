#!/usr/bin/env python3
"""Fleet Agent functionality showcase — console demo.

Walks the agent's full surface area, section by section, in plain English:

  1. The live graph schema the agent reasons over.
  2. The ``graph_query`` retriever on its own (Text2Cypher: Claude writes
     read-only Cypher from the schema).
  3. The ``vector_search`` retriever on its own (semantic search over
     maintenance-manual chunks).
  4. The full Strands ReAct agent, choosing tools by itself.

Every section starts with a ``====`` banner and a one-line, plain-English
statement of what it is showing. Run it straight through:

    uv run python demo.py
"""

from __future__ import annotations

import logging
import textwrap

from strands import Agent
from strands.models import BedrockModel
from tools import graph_query_tool, vector_search_tool

from common import (
    AWS_REGION,
    MODEL_ID,
    SYSTEM_PROMPT_TEMPLATE,
    close,
    get_graph_schema,
    graph_query,
    vector_search,
)

# The retrievers log at INFO (schema fetch, generated Cypher). Keep them, but
# silence HTTP client chatter so the demo output stays readable.
logging.basicConfig(level=logging.INFO, format="%(message)s")
for noisy in (
    "httpx",
    "httpcore",
    "boto3",
    "botocore",
    "urllib3",
    "strands",
    "neo4j",
):
    logging.getLogger(noisy).setLevel(logging.WARNING)
# The driver logs every server PERFORMANCE notice at WARNING; mute those.
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

WIDTH = 78


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


def section_schema() -> None:
    banner(
        "SECTION 1 — What the agent knows about the database",
        "Before answering anything, the agent loads the live Neo4j schema "
        "(node types and how they connect) once per process and puts it in "
        "its system prompt. This is that schema — the map it reasons over.",
    )
    show("Live graph schema", get_graph_schema())


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
        show("graph_query result", graph_query(q))


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
        show("Top matching manual chunks", vector_search(q, top_k=2))


def section_agent() -> None:
    banner(
        "SECTION 4 — The full ReAct agent, choosing tools by itself",
        "Now the real agent runs. Given only a question, Claude decides "
        "which tool to call (graph_query for structured facts, "
        "vector_search for manual text), may chain several calls, then "
        "writes a final answer. We feed it one structured question, one "
        "manual-text question, and one that needs both.",
    )
    schema = get_graph_schema()
    agent = Agent(
        model=BedrockModel(
            model_id=MODEL_ID,
            region_name=AWS_REGION,
            temperature=0.0,
            streaming=False,
        ),
        tools=[graph_query_tool, vector_search_tool],
        system_prompt=SYSTEM_PROMPT_TEMPLATE.format(schema=schema),
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
        result = agent(q)
        show("Agent answer", str(result))


def main() -> None:
    print()
    print("#" * WIDTH)
    print("#" + "FLEET AGENT — FUNCTIONALITY SHOWCASE".center(WIDTH - 2) + "#")
    print("#" * WIDTH)
    try:
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
    finally:
        close()


if __name__ == "__main__":
    main()
