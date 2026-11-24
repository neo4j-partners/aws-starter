"""Direct-to-Neo4j retrieval over the fleet graph.

There is no MCP server and no AgentCore Gateway in this path. The graph tools
connect straight to Neo4j with the driver and answer questions with two
``neo4j-graphrag`` retrievers:

- ``vector_search``: hybrid search over maintenance-document chunks. It
  combines the ``maintenanceChunkEmbeddings`` vector index with the
  ``maintenanceChunkText`` fulltext index, both populated by
  ``aircraft-fleet-pipeline``. Each hit carries its source document, aircraft
  type, and the entities extracted from that chunk.
- ``graph_query``: Text2Cypher. The LLM writes a read-only Cypher query from
  the live schema and the question, for exact and aggregate answers.

The embedder here MUST match the one ``aircraft-fleet-pipeline`` used to
populate the graph, or vector search returns noise. It defaults to Amazon
Bedrock Titan v2 with 1024 dimensions. Both are env-overridable.

Nothing in this module imports Strands. ``core.graph.tools`` wraps the two
callables below as Strands tools.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable
from functools import lru_cache

import neo4j
from neo4j import Driver, GraphDatabase
from neo4j.auth_management import AuthManager
from neo4j.exceptions import AuthError
from neo4j_graphrag.embeddings import BedrockEmbeddings
from neo4j_graphrag.llm import BedrockLLM
from neo4j_graphrag.retrievers import HybridCypherRetriever
from neo4j_graphrag.schema import get_schema
from neo4j_graphrag.types import RetrieverResultItem

from fleet_supervisor.core.config import AWS_REGION, MODEL_ID, ConfigError, graph_settings
from fleet_supervisor.core.graph.text2cypher import BoundedText2CypherRetriever
from fleet_supervisor.core.secrets import forget_secrets, neo4j_login

logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"{name} is not set. The graph tools connect directly to Neo4j. "
            "Set NEO4J_URI and the login variables in the shared aircraft-fleet "
            ".env for local runs, or as Runtime env vars when deployed."
        )
    return value


_driver: Driver | None = None
_auth: RotatingLoginAuthManager | None = None
_driver_lock = threading.Lock()

_UNAUTHORIZED = "Neo.ClientError.Security.Unauthorized"


def _fresh_login() -> neo4j.Auth:
    """Read the fleet graph login again, skipping the secrets cache.

    The cached secrets are dropped first, so a password rotated in Secrets
    Manager is read again.
    """
    forget_secrets()
    login = neo4j_login()
    return neo4j.basic_auth(login.username, login.password)


class RotatingLoginAuthManager(AuthManager):
    """Give the driver the fleet graph login, and follow a rotated password.

    The manager reads the login once and caches it. ``reload`` reads it again.

    neo4j 6.4 calls ``handle_security_exception`` only for an error on a
    connection that is already in the pool. When Neo4j rejects the login
    while a new connection opens, the driver raises the ``AuthError`` at once
    and never asks the manager. So callers run their Neo4j work through
    ``retry_on_rotated_login``, which reloads the login and retries once.

    For an ``Unauthorized`` error on a pooled connection, the manager reads
    the secret once. It asks the driver to retry only when the secret now
    holds a different login. ``AuthManagers.basic`` asks for a retry on every
    rejection. With a wrong password, the driver would then retry with
    backoff until ``max_transaction_retry_time``, about 30 s per query, and
    read the secret on each attempt.

    The memory path recovers from a rotation in ``server._build_agent``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._auth: neo4j.Auth | None = None

    def get_auth(self) -> neo4j.Auth:
        with self._lock:
            if self._auth is None:
                self._auth = _fresh_login()
            return self._auth

    def reload(self) -> bool:
        """Read the login again, skipping the secrets cache. Return True if it changed."""
        with self._lock:
            login = _fresh_login()
            changed = login != self._auth
            self._auth = login
            return changed

    def handle_security_exception(
        self, auth: neo4j.Auth, error: neo4j.exceptions.Neo4jError
    ) -> bool:
        """Return True when the driver should retry with a new login."""
        if error.code != _UNAUTHORIZED:
            return False
        with self._lock:
            if self._auth is not None and self._auth != auth:
                # Another connection already read the new login.
                return True
            login = _fresh_login()
            if login == auth:
                return False
            self._auth = login
            return True


def retry_on_rotated_login[T](auth: RotatingLoginAuthManager, call: Callable[[], T]) -> T:
    """Run ``call``, and run it once more if Neo4j rejected a login that has since rotated.

    It retries only an ``Unauthorized`` ``AuthError``, and only when ``auth``
    now holds a different login than the one ``call`` started with. Another
    call may already have read the new login, or ``reload`` finds it in the
    secret. A password that is still wrong raises after the one attempt. No
    other error is retried. ``call`` runs again from the start, so it must be
    safe to repeat.
    """
    started_with = auth.get_auth()
    try:
        return call()
    except AuthError as error:
        if error.code != _UNAUTHORIZED or (auth.get_auth() == started_with and not auth.reload()):
            raise
    # Outside the except block, so a second failure does not chain the first.
    logger.warning("Neo4j rejected the fleet graph login; retrying with the rotated one")
    return call()


def _shared_driver() -> tuple[Driver, RotatingLoginAuthManager]:
    """Return the process-wide driver and its auth manager, created together once."""
    global _driver, _auth
    with _driver_lock:
        if _driver is None or _auth is None:
            uri = _require_env("NEO4J_URI")
            logger.info("Connecting to Neo4j at %s", uri)
            _auth = RotatingLoginAuthManager()
            _driver = GraphDatabase.driver(uri, auth=_auth)
        return _driver, _auth


def get_driver() -> Driver:
    """Return the process-wide Neo4j driver. It is a connection pool, created once."""
    return _shared_driver()[0]


def _with_rotated_login[T](call: Callable[[], T]) -> T:
    """Run ``call`` on the shared driver through ``retry_on_rotated_login``."""
    return retry_on_rotated_login(_shared_driver()[1], call)


def _neo4j_database() -> str:
    return os.environ.get("NEO4J_DATABASE", "neo4j")


@lru_cache(maxsize=1)
def _embedder() -> BedrockEmbeddings:
    """Return the Bedrock embedder. It must match the one the pipeline used."""
    return BedrockEmbeddings(
        model_id=graph_settings.embed_model_id,
        dimensions=graph_settings.embed_dimensions,
        region_name=AWS_REGION,
    )


# Appended to the hybrid search, where ``node`` is the matched Chunk and
# ``score`` its hybrid score. It follows the lexical graph to the source
# Document and to every entity extracted from the chunk. Entity labels are not
# hard-coded, so this keeps working when the extraction schema changes.
#
# With ``$aircraft_type`` set, it keeps only that type's chunks and then the
# ``$result_k`` best. A null ``$aircraft_type`` keeps every chunk.
#
# The entity ``collect`` does not keep row order, so the final ORDER BY puts
# the hits back in score order.
CHUNK_RETRIEVAL_QUERY = """
OPTIONAL MATCH (node)-[:FROM_DOCUMENT]->(doc:Document)
WITH node, score, doc
WHERE $aircraft_type IS NULL OR toLower(doc.aircraftType) = toLower($aircraft_type)
WITH node, score, doc
ORDER BY score DESC
LIMIT $result_k
OPTIONAL MATCH (entity)-[:FROM_CHUNK]->(node)
WITH node, score, doc, collect(DISTINCT entity)[..$max_entities] AS entities
RETURN node.text AS text,
       score,
       doc.documentId AS document_id,
       doc.aircraftType AS aircraft_type,
       doc.title AS title,
       node.index AS chunk_index,
       [e IN entities |
           coalesce(head([l IN labels(e) WHERE NOT l STARTS WITH '__']), 'Entity')
           + ': ' + coalesce(e.name, '?')] AS entities
ORDER BY score DESC
"""

# Entities listed per chunk. Enough to show what the chunk is about without
# flooding the model context.
MAX_ENTITIES_PER_CHUNK = 10

# A search for one aircraft type takes this many times ``top_k`` hits from
# each index before the type filter. neo4j-graphrag rejects filters on
# hybrid search, so the filter runs after the hits are ranked. Each index
# returns only ``top_k`` hits, and other types' chunks would otherwise take
# most of them. A probe of 11 per-type EGT queries gave the same results
# from a pool of 4x top_k up.
TYPE_FILTER_POOL_FACTOR = 4

_PROVENANCE_KEYS = (
    "score",
    "document_id",
    "aircraft_type",
    "title",
    "chunk_index",
    "entities",
)


def _chunk_formatter(record: neo4j.Record) -> RetrieverResultItem:
    """Keep the chunk text as content and the provenance fields as metadata."""
    return RetrieverResultItem(
        content=record.get("text") or "",
        metadata={key: record.get(key) for key in _PROVENANCE_KEYS},
    )


def _format_hit(item: RetrieverResultItem) -> str:
    """Render one hit with a source header the model can cite."""
    meta = item.metadata or {}
    source = " | ".join(
        str(part)
        for part in (
            meta.get("document_id") or "unknown document",
            meta.get("aircraft_type"),
            f"chunk {meta['chunk_index']}" if meta.get("chunk_index") is not None else None,
            f"score {meta['score']:.3f}" if meta.get("score") is not None else None,
        )
        if part
    )
    lines = [f"[Source: {source}]"]
    if entities := meta.get("entities"):
        lines.append(f"Entities: {', '.join(entities)}")
    lines.append(str(item.content))
    return "\n".join(lines)


_LUCENE_TOKEN = re.compile(r"\w+")


def fulltext_query(text: str) -> str:
    """Reduce free text to plain lowercase word tokens for the fulltext index.

    ``db.index.fulltext.queryNodes`` parses its input as Lucene syntax, and
    neo4j-graphrag passes it through unescaped. A question such as
    ``"Is A320-200 EGT/N1 OK?"`` contains operators that fail to parse or
    change the match. Keeping only word tokens removes all syntax. Lowercasing
    also neutralizes the ``AND``, ``OR``, and ``NOT`` operators. The standard
    analyzer lowercases terms anyway, so matching is unchanged.
    """
    return " ".join(_LUCENE_TOKEN.findall(text.lower()))


@lru_cache(maxsize=1)
def _hybrid_retriever() -> HybridCypherRetriever:
    return HybridCypherRetriever(
        get_driver(),
        vector_index_name=graph_settings.vector_index_name,
        fulltext_index_name=graph_settings.fulltext_index_name,
        retrieval_query=CHUNK_RETRIEVAL_QUERY,
        embedder=_embedder(),
        result_formatter=_chunk_formatter,
        neo4j_database=_neo4j_database(),
    )


_schema_lock = threading.Lock()
_schema_cache: tuple[float, str] | None = None


def get_graph_schema() -> str:
    """Live Neo4j schema string, cached for ``SCHEMA_TTL_S`` seconds.

    The TTL lets a running server pick up a pipeline reload without a restart.
    A failure raises and caches nothing, so the next call tries again.
    """
    global _schema_cache
    with _schema_lock:
        now = time.monotonic()
        if _schema_cache is not None and now - _schema_cache[0] < graph_settings.schema_ttl_s:
            return _schema_cache[1]
        logger.info("Fetching Neo4j schema")
        schema = get_schema(get_driver(), database=_neo4j_database())
        _schema_cache = (now, schema)
        logger.info("Schema cached (%d bytes)", len(schema))
        return schema


@lru_cache(maxsize=1)
def _text2cypher_retriever() -> BoundedText2CypherRetriever:
    return BoundedText2CypherRetriever(
        get_driver(),
        llm=BedrockLLM(
            model_name=MODEL_ID,
            region_name=AWS_REGION,
            # Merged into the Converse inferenceConfig.
            model_params={"maxTokens": graph_settings.text2cypher_max_tokens},
        ),
        neo4j_schema=get_graph_schema(),
        neo4j_database=_neo4j_database(),
        timeout_s=graph_settings.text2cypher_timeout_s,
        max_rows=graph_settings.text2cypher_max_rows,
    )


def vector_search(query: str, top_k: int = 5, aircraft_type: str | None = None) -> str:
    """Return the ``top_k`` best hybrid-search chunks with their sources.

    With ``aircraft_type`` set, only chunks from that type's manual count.
    The type is also added to the search text when the query doesn't name
    it, so both indexes rank that type's chunks first and the filter keeps
    ``top_k`` of them.
    The model-facing description lives on ``core.graph.tools.vector_search_tool``.
    """
    aircraft_type = (aircraft_type or "").strip() or None
    if aircraft_type and aircraft_type.lower() not in query.lower():
        query = f"{aircraft_type} {query}"
    text = fulltext_query(query)
    if not text:
        return "No relevant document chunks found."
    pool = top_k * TYPE_FILTER_POOL_FACTOR if aircraft_type else top_k
    logger.info("vector_search query=%r top_k=%d aircraft_type=%s", query, top_k, aircraft_type)
    # Embed outside the retried call, so a rotated login does not embed twice.
    query_vector = _embedder().embed_query(query)
    result = _with_rotated_login(
        lambda: _hybrid_retriever().search(
            query_text=text,
            query_vector=query_vector,
            top_k=pool,
            query_params={
                "max_entities": MAX_ENTITIES_PER_CHUNK,
                "aircraft_type": aircraft_type,
                "result_k": top_k,
            },
        )
    )
    hits = [item for item in result.items if item.content]
    if not hits:
        if aircraft_type:
            return f"No relevant document chunks found for aircraft type {aircraft_type}."
        return "No relevant document chunks found."
    return "\n\n---\n\n".join(_format_hit(item) for item in hits)


def graph_query(question: str) -> str:
    """Generate Cypher for ``question``, run it, and return the rows as text.

    The model-facing description lives on ``core.graph.tools.graph_query_tool``.
    The current cached schema is passed on every call, so a schema refresh
    reaches the Cypher prompt without rebuilding the retriever.
    A rejected login that has rotated reruns the whole search, Cypher
    generation included. Claude writes the Cypher again, so the second query
    can differ from the first.
    """
    result = _with_rotated_login(
        lambda: _text2cypher_retriever().search(
            query_text=question,
            prompt_params={"schema": get_graph_schema()},
        )
    )
    if not result.items:
        return "The generated query returned no results."
    rows = "\n".join(str(item.content) for item in result.items)
    if result.metadata and result.metadata.get("truncated"):
        rows += (
            f"\n(Showing the first {len(result.items)} rows. "
            "Aggregate or filter the question to see the rest.)"
        )
    return rows


def close() -> None:
    """Close the shared driver. Safe to call when no driver was opened.

    The cached retrievers hold the driver, so they are dropped too. The next
    call builds a new driver and new retrievers.
    """
    global _driver, _auth
    with _driver_lock:
        _hybrid_retriever.cache_clear()
        _text2cypher_retriever.cache_clear()
        if _driver is not None:
            _driver.close()
            _driver = None
        _auth = None
