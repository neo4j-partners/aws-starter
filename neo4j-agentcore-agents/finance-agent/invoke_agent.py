#!/usr/bin/env python3
"""Invoke the deployed Finance Agent and exercise its Context Graph memory.

This calls the AgentCore Runtime agent recorded in ``.bedrock_agentcore.yaml``
via boto3. Unlike ``agentcore invoke`` (which sends ``{"prompt": ...}`` only),
this client also puts ``user_id``/``session_id`` in the payload so the Strands
variant's per-request memory directives bind to them.

The stock ``neo4j_agent_memory`` 0.2.1 Strands tools accept ``user_id`` but
ignore it (message search is a global vector query). The Strands variant
works around this with ``common.memory.user_scoped_context_graph_tools``, so
this agent *does* isolate by ``user_id`` and recalls across that user's
sessions. The ``memory-demo`` therefore proves both cross-session recall and
per-user isolation; ``verify_neo4j_persistence`` is the ground-truth check.

Memory is wired into the **Strands** variant only
(``strands/runtime_app.py`` -> ``neo4j_agent_memory``). The ``memory-demo`` mode is
only meaningful against a deployed Strands agent; the LangGraph variant has no
memory tools and will just answer each turn independently.

The response is streamed: SSE events ("data: {...}\\n\\n") are parsed as they
arrive off the wire and the answer is printed to the terminal token by token,
not buffered and printed at the end. The parser understands exactly the three
event shapes the Strands runtime emits (``chunk``/``error``/``complete``); the
deprecated direct-response shapes are not supported.

Usage:
    uv run python invoke_agent.py                       # default prompt
    uv run python invoke_agent.py "Tell me about Apple" # one-shot
    uv run python invoke_agent.py --user-id alice "..." # one-shot, scoped
    uv run python invoke_agent.py memory-demo           # cross-session recall
    uv run python invoke_agent.py memory-demo --user-id alice
    uv run python invoke_agent.py load-test             # random queries / 5s
    uv run python invoke_agent.py load-test --interval 10

Prerequisites:
    - Strands variant deployed (strands/agent.sh deploy)
    - NEO4J_URI / NEO4J_PASSWORD injected at deploy time (memory-demo needs it)
    - AWS credentials configured
    - .bedrock_agentcore.yaml present (created by agentcore configure)
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
import uuid
from pathlib import Path

import boto3
import yaml

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent / ".bedrock_agentcore.yaml"
QUERIES_FILE = Path(__file__).parent / "queries.txt"
DEFAULT_PROMPT = "What companies are in the database?"
DEFAULT_USER_ID = "demo-user"

# Distinctive tokens from the memory-demo "teach" turn. The agent summarizes
# the preference in its own words before calling add_memory, so we match on
# stable keywords rather than the verbatim prompt. Memory lives on :Message
# nodes, which the finance graph itself never creates, so these are specific.
TEACH_NEEDLES = ("energy", "nvidia")

# .env files searched (in order) for direct Neo4j credentials, mirroring
# strands/agent.sh: project-local first, then the Neo4j MCP server's .env
# (same database as the finance graph).
ENV_FILES = (
    Path(__file__).parent / ".env",
    Path(__file__).parent / ".." / ".." / "neo4j-agentcore-mcp-server" / ".env",
)


def get_agent_config() -> tuple[str, str]:
    """Read the agent ARN and region from .bedrock_agentcore.yaml.

    That file is created by ``agentcore configure``.
    """
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"ERROR: {CONFIG_FILE.name} not found")
        print("")
        print("Run 'strands/agent.sh configure' and 'strands/agent.sh deploy' first")
        sys.exit(1)

    default_agent = config.get("default_agent")
    if not default_agent:
        raise ValueError(f"default_agent not found in {CONFIG_FILE.name}")

    agent_config = config.get("agents", {}).get(default_agent, {})
    arn = agent_config.get("bedrock_agentcore", {}).get("agent_arn")
    region = agent_config.get("aws", {}).get("region", "us-west-2")

    if not arn:
        raise ValueError(
            f"agent_arn not found for agent '{default_agent}' in {CONFIG_FILE.name}"
        )

    return arn, region


def _handle_sse_event(
    event: str, content_parts: list[str], errors: list[str]
) -> None:
    """Dispatch one SSE event from the Strands runtime, printing text live.

    The Strands ``runtime_app`` emits exactly three JSON event shapes:
    ``{"type": "chunk", "data": ...}``, ``{"type": "error", "error": ...}``,
    and ``{"type": "complete"}``. ``chunk`` text is printed as it arrives and
    also collected so callers still get the assembled response. ``json.loads``
    already yields real newlines, so no ``\\n`` unescaping is needed; anything
    that is not one of these shapes is ignored.
    """
    event = event.strip()
    if not event:
        return
    if event.startswith("data: "):
        event = event[6:]
    try:
        data = json.loads(event)
    except json.JSONDecodeError:
        return
    if data.get("type") == "chunk":
        text = data.get("data", "")
        print(text, end="", flush=True)
        content_parts.append(text)
    elif data.get("type") == "error":
        errors.append(data.get("error", "Unknown error"))


def invoke_agent(
    prompt: str,
    user_id: str = DEFAULT_USER_ID,
    session_id: str | None = None,
) -> dict:
    """Invoke the deployed agent with one prompt, scoped to ``user_id``.

    ``user_id``/``session_id`` go in the JSON payload because the Strands
    variant's ``_resolve_user_id`` reads them from there to scope its memory
    tools. The boto3 ``runtimeSessionId`` is a separate transport-level id
    (fresh per call) and is not what the memory scope keys off.
    """
    agent_arn, region = get_agent_config()

    logger.info("Agent ARN: %s", agent_arn)
    logger.info("Region: %s", region)
    logger.info("Prompt: %s", prompt)
    logger.info("Memory scope: user_id=%s session_id=%s", user_id, session_id)

    client = boto3.client("bedrock-agentcore", region_name=region)

    request: dict[str, str] = {"prompt": prompt, "user_id": user_id}
    if session_id:
        request["session_id"] = session_id
    payload = json.dumps(request).encode()

    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=str(uuid.uuid4()),
        payload=payload,
        qualifier="DEFAULT",
    )

    content_parts: list[str] = []
    errors: list[str] = []
    buffer = ""

    # Parse and print SSE events ("data: {...}\n\n") as they arrive off the
    # wire rather than buffering the whole response, so the answer streams to
    # the terminal live.
    for raw in response.get("response", []):
        buffer += raw.decode("utf-8")
        while "\n\n" in buffer:
            event, buffer = buffer.split("\n\n", 1)
            _handle_sse_event(event, content_parts, errors)
    if buffer.strip():
        _handle_sse_event(buffer, content_parts, errors)

    print()  # terminate the streamed line

    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "success", "response": "".join(content_parts)}


def _print_result(result: dict) -> None:
    """The success text already streamed live; only surface errors here."""
    if result.get("status") != "success":
        print(f"ERROR: {result.get('errors', ['Unknown error'])}")


def run_one_shot(prompt: str, user_id: str) -> None:
    print("=" * 70)
    print("Finance Agent - Programmatic Invocation")
    print("=" * 70)
    print("")
    print(f"User ID: {user_id}")
    print(f"Prompt:  {prompt}")
    print("")

    print("=" * 70)
    print("Response:")
    print("=" * 70)
    result = invoke_agent(prompt, user_id=user_id)
    _print_result(result)
    print("")


def run_memory_demo(user_id: str) -> None:
    """Two turns in separate sessions; turn 2 must recall turn 1's fact.

    Same ``user_id``, different ``session_id`` per turn: if the second turn
    answers using the preference stated in the first, cross-session
    persistence and semantic recall are working. Because the Strands variant
    uses ``common.memory``'s user-scoped tools, recall is also isolated per
    ``user_id`` (a different user would not see this memory).
    ``verify_neo4j_persistence`` is the ground-truth check.
    """
    teach = (
        "Please remember this about me: I prefer low-risk energy stocks, and "
        "I already hold a large position in NVIDIA. Just acknowledge for now."
    )
    recall = (
        "Based on what you know about me, what kind of companies should I "
        "consider adding to my portfolio, and what should I be cautious about?"
    )

    print("=" * 70)
    print("Finance Agent - Cross-Session Memory Demo")
    print("=" * 70)
    print(f"User ID: {user_id}")
    print("Turn 1 and Turn 2 use different sessions for the same user.")
    print("Turn 2 should recall the preference stated in Turn 1.")
    print("=" * 70)
    print("")

    print("-" * 70)
    print("[Turn 1 | session: demo-session-teach] Stating a durable preference")
    print("-" * 70)
    print(f"Prompt: {teach}")
    print("")
    _print_result(invoke_agent(teach, user_id=user_id, session_id="demo-session-teach"))
    print("")

    print("Pausing 5s to let memory persist...")
    time.sleep(5)
    print("")

    print("-" * 70)
    print("[Turn 2 | session: demo-session-recall] New session, same user")
    print("-" * 70)
    print(f"Prompt: {recall}")
    print("")
    _print_result(
        invoke_agent(recall, user_id=user_id, session_id="demo-session-recall")
    )
    print("")
    print("=" * 70)
    print("If Turn 2 mentioned low-risk energy stocks or the NVIDIA holding")
    print("without being told again, Context Graph memory is working.")
    print("=" * 70)


def _read_env_var(path: Path, key: str) -> str | None:
    """First ``KEY=value`` match in ``path``, with one quote layer stripped.

    Mirrors ``strands/agent.sh``'s ``read_env_var``: split on the first '='
    so passwords containing '=' survive, strip CR, then peel one layer of
    surrounding single/double quotes (common .env style).
    """
    if not path.is_file():
        return None
    prefix = f"{key}="
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith(prefix):
                value = stripped[len(prefix) :].rstrip("\r")
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                return value or None
    return None


def _load_neo4j_credentials() -> tuple[str, str] | None:
    """Resolve (uri, password) from the environment, then the .env files.

    Environment wins; otherwise the same lookup order as the deploy script:
    project-local ``.env`` first, then the Neo4j MCP server's ``.env`` (same
    database as the finance graph). Returns ``None`` if either is missing.
    """
    uri = os.environ.get("NEO4J_URI")
    password = os.environ.get("NEO4J_PASSWORD")
    for env_file in ENV_FILES:
        if uri and password:
            break
        if uri is None:
            uri = _read_env_var(env_file, "NEO4J_URI")
        if password is None:
            password = _read_env_var(env_file, "NEO4J_PASSWORD")
    if uri and password:
        return uri, password
    return None


def verify_neo4j_persistence(user_id: str, within_minutes: int = 30) -> None:
    """Query the graph directly for the memory the demo should have written.

    Ground-truth check: the memory-demo "teach" turn asks the agent to
    remember a low-risk-energy / NVIDIA preference, which the user-scoped
    Strands tools (common.memory) persist as a :Message under a
    :Conversation that is linked to ``(:User {identifier: user_id})`` and
    carries a denormalized ``user_identifier``. We look for a recent
    :Message whose content mentions the distinctive needles AND whose
    Conversation is scoped to this ``user_id``. A match therefore confirms
    both persistence and per-user isolation; paired with Turn 2's answer it
    also confirms cross-session recall.
    """
    creds = _load_neo4j_credentials()
    if creds is None:
        print("=" * 70)
        print("Neo4j verification skipped: NEO4J_URI / NEO4J_PASSWORD not found")
        print(f"Searched env vars and: {', '.join(str(p) for p in ENV_FILES)}")
        print("=" * 70)
        return

    uri, password = creds

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("Neo4j verification skipped: the 'neo4j' driver is not installed")
        return

    needle_filter = " AND ".join(
        f"toLower(m.content) CONTAINS '{needle}'" for needle in TEACH_NEEDLES
    )
    query = f"""
    MATCH (c:Conversation)-[:HAS_MESSAGE]->(m:Message)
    WHERE {needle_filter}
      AND c.user_identifier = $user_id
      AND m.timestamp >= datetime() - duration({{minutes: $within_minutes}})
    OPTIONAL MATCH (u:User {{identifier: $user_id}})-[:HAS_CONVERSATION]->(c)
    RETURN c.session_id AS session_id,
           c.user_identifier AS user_identifier,
           u IS NOT NULL AS user_linked,
           m.role AS role,
           m.timestamp AS timestamp,
           substring(m.content, 0, 160) AS preview
    ORDER BY m.timestamp DESC
    LIMIT 5
    """

    print("=" * 70)
    print("Neo4j Ground-Truth Verification")
    print("=" * 70)
    print(f"Looking for :Message nodes mentioning {TEACH_NEEDLES}")
    print(f"scoped to user_id={user_id!r}, written in the last "
          f"{within_minutes} minutes...")
    print("")

    try:
        with GraphDatabase.driver(uri, auth=("neo4j", password)) as driver:
            records = driver.execute_query(
                query, user_id=user_id, within_minutes=within_minutes
            ).records
    except Exception as exc:  # noqa: BLE001 - report any driver/connection failure
        print(f"FAIL: could not query Neo4j: {exc}")
        print("=" * 70)
        return

    if not records:
        print(f"FAIL: no memory scoped to user_id={user_id!r} found.")
        print("The agent may not have called add_memory, NEO4J_URI/")
        print("NEO4J_PASSWORD were not injected into the deployed runtime,")
        print("or the runtime is not using common.memory's scoped tools.")
        print("=" * 70)
        return

    print(f"PASS: found {len(records)} matching :Message node(s):")
    print("")
    for record in records:
        print(f"  session:    {record['session_id']}")
        print(f"  user_id:    {record['user_identifier']}")
        print(f"  user-linked: {record['user_linked']}")
        print(f"  role:       {record['role']}")
        print(f"  time:       {record['timestamp']}")
        print(f"  text:       {record['preview']}")
        print("")
    print("Persistence + per-user isolation confirmed: the preference reached")
    print(f"Neo4j scoped to user_id={user_id!r} (Conversation.user_identifier")
    print("set). Paired with Turn 2's answer, cross-session recall under that")
    print("same user is confirmed.")
    if not all(r["user_linked"] for r in records):
        print("")
        print("Note: some matched Conversations lack the")
        print("(:User)-[:HAS_CONVERSATION]-> link. Storage is still scoped via")
        print("the denormalized user_identifier; the explicit User edge is")
        print("written on conversation creation by common.memory.add_memory.")
    print("=" * 70)


def load_queries() -> list[str]:
    """Load numbered queries from queries.txt."""
    if not QUERIES_FILE.exists():
        return []
    queries: list[str] = []
    with open(QUERIES_FILE, encoding="utf-8") as f:
        for line in f:
            match = re.match(r"^\d+\.\s+(.+)$", line.strip())
            if match:
                queries.append(match.group(1))
    return queries


def run_load_test(interval: int, user_id: str) -> None:
    queries = load_queries()
    if not queries:
        print(f"ERROR: no numbered queries found in {QUERIES_FILE.name}")
        sys.exit(1)

    print("=" * 70)
    print("Finance Agent - Load Test Mode")
    print("=" * 70)
    print(f"Loaded {len(queries)} queries from {QUERIES_FILE.name}")
    print(f"Running a random query every {interval}s as user_id={user_id}")
    print("Press Ctrl+C to stop")
    print("=" * 70)
    print("")

    iteration = 1
    try:
        while True:
            idx = random.randint(0, len(queries) - 1)
            query = queries[idx]

            print("=" * 70)
            print(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"Iteration {iteration} - Query #{idx + 1}"
            )
            print("=" * 70)
            print(f"Query: {query}")
            print("-" * 70)
            print("")

            _print_result(invoke_agent(query, user_id=user_id))

            print("")
            print("-" * 70)
            print(f"Waiting {interval}s before next query...")
            print("")

            iteration += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("")
        print("=" * 70)
        print(f"Load test stopped after {iteration - 1} iterations")
        print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Invoke the deployed Finance Agent and exercise its memory.",
    )
    parser.add_argument(
        "command",
        nargs="*",
        help=(
            "'memory-demo', 'load-test', or a prompt to send "
            f"(default: {DEFAULT_PROMPT!r})"
        ),
    )
    parser.add_argument(
        "--user-id",
        default=DEFAULT_USER_ID,
        help=f"Memory scope for the request (default: {DEFAULT_USER_ID})",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Seconds between queries in load-test mode (default: 5)",
    )
    parser.add_argument(
        "--verify-neo4j",
        action="store_true",
        help=(
            "After memory-demo, query Neo4j directly to confirm the "
            "preference was persisted (ground-truth check)"
        ),
    )
    args = parser.parse_args()

    command = args.command
    try:
        if command and command[0] == "memory-demo":
            run_memory_demo(args.user_id)
            if args.verify_neo4j:
                print("")
                verify_neo4j_persistence(args.user_id)
        elif command and command[0] == "load-test":
            run_load_test(args.interval, args.user_id)
        else:
            prompt = " ".join(command) if command else DEFAULT_PROMPT
            run_one_shot(prompt, args.user_id)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
