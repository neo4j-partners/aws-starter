"""Simulate the Neo4j Aura Agent by sending natural language questions to the
configured LLM, generating Cypher or vector searches, and executing them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from neo4j import READ_ACCESS, Driver, NotificationDisabledClassification, RoutingControl
from neo4j.exceptions import Neo4jError

from generator.specs import (
    AIRPORTS,
    COMPONENT_TYPES_BY_SYSTEM,
    DELAY_CAUSES,
    EVENT_SEVERITIES,
    MANUAL_FLEET_TAILS,
    MODEL_DISTRIBUTION,
    OPERATORS,
    SENSOR_TYPES,
)

from .display import WIDTH, header, records_table, show_cypher
from .samples import report_query_error

# ---------------------------------------------------------------------------
# Graph schema description fed to the LLM for Cypher generation
# ---------------------------------------------------------------------------

# Facts about the generated data, from the generator specs so they match it.
# The first manual tail of each model is in every fleet of five or more
# aircraft, because the registry tails come first in round-robin order.
_SAMPLE_TAILS = ", ".join(f"{tails[0]} ({model})" for model, tails in MANUAL_FLEET_TAILS.items())
_GRAPH_FACTS = f"""\
Aircraft models: {", ".join(model for model, _ in MODEL_DISTRIBUTION)}.
Sample tail numbers: {_SAMPLE_TAILS}.
Operators: {", ".join(op.name for op in OPERATORS)}.
Airport IATA codes: {", ".join(airport.iata for airport in AIRPORTS)}.
"""

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

_RELATIONSHIPS_Q = """\
MATCH (a)-[r]->(b)
RETURN DISTINCT labels(a) AS from_labels, type(r) AS type, labels(b) AS to_labels"""


def _domain_label(labels: list[str]) -> str | None:
    """Join a node's labels, leaving out internal ones such as __KGBuilder__."""
    domain = sorted(label for label in labels if not label.startswith("__"))
    return ":".join(domain) or None


def graph_schema(driver: Driver, database: str) -> str:
    """Describe the graph's labels, properties, and relationships for the LLM.

    Labels and properties come from db.schema.nodeTypeProperties and the
    relationship patterns from the data, so the description matches the
    database. Value hints come from the generator specs.
    """
    # db.schema.nodeTypeProperties warns that its propertyTypes field will
    # change. The query does not use that field, so the warning is noise.
    with driver.session(
        database=database,
        default_access_mode=READ_ACCESS,
        notifications_disabled_classifications=[NotificationDisabledClassification.GENERIC],
    ) as session:
        property_rows = session.run(_NODE_PROPERTIES_Q).data()
        relationship_rows = session.run(_RELATIONSHIPS_Q).data()

    properties: dict[str, set[str]] = {}
    for row in property_rows:
        if label := _domain_label(row["nodeLabels"]):
            properties.setdefault(label, set()).add(row["propertyName"])

    relationships = set()
    for row in relationship_rows:
        from_label = _domain_label(row["from_labels"])
        to_label = _domain_label(row["to_labels"])
        if from_label and to_label:
            relationships.add((from_label, row["type"], to_label))

    lines = ["Node labels and properties:"]
    for label in sorted(properties):
        line = f"- {label} {{{', '.join(sorted(properties[label]))}}}"
        if note := _LABEL_NOTES.get(label):
            line += f"  ({note})"
        lines.append(line)
    lines += ["", "Relationships:"]
    lines += [f"- ({a})-[:{rel}]->({b})" for a, rel, b in sorted(relationships)]
    return "\n".join(lines) + "\n\n" + _GRAPH_FACTS


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
        "Tell me about aircraft N95040A",
        "Aircraft Overview",
        "text2cypher",
    ),
    SampleQuestion(
        "What are the sensor operating limits for N30268B?",
        "Sensor Operating Limits",
        "text2cypher",
    ),
    SampleQuestion(
        "Show the maintenance summary for N54980C",
        "Maintenance Summary",
        "text2cypher",
    ),
    SampleQuestion(
        "What faults do aircraft N95040A and N26760M share?",
        "Shared Faults",
        "text2cypher",
    ),
    SampleQuestion(
        "What maintenance manual applies to N30268B?",
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
    # any write it contains.
    try:
        records, _, _ = driver.execute_query(
            cypher, database_=database, routing_=RoutingControl.READ
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

    prompt = system_prompt(graph_schema(driver, database))

    questions = SAMPLE_QUESTIONS
    if sample_size > 0:
        questions = questions[:sample_size]

    print(f"\n{'#' * WIDTH}")
    print("  Aircraft Digital Twin \u2014 Agent Simulation")
    print(f"{'#' * WIDTH}")
    print(f"\n  LLM: {provider}/{llm_model}")
    print(f"  Questions: {len(questions)}\n")

    current_category = ""
    for i, sq in enumerate(questions, 1):
        if sq.category != current_category:
            current_category = sq.category
            header(f"{i}. [{sq.tool}] {sq.category}", f"Tool: {sq.tool}")

        if sq.tool == "text2cypher":
            _run_text2cypher(driver, database, chat_fn, prompt, sq.question)
        elif sq.tool == "similarity_search":
            _run_similarity_search(driver, database, chat_fn, embed_fn, sq.question)

    print(f"{'#' * WIDTH}")
    print("  Agent simulation complete.")
    print(f"{'#' * WIDTH}\n")
