"""SimpleKGPipeline-based document enrichment: chunking, embedding, and entity extraction."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neo4j import Driver
from neo4j_graphrag.components.text_splitters.base import TextSplitter
from neo4j_graphrag.components.types import TextChunks
from neo4j_graphrag.embeddings.openai import OpenAIEmbeddings

from .loader import detach_delete_nodes
from .schema import (
    COMPONENT_ALIASES_TEXT,
    COMPONENT_TYPE_BY_ALIAS,
    COMPONENT_TYPES_TEXT,
    OPERATING_LIMIT_REGIMES_TEXT,
    SENSOR_PARAMETER_NAMES,
    SYSTEM_TYPE_BY_COMPONENT_TYPE,
    SYSTEM_TYPES,
    SYSTEM_TYPES_TEXT,
)

logger = logging.getLogger(__name__)

# Labels for extracted entity nodes (used by clear/verify logic).
EXTRACTED_LABELS = [
    "AircraftModel",
    "SystemReference",
    "ComponentReference",
    "Fault",
    "MaintenanceProcedure",
    "OperatingLimit",
]

# ---------------------------------------------------------------------------
# Document metadata registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentMeta:
    filename: str
    document_id: str
    aircraft_type: str
    title: str


DOCUMENTS: list[DocumentMeta] = [
    DocumentMeta(
        filename="MAINTENANCE_A320.md",
        document_id="AMM-A320-2024-001",
        aircraft_type="A320-200",
        title="A320-200 Maintenance and Troubleshooting Manual",
    ),
    DocumentMeta(
        filename="MAINTENANCE_A321neo.md",
        document_id="AMM-A321neo-2024-001",
        aircraft_type="A321neo",
        title="A321neo Maintenance and Troubleshooting Manual",
    ),
    DocumentMeta(
        filename="MAINTENANCE_B737.md",
        document_id="AMM-B737-2024-001",
        aircraft_type="B737-800",
        title="B737-800 Maintenance and Troubleshooting Manual",
    ),
    DocumentMeta(
        filename="MAINTENANCE_E190.md",
        document_id="AMM-E190-2024-001",
        aircraft_type="E190",
        title="E190 Maintenance and Troubleshooting Manual",
    ),
    DocumentMeta(
        filename="MAINTENANCE_A220.md",
        document_id="AMM-A220-2024-001",
        aircraft_type="A220-300",
        title="A220-300 Maintenance and Troubleshooting Manual",
    ),
]


# A comment that fills its lines, such as a generated-block marker, goes with
# its line break. Any other comment goes alone. A comment ends at its first
# "-->", so the body may not contain one; otherwise a comment followed by text
# could run on to a later comment that ends a line and take the text between.
_LINE_COMMENT = re.compile(r"^[ \t]*<!--(?:(?!-->).)*-->[ \t]*(?:\n|\Z)", re.MULTILINE | re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_comments(text: str) -> str:
    """Drop HTML comments, so block markers never reach chunks or the LLM."""
    return _COMMENT.sub("", _LINE_COMMENT.sub("", text))


def read_manual_text(path: Path) -> str:
    """A manual's text as the pipeline chunks it."""
    return strip_comments(path.read_text(encoding="utf-8")).strip()


# ---------------------------------------------------------------------------
# Context-aware text splitter
# ---------------------------------------------------------------------------

# A markdown table's separator line, such as "|-------|:---:|".
_TABLE_SEPARATOR = re.compile(r"\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*")


@dataclass(frozen=True)
class TableSpan:
    """Offsets of one markdown table in a text."""

    start: int  # start of the header row
    body_start: int  # start of the first row after the separator line
    end: int  # end of the last row, after its newline


def markdown_tables(text: str) -> list[TableSpan]:
    """Each markdown table in ``text``: a header row, a separator, then rows."""
    lines = text.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    tables = []
    i = 0
    while i < len(lines) - 1:
        if lines[i].lstrip().startswith("|") and _TABLE_SEPARATOR.fullmatch(lines[i + 1]):
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            tables.append(
                TableSpan(
                    start=offsets[i],
                    body_start=min(offsets[i + 2], len(text)),
                    end=min(offsets[j], len(text)),
                )
            )
            i = j
        else:
            i += 1
    return tables


def with_table_header(text: str, start: int, end: int, tables: list[TableSpan]) -> str:
    """``text[start:end]``, led by its table's header when it starts inside a table.

    A chunk that starts in a table's header or separator line is extended
    back to the header row. A chunk that starts in a body row gets the
    header row and separator, then that whole row, so its first row is
    complete and its cells line up with the header.
    """
    chunk = text[start:end]
    first = start + len(chunk) - len(chunk.lstrip())
    line_start = text.rfind("\n", 0, first) + 1
    for table in tables:
        if table.start <= line_start < table.end and first > table.start:
            if line_start < table.body_start:
                return text[table.start : end]
            return text[table.start : table.body_start] + text[line_start:end]
    return chunk


_HEADING = re.compile(r"(#{1,6})[ \t]+(.+?)[ \t]*")
_FENCE = "```"


@dataclass(frozen=True)
class Heading:
    """One markdown heading in a text."""

    start: int  # start of the heading line
    level: int  # 1 for "#", 2 for "##", and so on
    text: str


def markdown_headings(text: str) -> list[Heading]:
    """Each markdown heading in ``text``, skipping lines in fenced code blocks."""
    headings = []
    offset = 0
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith(_FENCE):
            in_fence = not in_fence
        elif not in_fence and (match := _HEADING.fullmatch(line)):
            headings.append(Heading(offset, len(match.group(1)), match.group(2)))
        offset += len(line) + 1
    return headings


def section_path(headings: list[Heading], offset: int) -> list[str]:
    """Heading texts in effect at ``offset``, from the "##" level down.

    The "#" heading is the manual's title, which the context line already
    names. A heading whose line starts after ``offset`` is not in effect
    yet. A heading that starts exactly at ``offset`` closes its earlier
    siblings but is left out, so a chunk that starts with a heading shows
    only that heading's parents.
    """
    path: list[Heading] = []
    for heading in headings:
        if heading.start > offset:
            break
        while path and path[-1].level >= heading.level:
            path.pop()
        if heading.start == offset:
            break
        path.append(heading)
    return [heading.text for heading in path if heading.level >= 2]


class ContextPrependingSplitter(TextSplitter):
    """Wraps a ``TextSplitter`` and prepends a context line to every chunk.

    **Why this is necessary:**  ``SimpleKGPipeline`` passes ``document_metadata``
    (which includes the aircraft type) only to the lexical graph builder for
    storage on ``Document`` nodes. It is never injected into the LLM extraction
    prompt.  The LLM sees only the raw chunk text.  After the inner splitter
    divides a 30 000-character maintenance manual into ~40 chunks of ~800
    characters, most chunks land deep in engine-specific sections where the
    engine designation (e.g. "LEAP-1A") dominates and the aircraft model
    (e.g. "A321neo") is never mentioned.  Without explicit context, the LLM
    confuses engine types for aircraft types, breaking downstream cross-links
    that match on ``OperatingLimit.aircraftType == Aircraft.model``.

    This wrapper solves the problem by delegating splitting to the inner
    splitter, then prepending a short context header to *every* resulting
    chunk so the LLM always has access to the document-level aircraft type.

    A chunk that starts inside a markdown table also gets the table's header
    row and separator after the context line. Without them, a chunk cut below
    a table's header holds values with no column names, such as an EGT row
    with no operating regimes. The inner splitter must return substrings of
    the text, as ``FixedSizeSplitter`` does, so each chunk's offset can be
    found.

    The context line also names the manual section each chunk starts in, as
    ``" | Section: 3. Engine > 3.2 Components > 3.2.3 High-Pressure Turbine"``.
    A chunk cut below its section heading otherwise loses which component or
    fault its text, tables and limits belong to. The context is added after
    the inner splitter runs, so it doesn't change chunk sizes or boundaries.

    It also sets ``chunkId`` to ``"{document_id}:{index}"`` in each chunk's
    metadata. The lexical graph builder copies chunk metadata onto the
    ``Chunk`` node, so every chunk gets a stable id for its uniqueness
    constraint.

    Set :attr:`context` and :attr:`document_id` before each call to
    ``pipeline.run_async()``. :attr:`context` is the context line without
    its section or line break. An empty context adds no line.
    """

    def __init__(self, inner: TextSplitter, context: str = "", document_id: str = "") -> None:
        self.inner = inner
        self.context = context
        self.document_id = document_id

    def _context_line(self, section: list[str]) -> str:
        if not section:
            return f"{self.context}\n\n"
        return f"{self.context} | Section: {' > '.join(section)}\n\n"

    async def run(self, text: str) -> TextChunks:
        if not self.document_id:
            raise ValueError("Set document_id before splitting so every Chunk gets a chunkId.")
        result = await self.inner.run(text)
        tables = markdown_tables(text)
        headings = markdown_headings(text)
        search_from = 0
        for chunk in result.chunks:
            start = text.find(chunk.text, search_from)
            if start < 0:
                raise ValueError(
                    f"chunk {chunk.index} is not a substring of the text, "
                    "so its table header can't be found"
                )
            search_from = start + 1
            # Skip leading blank lines, so a chunk that opens on blank
            # lines and then a heading counts as starting at that heading.
            body_start = start + len(chunk.text) - len(chunk.text.lstrip())
            chunk.text = with_table_header(text, start, start + len(chunk.text), tables)
            if self.context:
                section = section_path(headings, body_start)
                chunk.text = self._context_line(section) + chunk.text
            chunk.metadata = {
                **(chunk.metadata or {}),
                "chunkId": f"{self.document_id}:{chunk.index}",
            }
        return result


# ---------------------------------------------------------------------------
# Dimension-aware embedder wrapper
# ---------------------------------------------------------------------------


class DimensionAwareOpenAIEmbeddings(OpenAIEmbeddings):
    """OpenAIEmbeddings that always passes ``dimensions`` to the API.

    The pipeline's ``TextChunkEmbedder`` calls ``embed_query(text)`` without
    a ``dimensions`` kwarg, so we override to inject it automatically.
    """

    def __init__(self, dimensions: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._dimensions = dimensions

    def embed_query(self, text: str, **kwargs: Any) -> list[float]:
        return super().embed_query(text, dimensions=self._dimensions, **kwargs)


# ---------------------------------------------------------------------------
# Extraction prompt template
# ---------------------------------------------------------------------------

# Custom prompt that teaches the LLM domain reasoning for aircraft maintenance
# manuals and keeps extracted manual entities model-scoped.
#
# Placeholders: {schema}, {examples}, {text} (required by ERExtractionTemplate).
# Literal braces must be doubled for Python str.format(). The f-string parts
# add the fleet type lists from schema.py and contain no braces of their own.

EXTRACTION_PROMPT = (
    """\
You are an expert aviation engineer extracting structured maintenance-manual \
knowledge to build an aircraft digital twin graph.

Your task: extract entities (nodes) and relationships from the input text \
according to the schema below.

Return result as JSON using this format:
{{"nodes": [
  {{"id": "0", "label": "AircraftModel", "properties": {{"name": "A320-200"}}}},
  {{"id": "1", "label": "ComponentReference", "properties": {{"name": "High-Pressure Turbine - A320-200", "componentType": "HP Turbine", "aircraftType": "A320-200"}}}},
  {{"id": "2", "label": "OperatingLimit", "properties": {{"name": "EGT Takeoff - A320-200", "parameterName": "EGT", "regime": "Takeoff", "aircraftType": "A320-200", "unit": "°C", "maxValue": "695"}}}}
],
"relationships": [
  {{"start_node_id": "1", "end_node_id": "2", "type": "HAS_LIMIT", "properties": {{}}}}
]}}

Use only the following node and relationship types:
{schema}

IMPORTANT RULES:

1. DOCUMENT CONTEXT: The input text starts with a [DOCUMENT CONTEXT] line \
that identifies the aircraft type and title. Use the aircraft type from this \
context line as the `aircraftType` property on every extracted entity except \
AircraftModel, where it is the `name`.

2. AIRCRAFT TYPE vs ENGINE MODEL: The `aircraftType` property must be the \
airframe model (the aircraft you fly, e.g. A320-200, A321neo, B737-800), \
NOT the engine designation (e.g. V2500, LEAP-1A, CFM56-7B, PW1100G). \
Maintenance manuals are organized by aircraft type. Engine models appear \
throughout the text but they are components OF the aircraft, not the \
aircraft type itself.

3. EXTRACT USEFUL MANUAL KNOWLEDGE: Extract aircraft models, systems, \
components, faults, procedures, and operating limits when they are explicitly \
mentioned in the text. Do not invent part numbers, fault codes, intervals, or \
limits that are not present.

"""
    + f"""\
4. PARAMETER NAMES: For OperatingLimit, `parameterName` must be one of the \
fleet sensor types {SENSOR_PARAMETER_NAMES} when the limit is for that \
measurement. Use Vibration for every engine vibration limit, including N1 and \
N2 vibration, and name the shaft in `name` instead. For any other parameter, \
use a concise sensor-style name.

"""
    + """\
5. ENTITY NAME FORMAT: For SystemReference, ComponentReference, Fault, \
MaintenanceProcedure, and OperatingLimit, the `name` property must follow \
"<specific name> - <aircraftType>" (e.g. "High-Pressure Turbine - A320-200"). \
AircraftModel uses the aircraft type only (e.g. "A320-200"). This prevents \
cross-model entity resolution mistakes. An OperatingLimit's specific name is \
its parameter and then its `regime` (e.g. "EGT Takeoff - A320-200" and \
"EGT Takeoff Normal - A320-200"), so each regime's limit stays a separate \
entity. Set `regime` on every OperatingLimit, as rule 8 says.

6. RELATIONSHIPS: Create relationships only when the text supports them. \
Prefer the schema patterns: AircraftModel HAS_SYSTEM SystemReference, \
SystemReference HAS_COMPONENT ComponentReference, ComponentReference HAS_FAULT \
Fault, Fault CORRECTED_BY MaintenanceProcedure, and component/system HAS_LIMIT \
OperatingLimit.

"""
    + f"""\
7. FLEET TYPES: Set SystemReference `systemType` to exactly one of \
{SYSTEM_TYPES_TEXT}, and omit it for any other system. Set ComponentReference \
`componentType` to exactly one of the types listed for the part's system: \
{COMPONENT_TYPES_TEXT}. Use these types for the manuals' own part names: \
{COMPONENT_ALIASES_TEXT}. Use the type the part is or belongs to, for example \
HP Turbine for a high-pressure turbine stage and Main Fuel Pump for an engine \
fuel pump. Omit `componentType` when no listed type fits, such as a fuel \
filter or a fuel nozzle. Never invent other values.

"""
    + f"""\
8. OPERATING LIMITS: Emit an OperatingLimit only when the text gives a \
numeric minValue or maxValue. Set `regime` to exactly one of \
{OPERATING_LIMIT_REGIMES_TEXT}, and use the same words in the name. Use All \
when the text names no regime.
- Hard limits: Takeoff, Max Continuous, and Start come only from the \
Operating Limits table, the one with Normal, Caution, and Maximum columns. \
Set maxValue from its Maximum column, e.g. "EGT Takeoff - A320-200" with \
maxValue 695. Ignore that table's Normal and Caution columns.
- Normal ranges: The Normal Operating Parameters table and its Quick \
Reference - Normal Operating Limits copy hold normal ranges, not hard limits. \
Use the column's regime followed by Normal, e.g. "EGT Takeoff Normal - \
A320-200" with regime Takeoff Normal and maxValue 650. Never give these a \
hard-limit regime.
- Bands: For an Advisory, Caution, or Warning row, set the band's bounds, \
e.g. "Vibration N1 Warning - A220-300" with minValue 3.5. Skip Normal band \
rows and Nominal values.
- Trend: The Digital Twin trend-averaged EGT thresholds use Trend Advisory, \
Trend Caution, and Trend Warning, with minValue where the level starts. Skip \
the trend baseline.
- Values: "a-b" sets minValue a and maxValue b. "< x" or "≤ x" sets maxValue \
x. "> x" or "≥ x" sets minValue x. For "v (a-b)" or "v (< x)", use the range \
in parentheses. A lone number in the Normal Operating Parameters table sets \
maxValue.

"""
    + """\
Assign a unique ID (string) to each node and reuse it for relationships.

Output rules:
- Return ONLY the JSON object, no additional text.
- Omit any backticks. Output raw JSON.
- The JSON must be a single object, not wrapped in a list.
- Property names must be in double quotes.
- Property values must be strings, numbers, booleans, or arrays of those values.
- Omit unknown or unavailable properties; do not use null or nested objects.

{examples}

Input text:

{text}
"""
)


# ---------------------------------------------------------------------------
# Pipeline factory
# ---------------------------------------------------------------------------


# Sonnet 5.5 thinks adaptively by default at "high" effort. Extraction is a
# well-specified, per-chunk task, so "low" effort keeps pipeline cost down.
_BEDROCK_EXTRACTION_THINKING = {
    "thinking": {"type": "adaptive"},
    "output_config": {"effort": "low"},
}


def _create_extraction_llm(
    *,
    provider: str,
    openai_api_key: str | None,
    anthropic_api_key: str | None,
    region: str | None = None,
    llm_model: str,
    llm_max_tokens: int,
):
    """Create the LLM used for maintenance-manual entity extraction."""
    if provider == "bedrock":
        # StructuredBedrockLLM (a thin local subclass) routes the extractor's
        # response_format request through Bedrock Converse tool use, so entity
        # extraction gets schema-shaped JSON instead of prompt-and-repair.
        from .bedrock_structured import StructuredBedrockLLM

        return StructuredBedrockLLM(
            model_name=llm_model,
            model_params={"maxTokens": llm_max_tokens},
            region_name=region,
            additional_request_fields=_BEDROCK_EXTRACTION_THINKING,
        )
    if provider == "openai":
        from neo4j_graphrag.llm.openai_llm import OpenAILLM

        return OpenAILLM(
            model_name=llm_model,
            model_params={
                "max_completion_tokens": llm_max_tokens,
                "response_format": {"type": "json_object"},
            },
            api_key=openai_api_key,
        )
    if provider == "anthropic":
        # Untested against the live Anthropic API; see anthropic_effort.py.
        from .anthropic_effort import EffortAnthropicLLM

        return EffortAnthropicLLM(
            model_name=llm_model,
            model_params={
                "max_tokens": llm_max_tokens,
                "thinking": _BEDROCK_EXTRACTION_THINKING["thinking"],
            },
            effort=_BEDROCK_EXTRACTION_THINKING["output_config"]["effort"],
            api_key=anthropic_api_key,
        )
    raise ValueError(f"Unknown LLM provider: {provider!r}")


def _create_pipeline(
    driver: Driver,
    database: str,
    *,
    provider: str,
    openai_api_key: str | None,
    anthropic_api_key: str | None,
    region: str | None = None,
    llm_model: str,
    llm_max_tokens: int,
    embedding_model: str,
    embedding_dimensions: int,
    chunk_size: int,
    chunk_overlap: int,
):
    """Build a ``SimpleKGPipeline`` configured for maintenance-manual enrichment."""
    from neo4j_graphrag.components.text_splitters.fixed_size_splitter import (
        FixedSizeSplitter,
    )
    from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline

    from .schema import build_extraction_schema

    # --- LLM ---
    llm = _create_extraction_llm(
        provider=provider,
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        region=region,
        llm_model=llm_model,
        llm_max_tokens=llm_max_tokens,
    )

    # --- Embedder ---
    if provider == "bedrock":
        from neo4j_graphrag.embeddings.bedrock import BedrockEmbeddings

        embedder = BedrockEmbeddings(
            model_id=embedding_model,
            dimensions=embedding_dimensions,
            region_name=region,
        )
    else:
        embedder = DimensionAwareOpenAIEmbeddings(
            dimensions=embedding_dimensions,
            model=embedding_model,
            api_key=openai_api_key,
        )

    # --- Text splitter (with per-chunk context injection) ---
    inner_splitter = FixedSizeSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        approximate=True,
    )
    splitter = ContextPrependingSplitter(inner_splitter)

    # --- Schema ---
    schema = build_extraction_schema()

    pipeline = SimpleKGPipeline(
        llm=llm,
        driver=driver,
        embedder=embedder,
        schema=schema,
        text_splitter=splitter,
        from_file=False,
        on_error="IGNORE",
        perform_entity_resolution=True,
        prompt_template=EXTRACTION_PROMPT,
        neo4j_database=database,
    )
    return pipeline, splitter


def debug_extract_chunks(
    document_dir: Path,
    *,
    filename: str,
    chunk_indexes: list[int],
    provider: str,
    openai_api_key: str | None,
    anthropic_api_key: str | None,
    region: str | None = None,
    llm_model: str,
    llm_max_tokens: int,
    chunk_size: int,
    chunk_overlap: int,
) -> bool:
    """Run extractor validation for selected chunks without writing to Neo4j."""
    from neo4j_graphrag.components.entity_relation_extractor import (
        LLMEntityRelationExtractor,
        OnError,
    )
    from neo4j_graphrag.components.text_splitters.fixed_size_splitter import (
        FixedSizeSplitter,
    )

    from .schema import build_extraction_schema

    meta = next((doc for doc in DOCUMENTS if doc.filename == filename), None)
    if meta is None:
        names = ", ".join(doc.filename for doc in DOCUMENTS)
        raise ValueError(f"Unknown document {filename!r}. Expected one of: {names}")

    llm = _create_extraction_llm(
        provider=provider,
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        region=region,
        llm_model=llm_model,
        llm_max_tokens=llm_max_tokens,
    )
    extractor = LLMEntityRelationExtractor(
        llm=llm,
        prompt_template=EXTRACTION_PROMPT,
        create_lexical_graph=False,
        on_error=OnError.RAISE,
        use_structured_output=llm.supports_structured_output,
    )
    splitter = ContextPrependingSplitter(
        FixedSizeSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            approximate=True,
        ),
        context=(f"[DOCUMENT CONTEXT] Aircraft Type: {meta.aircraft_type} | Title: {meta.title}"),
        document_id=meta.document_id,
    )
    schema = build_extraction_schema()

    async def _run() -> bool:
        text = read_manual_text(document_dir / filename)
        chunks = await splitter.run(text)
        logger.info("Document: %s", filename)
        logger.info("Total chunks: %d", len(chunks.chunks))
        logger.info("LLM: %s/%s max_tokens=%d", provider, llm_model, llm_max_tokens)

        ok = True
        for index in chunk_indexes:
            if index < 0 or index >= len(chunks.chunks):
                logger.error("  [FAIL] chunk_index=%d is out of range", index)
                ok = False
                continue
            chunk = chunks.chunks[index]
            try:
                graph = await extractor.extract_for_chunk(schema, "", chunk)
            except Exception as exc:
                logger.error("  [FAIL] chunk_index=%d: %s", index, exc)
                ok = False
                continue
            logger.info(
                "  [OK] chunk_index=%d: %d nodes, %d relationships",
                index,
                len(graph.nodes),
                len(graph.relationships),
            )
        return ok

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# Document processing
# ---------------------------------------------------------------------------


def process_all_documents(
    driver: Driver,
    database: str,
    document_dir: Path,
    *,
    provider: str,
    openai_api_key: str | None,
    anthropic_api_key: str | None,
    region: str | None = None,
    llm_model: str,
    llm_max_tokens: int,
    embedding_model: str,
    embedding_dimensions: int,
    chunk_size: int,
    chunk_overlap: int,
    enrich_sample_size: int = 0,
) -> None:
    """Run the SimpleKGPipeline over every maintenance manual.

    When *enrich_sample_size* > 0 the input text for each document is truncated
    so that approximately that many chunks are produced.  Useful for quick test
    runs without processing the full manuals.
    """
    pipeline, splitter = _create_pipeline(
        driver,
        database,
        provider=provider,
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        region=region,
        llm_model=llm_model,
        llm_max_tokens=llm_max_tokens,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    # Pre-compute max text length when sample size is set.
    # Each chunk beyond the first advances by (chunk_size - chunk_overlap) chars.
    if enrich_sample_size > 0:
        max_chars = chunk_size + (enrich_sample_size - 1) * (chunk_size - chunk_overlap)
    else:
        max_chars = 0  # 0 = unlimited

    async def _run_all():
        for meta in DOCUMENTS:
            logger.info("Processing: %s", meta.filename, extra={"blank_before": True})
            filepath = document_dir / meta.filename
            text = read_manual_text(filepath)
            logger.info("  Read %s characters.", f"{len(text):,}")

            if max_chars and len(text) > max_chars:
                text = text[:max_chars]
                logger.info(
                    "  Truncated to %s chars (~%d chunks).", f"{max_chars:,}", enrich_sample_size
                )

            # Update the splitter's context so every chunk the LLM sees starts
            # with the aircraft type.  The custom EXTRACTION_PROMPT instructs
            # the LLM to read this header.
            splitter.context = (
                f"[DOCUMENT CONTEXT] Aircraft Type: {meta.aircraft_type} | Title: {meta.title}"
            )
            splitter.document_id = meta.document_id

            await pipeline.run_async(
                text=text,
                document_metadata={
                    "documentId": meta.document_id,
                    "aircraftType": meta.aircraft_type,
                    "title": meta.title,
                    "type": "maintenance_manual",
                    "path": meta.filename,
                },
            )
            logger.info("  [OK] Pipeline complete for %s", meta.document_id)

    asyncio.run(_run_all())


# ---------------------------------------------------------------------------
# Cross-links to existing operational graph
# ---------------------------------------------------------------------------


def link_to_existing_graph(driver: Driver, database: str) -> None:
    """Create relationships between enrichment data and the operational graph."""

    # Document -[:APPLIES_TO]-> Aircraft (via document metadata aircraftType)
    records, _, _ = driver.execute_query(
        """
        MATCH (d:Document) WHERE d.aircraftType IS NOT NULL
        MATCH (a:Aircraft {model: d.aircraftType})
        MERGE (d)-[:APPLIES_TO]->(a)
        RETURN count(*) AS count
    """,
        database_=database,
    )
    logger.info("  [OK] %d Document -[:APPLIES_TO]-> Aircraft", records[0]["count"])

    # AircraftModel -[:DESCRIBES_MODEL]-> Aircraft
    # (model-level manual entity to tail-level fleet)
    records, _, _ = driver.execute_query(
        """
        MATCH (am:AircraftModel)
        MATCH (a:Aircraft {model: am.name})
        MERGE (am)-[:DESCRIBES_MODEL]->(a)
        RETURN count(*) AS count
    """,
        database_=database,
    )
    logger.info("  [OK] %d AircraftModel -[:DESCRIBES_MODEL]-> Aircraft", records[0]["count"])

    # SystemReference -[:DESCRIBES_SYSTEM]-> System
    # (same aircraft model, systemType equals the System type, ignoring case
    # and outer spaces; the extraction prompt limits systemType to the fleet
    # system types)
    records, _, _ = driver.execute_query(
        """
        MATCH (sr:SystemReference)
        WHERE sr.aircraftType IS NOT NULL AND sr.systemType IS NOT NULL
        MATCH (:Aircraft {model: sr.aircraftType})-[:HAS_SYSTEM]->(s:System)
        WHERE toLower(s.type) = toLower(trim(sr.systemType))
        MERGE (sr)-[:DESCRIBES_SYSTEM]->(s)
        RETURN count(*) AS count
    """,
        database_=database,
    )
    logger.info("  [OK] %d SystemReference -[:DESCRIBES_SYSTEM]-> System", records[0]["count"])

    # ComponentReference -[:DESCRIBES_COMPONENT]-> Component
    # (same aircraft model; componentType, ignoring case and outer spaces, is
    # a component type or one of its aliases, and the Component has that type, within the
    # System type that has that component type in specs. Parent
    # SystemReferences with a fleet systemType, ignoring case and outer
    # spaces, must include that System type, or the link is blocked.
    # Parents with another systemType, or none, are ignored.)
    records, _, _ = driver.execute_query(
        """
        MATCH (cr:ComponentReference)
        WHERE cr.aircraftType IS NOT NULL AND cr.componentType IS NOT NULL
        WITH cr, $component_type_by_alias[toLower(trim(cr.componentType))] AS ctype
        WHERE ctype IS NOT NULL
        WITH cr, ctype, $system_types[toLower(ctype)] AS systemType
        OPTIONAL MATCH (sr:SystemReference)-[:HAS_COMPONENT]->(cr)
        WITH cr, ctype, systemType,
             [t IN collect(toLower(trim(sr.systemType))) WHERE t IN $fleet_system_types] AS parentTypes
        WHERE parentTypes = [] OR toLower(systemType) IN parentTypes
        MATCH (:Aircraft {model: cr.aircraftType})
            -[:HAS_SYSTEM]->(:System {type: systemType})
            -[:HAS_COMPONENT]->(c:Component {type: ctype})
        MERGE (cr)-[:DESCRIBES_COMPONENT]->(c)
        RETURN count(*) AS count
    """,
        component_type_by_alias=COMPONENT_TYPE_BY_ALIAS,
        system_types=SYSTEM_TYPE_BY_COMPONENT_TYPE,
        fleet_system_types=[t.lower() for t in SYSTEM_TYPES],
        database_=database,
    )
    logger.info(
        "  [OK] %d ComponentReference -[:DESCRIBES_COMPONENT]-> Component", records[0]["count"]
    )

    # Drop each OperatingLimit with no minValue and no maxValue, so no
    # Sensor links to a limit without a value.
    records, _, _ = driver.execute_query(
        """
        MATCH (ol:OperatingLimit)
        WHERE ol.minValue IS NULL AND ol.maxValue IS NULL
        DETACH DELETE ol
        RETURN count(*) AS count
    """,
        database_=database,
    )
    logger.info("  [OK] %d OperatingLimit with no value dropped", records[0]["count"])

    # Sensor -[:HAS_LIMIT]-> OperatingLimit
    # (same aircraft model, parameterName equals the Sensor type, ignoring case)
    records, _, _ = driver.execute_query(
        """
        MATCH (a:Aircraft)-[:HAS_SYSTEM]->(:System)-[:HAS_SENSOR]->(s:Sensor)
        MATCH (ol:OperatingLimit {aircraftType: a.model})
        WHERE toLower(ol.parameterName) = toLower(s.type)
        MERGE (s)-[:HAS_LIMIT]->(ol)
        RETURN count(*) AS count
    """,
        database_=database,
    )
    logger.info("  [OK] %d Sensor -[:HAS_LIMIT]-> OperatingLimit", records[0]["count"])


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def clear_enrichment_data(driver: Driver, database: str) -> None:
    """Delete all Document, Chunk, and extracted entity nodes (preserves operational graph)."""
    # __Entity__ and __KGBuilder__ are labels the KG pipeline adds to its nodes.
    labels_to_clear = ["Document", "Chunk", *EXTRACTED_LABELS, "__Entity__", "__KGBuilder__"]

    logger.info("Clearing enrichment data (Documents, Chunks, extracted entities)...")
    deleted_total = sum(detach_delete_nodes(driver, database, label) for label in labels_to_clear)

    logger.info("  [OK] Cleared %d enrichment nodes.", deleted_total)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_SAMPLE_SIZE = 5


def _get_existing_schema_tokens(driver: Driver, database: str) -> tuple[set[str], set[str]]:
    """Return labels and relationship types currently present in the graph."""
    label_rows, _, _ = driver.execute_query(
        "CALL db.labels() YIELD label RETURN label", database_=database
    )
    rel_rows, _, _ = driver.execute_query(
        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType",
        database_=database,
    )
    return (
        {row["label"] for row in label_rows},
        {row["relationshipType"] for row in rel_rows},
    )


def validate_enrichment(driver: Driver, database: str) -> None:
    """Run sample queries to verify embeddings, entities, and cross-links."""

    print(f"\nValidation (sample size {_SAMPLE_SIZE}):")
    labels, rel_types = _get_existing_schema_tokens(driver, database)

    # 1. Chunks with embeddings linked to documents
    rows = []
    if {"Chunk", "Document"}.issubset(labels) and "FROM_DOCUMENT" in rel_types:
        rows, _, _ = driver.execute_query(
            f"""
            MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d:Document)
            WHERE c.embedding IS NOT NULL
            RETURN DISTINCT d.documentId AS doc, elementId(c) AS chunk_id, size(c.embedding) AS dims
            LIMIT {_SAMPLE_SIZE}
        """,
            database_=database,
        )
    print(f"\n  Chunks with embeddings -> Document ({len(rows)} samples):")
    for r in rows:
        print(f"    {r['chunk_id'][:12]}...  dims={r['dims']}  doc={r['doc']}")
    if not rows:
        print("    [WARN] No chunks with embeddings found!")

    # 2. Extracted manual entities
    rows, _, _ = driver.execute_query(
        """
        UNWIND $labels AS label
        OPTIONAL MATCH (n)
        WHERE label IN labels(n)
        RETURN label, count(n) AS count
        ORDER BY label
        """,
        labels=EXTRACTED_LABELS,
        database_=database,
    )
    print("\n  Extracted manual entities:")
    for r in rows:
        print(f"    {r['label']}: {r['count']}")

    # 3. Cross-links to operational graph
    if "Aircraft" not in labels:
        print("\n  Cross-links to operational graph:")
        print("    [WARN] No Aircraft nodes found. Run `uv run populate-aircraft-db setup`")
        print("           or load CSV data before running enrichment-only validation.")
        return

    # Each query runs only when the graph has the labels and type it names.
    queries = [
        (
            "Document -[:APPLIES_TO]-> Aircraft",
            "MATCH (d:Document)-[:APPLIES_TO]->(a:Aircraft) "
            f"RETURN d.title AS src, a.tail_number AS tgt LIMIT {_SAMPLE_SIZE}",
            {"Document", "Aircraft", "APPLIES_TO"},
        ),
        (
            "AircraftModel -[:DESCRIBES_MODEL]-> Aircraft",
            "MATCH (am:AircraftModel)-[:DESCRIBES_MODEL]->(a:Aircraft) "
            f"RETURN am.name AS src, a.tail_number AS tgt LIMIT {_SAMPLE_SIZE}",
            {"AircraftModel", "Aircraft", "DESCRIBES_MODEL"},
        ),
        (
            "ComponentReference -[:DESCRIBES_COMPONENT]-> Component",
            "MATCH (cr:ComponentReference)-[:DESCRIBES_COMPONENT]->(c:Component) "
            f"RETURN cr.name AS src, c.name AS tgt LIMIT {_SAMPLE_SIZE}",
            {"ComponentReference", "Component", "DESCRIBES_COMPONENT"},
        ),
        (
            "Sensor -[:HAS_LIMIT]-> OperatingLimit",
            "MATCH (s:Sensor)-[:HAS_LIMIT]->(ol:OperatingLimit) "
            f"RETURN s.type AS src, ol.name AS tgt LIMIT {_SAMPLE_SIZE}",
            {"Sensor", "OperatingLimit", "HAS_LIMIT"},
        ),
    ]
    print("\n  Cross-links to operational graph:")
    for label, query, names in queries:
        if names <= labels | rel_types:
            rows, _, _ = driver.execute_query(query, database_=database)
        else:
            rows = []
        if rows:
            pairs = ", ".join(f"{r['src']}->{r['tgt']}" for r in rows)
            print(f"    {label}: {pairs}")
        else:
            print(f"    {label}: (none)")
