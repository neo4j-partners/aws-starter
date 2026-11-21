"""Simulate the Neo4j Aura Agent by sending natural language questions to the
configured LLM, generating Cypher or vector searches, and executing them."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal

from neo4j import (
    READ_ACCESS,
    Driver,
    NotificationDisabledClassification,
    Query,
    Record,
    RoutingControl,
)
from neo4j.exceptions import DriverError, Neo4jError

from generator.specs import (
    COMPONENT_TYPES_BY_SYSTEM,
    DELAY_CAUSES,
    EVENT_SEVERITIES,
    MANUAL_FLEET_TAILS,
    SENSOR_TYPES,
)

from .display import WIDTH, header, records_table, show_cypher
from .query_errors import report_query_error
from .schema import _quote_identifier

# ---------------------------------------------------------------------------
# Graph schema description fed to the LLM for Cypher generation
# ---------------------------------------------------------------------------

# Tails for the sample questions. The first manual tail of each model is in
# every fleet of five or more aircraft, because the registry tails come
# first in round-robin order.
_FIRST_TAIL: dict[str, str] = {model: tails[0] for model, tails in MANUAL_FLEET_TAILS.items()}
# The shared-faults question needs two tails of one model, because manual
# Fault nodes are per aircraft model. The second B737 tail is the sixth
# registry aircraft, so these are in every fleet of six or more.
_SHARED_FAULT_TAILS: list[str] = MANUAL_FLEET_TAILS["B737-800"][:2]

# Value hints and notes the schema procedures cannot show, by label.
_LABEL_NOTES: dict[str, str] = {
    "System": f"type: {', '.join(COMPONENT_TYPES_BY_SYSTEM)}",
    "Sensor": f"type: {', '.join(sensor_type for sensor_type, _, _ in SENSOR_TYPES)}",
    "Delay": f"cause: {', '.join(DELAY_CAUSES)}",
    "MaintenanceEvent": f"severity: {', '.join(EVENT_SEVERITIES)}",
    "Removal": "hours_since_install and flight_hours_at_removal are flight hours",
    "Chunk": 'chunkId: "{documentId}:{index}"',
}

_NODE_PROPERTIES_Q = """\
CALL db.schema.nodeTypeProperties() YIELD nodeLabels, propertyName
RETURN nodeLabels, propertyName"""

# The count store pairs every label that starts a relationship type with
# every label that ends it, without reading any relationships. Some pairs
# may never be linked, so each one is checked against the data.
_SCHEMA_VISUALIZATION_Q = "CALL db.schema.visualization() YIELD nodes, relationships"

_MODELS_Q = """\
MATCH (a:Aircraft)
WHERE a.model IS NOT NULL
RETURN DISTINCT a.model AS model
ORDER BY model"""

# The tail of each model's lowest aircraft_id number, which is its first
# registry tail in a generated fleet. An aircraft_id is "AC" and a number.
# As text AC10000 sorts before AC1001, so the query sorts by the number.
_SAMPLE_TAILS_Q = """\
MATCH (a:Aircraft)
WHERE a.model IS NOT NULL AND a.tail_number IS NOT NULL
WITH a ORDER BY toInteger(substring(a.aircraft_id, 2))
WITH a.model AS model, collect(a)[0] AS first
RETURN model, first.tail_number AS tail
ORDER BY toInteger(substring(first.aircraft_id, 2))"""

_OPERATORS_Q = """\
MATCH (a:Aircraft)
WHERE a.operator IS NOT NULL
RETURN DISTINCT a.operator AS operator
ORDER BY operator"""

_AIRPORTS_Q = """\
MATCH (ap:Airport)
WHERE ap.iata IS NOT NULL
RETURN DISTINCT ap.iata AS iata
ORDER BY iata"""


def _domain_label(labels: list[str]) -> str | None:
    """Join a node's labels, leaving out internal ones such as __KGBuilder__."""
    domain = sorted(label for label in labels if not label.startswith("__"))
    return ":".join(domain) or None


def _printable(name: str) -> str:
    """Escape each character the terminal would not print, such as NUL or a newline."""
    return "".join(c if c.isprintable() else repr(c)[1:-1] for c in name)


def _warn_skipped(triples: set[tuple[str, str, str]], reason: str) -> None:
    if triples:
        shown = ", ".join(
            f"({_printable(start)})-[:{_printable(rel_type)}]->({_printable(end)})"
            for start, rel_type, end in sorted(triples)
        )
        print(f"  [WARN] skipped {len(triples)} relationship pattern(s) with {reason}: {shown}")


def _candidate_patterns(visualization: Record) -> list[tuple[str, str, str]]:
    """Return the (start label, type, end label) triples the count store allows.

    Triples with an internal label, such as __KGBuilder__, are left out.
    So are triples with a backslash in any name. Inside backticks Cypher
    decodes an escape such as \\u0060 to a backtick, so doubling backticks
    cannot keep such a name inside its quotes. Triples with a control
    character, such as NUL or a newline, are left out too. Each skipped
    triple is reported, since the schema then omits a real relationship.
    """
    names = {node.element_id: node["name"] for node in visualization["nodes"]}
    candidates = set()
    with_backslash = set()
    with_control = set()
    for rel in visualization["relationships"]:
        triple = (names[rel.start_node.element_id], rel.type, names[rel.end_node.element_id])
        if triple[0].startswith("__") or triple[2].startswith("__"):
            continue
        if any("\\" in name for name in triple):
            with_backslash.add(triple)
        elif any(unicodedata.category(c) == "Cc" for name in triple for c in name):
            with_control.add(triple)
        else:
            candidates.add(triple)
    _warn_skipped(with_backslash, "a backslash")
    _warn_skipped(with_control, "a control character")
    return sorted(candidates)


# Branches per pattern check query. Candidates grow with start labels times
# end labels, so the check runs in chunks to bound each query's size.
_CHECK_CHUNK = 150


def _pattern_check_queries(candidates: list[tuple[str, str, str]]) -> list[str]:
    """Return queries that yield the index of each candidate the data has.

    Each branch stops at the first matching relationship. Fixed labels let
    the planner start from a label scan. Neo4j 5.26 plans dynamic labels
    as a scan of every relationship, so the names are quoted into the text.
    """
    branches = [
        f"MATCH (:{_quote_identifier(start)})-[:{_quote_identifier(rel_type)}]->"
        f"(:{_quote_identifier(end)}) RETURN {index} AS candidate LIMIT 1"
        for index, (start, rel_type, end) in enumerate(candidates)
    ]
    return [
        "\nUNION ALL\n".join(branches[first : first + _CHECK_CHUNK])
        for first in range(0, len(branches), _CHECK_CHUNK)
    ]


def graph_schema(driver: Driver, database: str) -> str:
    """Describe the graph's labels, properties, and relationships for the LLM.

    Labels and properties come from db.schema.nodeTypeProperties. The
    relationship patterns come from db.schema.visualization, each checked
    against the data, so the description matches the database. A pattern
    names one label at each end, so a node with two labels gives a pattern
    for each. The models, sample tails, operators, and airport codes come
    from the data too. Value hints come from the generator specs.
    """
    # db.schema.nodeTypeProperties warns that its propertyTypes field will
    # change. The query does not use that field, so the warning is noise.
    # Notifications are filtered per session, so this query gets its own.
    with driver.session(
        database=database,
        default_access_mode=READ_ACCESS,
        notifications_disabled_classifications=[NotificationDisabledClassification.GENERIC],
    ) as session:
        property_rows = session.run(_NODE_PROPERTIES_Q).data()
        bookmarks = session.last_bookmarks()
    # On a partial database the fact queries can name a label or property
    # key that does not exist yet. The empty result is expected, so the
    # UNRECOGNIZED warning is noise. The first session's bookmarks make this
    # one read at least the state that one saw.
    with driver.session(
        database=database,
        default_access_mode=READ_ACCESS,
        notifications_disabled_classifications=[NotificationDisabledClassification.UNRECOGNIZED],
        bookmarks=bookmarks,
    ) as session:
        candidates = _candidate_patterns(session.run(_SCHEMA_VISUALIZATION_Q).single(strict=True))
        found = [
            row["candidate"]
            for query in _pattern_check_queries(candidates)
            for row in session.run(query).data()
        ]
        model_rows = session.run(_MODELS_Q).data()
        tail_rows = session.run(_SAMPLE_TAILS_Q).data()
        operator_rows = session.run(_OPERATORS_Q).data()
        airport_rows = session.run(_AIRPORTS_Q).data()

    # A label whose nodes have no properties comes back once with a null
    # propertyName. It is listed with an empty property set.
    properties: dict[str, set[str]] = {}
    for row in property_rows:
        if label := _domain_label(row["nodeLabels"]):
            names = properties.setdefault(label, set())
            if row["propertyName"] is not None:
                names.add(row["propertyName"])
    if not properties:
        print(f"  [WARN] No node labels in database {database!r}; run 'setup' first.\n")

    # Only an index the queries hold names a candidate.
    relationships = [candidates[index] for index in found if 0 <= index < len(candidates)]

    lines = ["Node labels and properties:"]
    for label in sorted(properties):
        line = f"- {label} {{{', '.join(sorted(properties[label]))}}}"
        # A node with several labels, such as Calibrated:Sensor, gets the
        # notes of each one.
        notes = [_LABEL_NOTES[name] for name in label.split(":") if name in _LABEL_NOTES]
        if notes:
            line += f"  ({'; '.join(notes)})"
        lines.append(line)
    lines += ["", "Relationships:"]
    lines += [f"- ({a})-[:{rel}]->({b})" for a, rel, b in sorted(relationships)]

    # A fact the database has no values for is left out.
    facts = {
        "Aircraft models": [row["model"] for row in model_rows],
        "Sample tail numbers": [f"{row['tail']} ({row['model']})" for row in tail_rows],
        "Operators": [row["operator"] for row in operator_rows],
        "Airport IATA codes": [row["iata"] for row in airport_rows],
    }
    fact_lines = [f"{name}: {', '.join(values)}." for name, values in facts.items() if values]
    if fact_lines:
        lines += ["", *fact_lines]
    return "\n".join(lines) + "\n"


_SYSTEM_PROMPT_RULES = """\
You are an expert Neo4j Cypher query generator for an aircraft digital twin \
knowledge graph. Given a natural language question, generate a single Cypher \
query that answers it.

Rules:
- Return ONLY the Cypher query text. No explanation, no markdown, no commentary.
- Do NOT wrap the query in backticks or code fences.
- The very first character of your response must be a Cypher keyword (MATCH, OPTIONAL, WITH, CALL, UNWIND, RETURN).
- Use the schema provided to write correct queries.
- Always LIMIT results to 10 unless the question specifies otherwise.
- Use tail_number (not aircraft_id) when displaying aircraft to users.
- For general "tell me about" questions, return the node's key properties.
- For "summary" questions, aggregate with count/collect grouped by relevant fields.
- For date filtering use datetime() or string comparison on ISO timestamps.
- Do not use deprecated Cypher syntax. Use modern CALL subqueries where needed.

Graph schema:
"""


def system_prompt(schema: str) -> str:
    """Return the text2cypher system prompt for a graph schema description."""
    return _SYSTEM_PROMPT_RULES + schema


VECTOR_SEARCH_PROMPT = """\
You are a query rewriter. Given a natural language question about aircraft \
maintenance, rewrite it as a short search phrase (3-8 words) optimized for \
semantic similarity search over maintenance manual chunks. Return ONLY the \
search phrase, nothing else."""

# ---------------------------------------------------------------------------
# Sample questions organized by agent tool type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SampleQuestion:
    question: str
    category: str
    tool: Literal["text2cypher", "similarity_search"]


SAMPLE_QUESTIONS: list[SampleQuestion] = [
    # -- Cypher Template style (answered via text2cypher) --
    SampleQuestion(
        f"Tell me about aircraft {_FIRST_TAIL['B737-800']}",
        "Aircraft Overview",
        "text2cypher",
    ),
    SampleQuestion(
        f"What are the sensor operating limits for {_FIRST_TAIL['A320-200']}?",
        "Sensor Operating Limits",
        "text2cypher",
    ),
    SampleQuestion(
        f"Show the maintenance summary for {_FIRST_TAIL['A321neo']}",
        "Maintenance Summary",
        "text2cypher",
    ),
    SampleQuestion(
        "What faults do aircraft {} and {} share?".format(*_SHARED_FAULT_TAILS),
        "Shared Faults",
        "text2cypher",
    ),
    SampleQuestion(
        f"What maintenance manual applies to {_FIRST_TAIL['A320-200']}?",
        "Manual Lookup",
        "text2cypher",
    ),
    # -- Text2Cypher style --
    SampleQuestion(
        "Which aircraft has the most critical maintenance events?",
        "Maintenance Analysis",
        "text2cypher",
    ),
    SampleQuestion(
        "What are the top causes of flight delays?",
        "Delay Analysis",
        "text2cypher",
    ),
    SampleQuestion(
        "Which airports have the most delayed arrivals?",
        "Delay Analysis",
        "text2cypher",
    ),
    SampleQuestion(
        "Show all components in the hydraulics system",
        "Topology",
        "text2cypher",
    ),
    SampleQuestion(
        "Which sensors have operating limits defined?",
        "Cross-Domain",
        "text2cypher",
    ),
    SampleQuestion(
        "Trace the provenance of the EGT operating limit for B737-800",
        "Cross-Domain",
        "text2cypher",
    ),
    # -- Similarity Search style --
    SampleQuestion(
        "How do I troubleshoot engine vibration?",
        "Troubleshooting",
        "similarity_search",
    ),
    SampleQuestion(
        "What are the EGT limits during takeoff?",
        "Operating Limits",
        "similarity_search",
    ),
    SampleQuestion(
        "What is the engine inspection schedule?",
        "Scheduled Maintenance",
        "similarity_search",
    ),
]


# ---------------------------------------------------------------------------
# LLM client abstraction
# ---------------------------------------------------------------------------


# Claude counts adaptive thinking toward max_tokens, so leave room for the
# Cypher after it. "low" effort matches the extraction pipeline.
_CHAT_MAX_TOKENS = 4000
_CLAUDE_THINKING = {"type": "adaptive"}
_CLAUDE_OUTPUT_CONFIG = {"effort": "low"}


def _create_llm_client(
    provider: str,
    *,
    openai_key: str | None = None,
    anthropic_key: str | None = None,
    region: str | None = None,
    llm_model: str,
    embedding_model: str,
    embedding_dimensions: int,
):
    """Return an LLM callable and an embed callable based on the provider."""

    if provider == "bedrock":
        import boto3
        from neo4j_graphrag.embeddings.bedrock import BedrockEmbeddings

        client = boto3.client("bedrock-runtime", **({"region_name": region} if region else {}))

        def chat(system: str, user: str) -> str:
            resp = client.converse(
                modelId=llm_model,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": _CHAT_MAX_TOKENS},
                additionalModelRequestFields={
                    "thinking": _CLAUDE_THINKING,
                    "output_config": _CLAUDE_OUTPUT_CONFIG,
                },
            )
            # With thinking on, a reasoningContent block comes before the text.
            content = resp["output"]["message"]["content"]
            return next((block["text"] for block in content if "text" in block), "")

        # The same embedder the pipeline uses for the chunk embeddings.
        embed = BedrockEmbeddings(
            model_id=embedding_model,
            dimensions=embedding_dimensions,
            region_name=region,
        ).embed_query

    elif provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=openai_key)

        def chat(system: str, user: str) -> str:
            resp = client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_completion_tokens=1000,
            )
            return resp.choices[0].message.content or ""

        def embed(text: str) -> list[float]:
            resp = client.embeddings.create(
                model=embedding_model,
                input=text,
                dimensions=embedding_dimensions,
            )
            return resp.data[0].embedding

    elif provider == "anthropic":
        import anthropic
        from openai import OpenAI

        anth_client = anthropic.Anthropic(api_key=anthropic_key)
        oai_client = OpenAI(api_key=openai_key)

        def chat(system: str, user: str) -> str:
            resp = anth_client.messages.create(
                model=llm_model,
                max_tokens=_CHAT_MAX_TOKENS,
                thinking=_CLAUDE_THINKING,
                output_config=_CLAUDE_OUTPUT_CONFIG,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            # With thinking on, a thinking block comes before the text.
            return next((block.text for block in resp.content if block.type == "text"), "")

        def embed(text: str) -> list[float]:
            resp = oai_client.embeddings.create(
                model=embedding_model,
                input=text,
                dimensions=embedding_dimensions,
            )
            return resp.data[0].embedding

    else:
        raise ValueError(f"Unknown provider: {provider!r}")

    return chat, embed


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------


def _extract_cypher(raw: str) -> str:
    """Extract a Cypher query from LLM output, stripping markdown fencing and preamble."""
    text = raw.strip()
    # Strip markdown fencing if present
    if "```" in text:
        lines = text.splitlines()
        in_block = False
        block_lines: list[str] = []
        for ln in lines:
            stripped = ln.strip()
            if stripped.startswith("```"):
                if in_block:
                    break
                in_block = True
                continue
            if in_block:
                block_lines.append(ln)
        if block_lines:
            return "\n".join(block_lines).strip()
    # If no fencing, find the first line that looks like Cypher
    for i, ln in enumerate(text.splitlines()):
        upper = ln.strip().upper()
        if upper.startswith(("MATCH", "OPTIONAL", "WITH", "CALL", "UNWIND", "RETURN")):
            return "\n".join(text.splitlines()[i:]).strip()
    return text


_MAX_RETRIES = 2
# Seconds the server lets one LLM-generated query run before it stops it.
_GENERATED_QUERY_TIMEOUT = 30


def _run_text2cypher(
    driver: Driver,
    database: str,
    chat_fn,
    prompt: str,
    question: str,
) -> None:
    """Send a question with the system prompt to the LLM, then run the Cypher it returns."""
    print(f'  Question: "{question}"\n')

    cypher = ""
    for attempt in range(_MAX_RETRIES):
        raw = chat_fn(prompt, question).strip()
        cypher = _extract_cypher(raw)
        if cypher:
            break
        if attempt < _MAX_RETRIES - 1:
            print("  (empty response, retrying...)")

    if not cypher:
        print("  [SKIP] LLM returned empty Cypher after retries.\n")
        return

    show_cypher(cypher, label="Generated Cypher")

    # LLM-generated Cypher runs in a read transaction, so the server rejects
    # any write it contains. The timeout stops a runaway query.
    try:
        records, _, _ = driver.execute_query(
            Query(cypher, timeout=_GENERATED_QUERY_TIMEOUT),
            database_=database,
            routing_=RoutingControl.READ,
        )
        rows = [dict(r) for r in records]
        records_table(rows)
    except Neo4jError as exc:
        print(f"  [ERROR] Cypher execution failed: {exc.code}: {exc.message}\n")


def _run_similarity_search(
    driver: Driver,
    database: str,
    chat_fn,
    embed_fn,
    question: str,
    top_k: int = 5,
) -> None:
    """Embed the question and run a vector similarity search over chunks."""
    print(f'  Question: "{question}"\n')

    # Rewrite question into a search phrase. An empty rewrite would embed
    # an empty string, so fall back to the original question.
    search_phrase = chat_fn(VECTOR_SEARCH_PROMPT, question).strip()
    if not search_phrase:
        print("  [WARN] Empty search phrase from the LLM. Using the question.")
        search_phrase = question
    print(f'  Search phrase: "{search_phrase}"\n')

    embedding = embed_fn(search_phrase)

    query = """\
CALL db.index.vector.queryNodes(
    'maintenanceChunkEmbeddings', $top_k, $embedding
) YIELD node, score
MATCH (node)-[:FROM_DOCUMENT]->(doc:Document)
RETURN score,
       doc.documentId AS document,
       doc.aircraftType AS aircraft_type,
       node.index AS chunk_idx,
       substring(node.text, 0, 120) AS preview
ORDER BY score DESC
LIMIT $top_k"""

    print("  Generated Cypher:")
    for ln in query.strip().splitlines():
        print(f"    {ln}")
    print()

    try:
        records, _, _ = driver.execute_query(
            query,
            embedding=embedding,
            top_k=top_k,
            database_=database,
        )
        rows = [dict(r) for r in records]
        if rows:
            for r in rows:
                r["score"] = f"{r['score']:.4f}"
        records_table(rows)
    except Neo4jError as exc:
        report_query_error(driver, database, exc, "maintenanceChunkEmbeddings")


def _text2cypher_prompt(driver: Driver, database: str) -> str | None:
    """Return the text2cypher system prompt, or None if the schema read fails."""
    try:
        return system_prompt(graph_schema(driver, database))
    except Neo4jError as exc:
        print(f"  [ERROR] Schema read failed: {exc.code}: {exc.message}")
        print("  (the text2cypher questions are skipped)\n")
        return None
    except DriverError as exc:
        # A dropped connection, such as ServiceUnavailable, has no code.
        print(f"  [ERROR] Schema read failed: {exc}")
        print("  (the text2cypher questions are skipped)\n")
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_agent_samples(
    driver: Driver,
    database: str,
    *,
    provider: str,
    openai_key: str | None = None,
    anthropic_key: str | None = None,
    region: str | None = None,
    llm_model: str,
    embedding_model: str,
    embedding_dimensions: int,
    sample_size: int = 0,
) -> None:
    """Run all agent sample questions with LLM-generated Cypher."""
    chat_fn, embed_fn = _create_llm_client(
        provider,
        openai_key=openai_key,
        anthropic_key=anthropic_key,
        region=region,
        llm_model=llm_model,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
    )

    questions = SAMPLE_QUESTIONS
    if sample_size > 0:
        questions = questions[:sample_size]

    print(f"\n{'#' * WIDTH}")
    print("  Aircraft Digital Twin \u2014 Agent Simulation")
    print(f"{'#' * WIDTH}")
    print(f"\n  LLM: {provider}/{llm_model}")
    print(f"  Questions: {len(questions)}\n")

    # The schema is read only for text2cypher questions. If the read fails,
    # those questions are skipped and the rest still run.
    prompt = None
    if any(sq.tool == "text2cypher" for sq in questions):
        prompt = _text2cypher_prompt(driver, database)

    current_category = ""
    for i, sq in enumerate(questions, 1):
        if sq.category != current_category:
            current_category = sq.category
            header(f"{i}. [{sq.tool}] {sq.category}", f"Tool: {sq.tool}")

        if sq.tool == "text2cypher":
            if prompt is None:
                print(f'  Question: "{sq.question}"\n')
                print("  [SKIP] No graph schema; see the error above.\n")
            else:
                _run_text2cypher(driver, database, chat_fn, prompt, sq.question)
        elif sq.tool == "similarity_search":
            _run_similarity_search(driver, database, chat_fn, embed_fn, sq.question)

    print(f"{'#' * WIDTH}")
    print("  Agent simulation complete.")
    print(f"{'#' * WIDTH}\n")
