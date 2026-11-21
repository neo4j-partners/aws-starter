"""CLI entry point for populate-aircraft-db."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Literal, TextIO

import typer
from neo4j import Driver, GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from generator.stamp import stale_reason

from .config import Settings
from .loader import clear_database, dataset_mismatch, load_operational_graph, verify
from .schema import (
    create_constraints,
    create_embedding_indexes,
    create_extraction_constraints,
    create_fulltext_indexes,
    create_indexes,
    drop_extraction_constraints,
)

app = typer.Typer(
    name="populate-aircraft-db",
    help="Load the Aircraft Digital Twin dataset into a Neo4j Aura instance.",
    add_completion=False,
    pretty_exceptions_show_locals=False,
)


class _SysStreamHandler(logging.StreamHandler):
    """Write each record to sys.stdout or sys.stderr as it is at emit time.

    CliRunner and pytest replace sys.stdout and sys.stderr and can close the
    old ones, so the handler does not keep the stream it was created with.
    """

    def __init__(self, stream_name: Literal["stdout", "stderr"]) -> None:
        self._stream_name = stream_name
        super().__init__()

    @property
    def stream(self) -> TextIO:
        return getattr(sys, self._stream_name)

    @stream.setter
    def stream(self, value: TextIO) -> None:
        # StreamHandler.__init__ assigns a stream. The getter ignores it and
        # always returns the current sys stream.
        del value

    def emit(self, record: logging.LogRecord) -> None:
        # When stdout is a block-buffered pipe, as in setup.sh 2>&1 | tee,
        # earlier print() output can still sit in its buffer. Flushing it
        # first keeps a stderr record after that output.
        # stdout can be None (pythonw, a closed descriptor) or a pipe whose
        # reader has exited. The flush only orders output, so a failure must
        # not stop the record from reaching stderr.
        if self._stream_name == "stderr" and (stdout := sys.stdout) is not None:
            with suppress(OSError, ValueError):
                stdout.flush()
        super().emit(record)


class _CliFormatter(logging.Formatter):
    """Format a record as its bare message, after a blank line if it asks for one.

    A library marks the start of a section with extra={"blank_before": True}.
    Only the CLI turns the mark into a blank line, so other log consumers see
    the record unchanged.
    """

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        return f"\n{message}" if getattr(record, "blank_before", False) else message


def _below_warning(record: logging.LogRecord) -> bool:
    return record.levelno < logging.WARNING


def _configure_logging() -> None:
    """Write this package's records as bare messages.

    INFO records go to stdout, and WARNING and higher go to stderr. A record
    with extra={"blank_before": True} follows a blank line.

    Only the package logger gets handlers, and its records do not propagate
    to the root logger. Other libraries keep the root logger's WARNING
    default, so INFO records from httpx and neo4j stay hidden. A repeat call
    keeps the existing handlers.
    """
    package_logger = logging.getLogger(__package__)
    package_logger.setLevel(logging.INFO)
    package_logger.propagate = False
    if any(isinstance(h, _SysStreamHandler) for h in package_logger.handlers):
        return
    stdout_handler = _SysStreamHandler("stdout")
    stdout_handler.addFilter(_below_warning)
    stderr_handler = _SysStreamHandler("stderr")
    stderr_handler.setLevel(logging.WARNING)
    for handler in (stdout_handler, stderr_handler):
        handler.setFormatter(_CliFormatter("%(message)s"))
        package_logger.addHandler(handler)


@app.callback()
def _main() -> None:
    _configure_logging()


def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


@contextmanager
def _connect(settings: Settings) -> Generator[Driver, None, None]:
    """Create a Neo4j driver, verify connectivity, and close on exit."""
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password.get_secret_value()),
    )
    try:
        driver.verify_connectivity()
    except (ServiceUnavailable, OSError) as exc:
        driver.close()
        print(f"[FAIL] Cannot connect to {settings.neo4j_uri}")
        print(f"       {exc}")
        print("\nCheck that the Neo4j instance is running and reachable.")
        sys.exit(1)
    try:
        print("[OK] Connected.\n")
        yield driver
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# LLM credential resolution
# ---------------------------------------------------------------------------


@dataclass
class _LLMCredentials:
    provider: Literal["bedrock", "openai", "anthropic"]
    openai_key: str | None
    anthropic_key: str | None
    llm_model: str
    llm_max_tokens: int
    embedding_model: str
    embedding_dims: int
    region: str | None = None


def _expected_embedding_dims(settings: Settings) -> int:
    """Embedding dimensionality for the active provider (read-only, no keys)."""
    if settings.llm_provider == "bedrock":
        return settings.bedrock_embedding_dimensions
    return settings.openai_embedding_dimensions


def _resolve_llm_credentials(settings: Settings) -> _LLMCredentials:
    """Validate and resolve LLM credentials from settings. Raises typer.BadParameter on failure."""
    provider = settings.llm_provider
    openai_key = None
    anthropic_key = None
    region = None

    if provider == "bedrock":
        # AWS credentials come from the standard boto3 chain, not this file.
        region = settings.aws_region
        llm_model = settings.bedrock_llm_model
        llm_max_tokens = settings.bedrock_llm_max_tokens
        embedding_model = settings.bedrock_embedding_model
        embedding_dims = settings.bedrock_embedding_dimensions
        return _LLMCredentials(
            provider=provider,
            openai_key=None,
            anthropic_key=None,
            llm_model=llm_model,
            llm_max_tokens=llm_max_tokens,
            embedding_model=embedding_model,
            embedding_dims=embedding_dims,
            region=region,
        )

    if provider == "openai":
        if settings.openai_api_key is None:
            raise typer.BadParameter(
                "OPENAI_API_KEY is required when using OpenAI. Set it in .env or as an env var."
            )
        openai_key = settings.openai_api_key.get_secret_value()
        llm_model = settings.openai_extraction_model
        llm_max_tokens = settings.openai_extraction_max_completion_tokens
    elif provider == "anthropic":
        # Anthropic still needs OpenAI for embeddings.
        if settings.openai_api_key is None:
            raise typer.BadParameter(
                "OPENAI_API_KEY is required for embeddings when using Anthropic. "
                "Set it in .env or as an env var."
            )
        openai_key = settings.openai_api_key.get_secret_value()
        if settings.anthropic_api_key is None:
            raise typer.BadParameter(
                "ANTHROPIC_API_KEY is required when using Anthropic. "
                "Set it in .env or as an env var."
            )
        anthropic_key = settings.anthropic_api_key.get_secret_value()
        llm_model = settings.anthropic_extraction_model
        llm_max_tokens = settings.anthropic_extraction_max_tokens
    else:
        raise typer.BadParameter(f"Unknown provider: {provider!r}. Use 'openai' or 'anthropic'.")

    embedding_model = settings.openai_embedding_model
    embedding_dims = settings.openai_embedding_dimensions

    return _LLMCredentials(
        provider=provider,
        openai_key=openai_key,
        anthropic_key=anthropic_key,
        llm_model=llm_model,
        llm_max_tokens=llm_max_tokens,
        embedding_model=embedding_model,
        embedding_dims=embedding_dims,
    )


# ---------------------------------------------------------------------------
# Enrichment helper
# ---------------------------------------------------------------------------


def _run_enrich(driver: Driver, settings: Settings, creds: _LLMCredentials) -> None:
    """Run the enrichment pipeline: chunk, embed, extract entities, and link."""
    from .pipeline import (
        clear_enrichment_data,
        link_to_existing_graph,
        process_all_documents,
        validate_enrichment,
    )

    print("Clearing existing enrichment data (safe re-run)...")
    clear_enrichment_data(driver, settings.neo4j_database)
    print()

    print("Dropping extraction constraints for pipeline write phase...")
    drop_extraction_constraints(driver, settings.neo4j_database)
    print()

    # Document and Chunk constraints must exist before the pipeline writes.
    # create_constraints is idempotent, so a graph loaded earlier is unchanged.
    print("Creating constraints...")
    create_constraints(driver, settings.neo4j_database)
    print()

    if settings.enrich_sample_size:
        print(
            f"Running SimpleKGPipeline (LLM: {creds.provider}/{creds.llm_model}, "
            f"max_tokens={creds.llm_max_tokens}, "
            f"sample_size={settings.enrich_sample_size} chunks/doc)..."
        )
    else:
        print(
            f"Running SimpleKGPipeline (LLM: {creds.provider}/{creds.llm_model}, "
            f"max_tokens={creds.llm_max_tokens})..."
        )

    process_all_documents(
        driver,
        settings.neo4j_database,
        settings.document_dir,
        provider=creds.provider,
        openai_api_key=creds.openai_key,
        anthropic_api_key=creds.anthropic_key,
        region=creds.region,
        llm_model=creds.llm_model,
        llm_max_tokens=creds.llm_max_tokens,
        embedding_model=creds.embedding_model,
        embedding_dimensions=creds.embedding_dims,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        enrich_sample_size=settings.enrich_sample_size,
    )

    print("\nCreating extraction constraints (post entity-resolution)...")
    create_extraction_constraints(driver, settings.neo4j_database)

    print("\nCreating embedding indexes...")
    create_embedding_indexes(driver, settings.neo4j_database, creds.embedding_dims)

    print("\nLinking to existing graph...")
    link_to_existing_graph(driver, settings.neo4j_database)

    validate_enrichment(driver, settings.neo4j_database)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@app.command("setup")
def setup_cmd() -> None:
    """Load CSV data into Neo4j and run GraphRAG enrichment in a single pass."""
    settings = Settings()  # type: ignore[call-arg]

    # Validate LLM credentials early, before any Neo4j work.
    creds = _resolve_llm_credentials(settings)

    start = time.monotonic()

    print(f"Connecting to {settings.neo4j_uri}...")
    with _connect(settings) as driver:
        print("Creating constraints...")
        create_constraints(driver, settings.neo4j_database)
        print("\nCreating indexes...")
        create_indexes(driver, settings.neo4j_database)
        print("\nCreating fulltext indexes...")
        create_fulltext_indexes(driver, settings.neo4j_database)
        print()

        load_operational_graph(driver, settings.neo4j_database, settings.data_dir)
        print()

        try:
            _run_enrich(driver, settings, creds)
        except Exception as exc:
            print(f"\n[FAIL] Enrichment failed: {exc}")
            print("CSV data was loaded successfully. Fix the issue and re-run:")
            print("  uv run populate-aircraft-db setup")
            raise typer.Exit(code=1) from exc

        verify(
            driver,
            settings.neo4j_database,
            expected_embedding_dimensions=creds.embedding_dims,
        )

    elapsed = time.monotonic() - start
    print(f"\nDone in {_fmt_elapsed(elapsed)}.")


@app.command("verify")
def verify_cmd(
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit with a nonzero status when verification warnings are found.",
    ),
) -> None:
    """Run comprehensive graph verification (read-only)."""
    settings = Settings()  # type: ignore[call-arg]

    # Two checks: the stamp in generated/ against the current generator code,
    # and the graph's Dataset node against that stamp. Each says which one
    # is out of date.
    status = "[FAIL]" if strict else "[WARN]"
    code_reason = stale_reason(settings.data_dir)
    if code_reason:
        print(f"{status} Generated CSVs are stale: {code_reason}.")
        print("  Regenerate and reload: ./setup.sh generate, then ./setup.sh load.")

    print(f"Connecting to {settings.neo4j_uri}...")
    with _connect(settings) as driver:
        graph_reason = dataset_mismatch(driver, settings.neo4j_database, settings.data_dir)
        if graph_reason:
            print(f"{status} The graph does not match the generated CSVs: {graph_reason}.")
            print("  Reload: ./setup.sh load.")
        if strict and (code_reason or graph_reason):
            raise typer.Exit(code=1)
        passed = verify(
            driver,
            settings.neo4j_database,
            expected_embedding_dimensions=_expected_embedding_dims(settings),
            strict=strict,
        )

    if strict and not passed:
        raise typer.Exit(code=1)


@app.command("clean")
def clean_cmd() -> None:
    """Clear all nodes and relationships from the database."""
    settings = Settings()  # type: ignore[call-arg]

    print(f"Connecting to {settings.neo4j_uri}...")
    with _connect(settings) as driver:
        clear_database(driver, settings.neo4j_database)

    print("\nDone.")


@app.command("clean-enrichment")
def clean_enrichment_cmd() -> None:
    """Clear enrichment data (Documents, Chunks, extracted entities) while preserving the operational graph."""
    from .pipeline import clear_enrichment_data

    settings = Settings()  # type: ignore[call-arg]

    print(f"Connecting to {settings.neo4j_uri}...")
    with _connect(settings) as driver:
        clear_enrichment_data(driver, settings.neo4j_database)

    print("\nDone.")


@app.command("load-operational")
def load_operational_cmd() -> None:
    """Load only CSV operational data and relink existing enrichment."""
    from .pipeline import link_to_existing_graph, validate_enrichment

    settings = Settings()  # type: ignore[call-arg]

    start = time.monotonic()

    print(f"Connecting to {settings.neo4j_uri}...")
    with _connect(settings) as driver:
        print("Creating constraints...")
        create_constraints(driver, settings.neo4j_database)
        print("\nCreating indexes...")
        create_indexes(driver, settings.neo4j_database)
        print("\nCreating fulltext indexes...")
        create_fulltext_indexes(driver, settings.neo4j_database)
        print()

        load_operational_graph(driver, settings.neo4j_database, settings.data_dir)
        print()

        print("Linking existing enrichment to operational graph...")
        link_to_existing_graph(driver, settings.neo4j_database)

        validate_enrichment(driver, settings.neo4j_database)

    elapsed = time.monotonic() - start
    print(f"\nDone in {_fmt_elapsed(elapsed)}.")


@app.command("enrich")
def enrich_cmd() -> None:
    """Run GraphRAG enrichment against an already-loaded operational graph."""
    settings = Settings()  # type: ignore[call-arg]
    creds = _resolve_llm_credentials(settings)

    print(f"Connecting to {settings.neo4j_uri}...")
    with _connect(settings) as driver:
        _run_enrich(driver, settings, creds)

    print("\nDone.")


@app.command("debug-extract")
def debug_extract_cmd(
    document: str = typer.Option(
        "MAINTENANCE_A321neo.md",
        "--document",
        "-d",
        help="Maintenance manual filename in DOCUMENT_DIR.",
    ),
    chunks: str = typer.Option(
        "3,5,6,7,9,10,11,12,13,15,16",
        "--chunks",
        "-c",
        help="Comma-separated chunk indexes to send to the extractor.",
    ),
) -> None:
    """Validate extractor output for selected chunks without writing to Neo4j."""
    from .pipeline import debug_extract_chunks

    settings = Settings()  # type: ignore[call-arg]
    creds = _resolve_llm_credentials(settings)
    try:
        chunk_indexes = [int(index.strip()) for index in chunks.split(",") if index.strip()]
    except ValueError as exc:
        raise typer.BadParameter("--chunks must be a comma-separated list of integers") from exc

    try:
        passed = debug_extract_chunks(
            settings.document_dir,
            filename=document,
            chunk_indexes=chunk_indexes,
            provider=creds.provider,
            openai_api_key=creds.openai_key,
            anthropic_api_key=creds.anthropic_key,
            region=creds.region,
            llm_model=creds.llm_model,
            llm_max_tokens=creds.llm_max_tokens,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
    except ImportError as exc:
        print(f"[FAIL] {exc}")
        if creds.provider == "anthropic":
            print("Install Anthropic support with: uv sync --extra anthropic")
        raise typer.Exit(code=1) from exc
    if not passed:
        raise typer.Exit(code=1)


@app.command("samples")
def samples_cmd() -> None:
    """Run sample queries showcasing the knowledge graph (read-only)."""
    from .samples import run_all_samples

    settings = Settings()  # type: ignore[call-arg]

    print(f"Connecting to {settings.neo4j_uri}...")
    with _connect(settings) as driver:
        run_all_samples(driver, settings.neo4j_database, sample_size=settings.sample_size)


@app.command("agent-samples")
def agent_samples_cmd() -> None:
    """Simulate the Neo4j Aura Agent: send natural language questions to the LLM,
    generate Cypher or vector searches, execute them, and display results."""
    from .agent_samples import run_agent_samples

    settings = Settings()  # type: ignore[call-arg]
    creds = _resolve_llm_credentials(settings)

    print(f"Connecting to {settings.neo4j_uri}...")
    with _connect(settings) as driver:
        run_agent_samples(
            driver,
            settings.neo4j_database,
            provider=creds.provider,
            openai_key=creds.openai_key,
            anthropic_key=creds.anthropic_key,
            region=creds.region,
            llm_model=creds.llm_model,
            embedding_model=creds.embedding_model,
            embedding_dimensions=creds.embedding_dims,
            sample_size=settings.sample_size,
        )


if __name__ == "__main__":
    app()
