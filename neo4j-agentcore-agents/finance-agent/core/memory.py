"""User-scoped Context Graph memory tools for the Strands Finance Agent.

Background
----------
``neo4j_agent_memory`` 0.2.1 ships a Strands integration
(``context_graph_tools``) whose tools accept a ``user_id`` argument but do
**not** isolate by it:

* ``add_memory`` calls ``short_term.add_message`` without ``user_identifier``,
  so no ``:User`` node or ``(:User)-[:HAS_CONVERSATION]->`` link is written.
* ``search_context`` calls ``short_term.search_messages`` with no scope, and
  that method's ``session_id`` parameter is documented but unimplemented — the
  query is always a global vector search.

The library *core*, however, fully supports multi-tenancy: ``add_message``
and ``add_preference`` take ``user_identifier=``, ``_ensure_conversation``
links the ``:User`` node and denormalizes ``user_identifier`` onto the
``:Conversation``, and ``users.upsert_user`` is idempotent.

This module re-implements the three user-relevant tools on top of that core
API so memory is genuinely isolated per ``user_id`` and recalled across all of
that user's sessions. The library's ``get_entity_graph`` is re-exported
unchanged — entity nodes are shared, not user-scoped, in 0.2.1; that boundary
is intentional and documented rather than papered over.

It builds the ``MemoryClient`` itself (``_build_memory_client``) instead of
calling the library's ``_get_or_create_client``. In the vendored 0.2.1 wheel
that helper constructs ``Neo4jConfig(user=...)`` while the model's field is
``username`` with ``extra="forbid"``, so every client build there raises
``1 validation error for Neo4jConfig / user / Extra inputs are not
permitted``. Our builder mirrors the library's provider-string
normalization and Bedrock embed kwargs but passes ``username``.

A fresh ``MemoryClient`` is built per tool call and discarded (each tool
opens it with ``async with`` and closes it). The client is **not** cached
across calls: ``_run_async`` runs each call in its own event loop (a worker
thread when the Strands runtime already holds a loop), and a Neo4j async
driver binds its connection pool to the loop of its first ``await``. A
client reused from a later call's different loop raises ``Task got Future
attached to a different loop``. Per-call construction keeps each driver
bound to exactly the loop that uses it.

The library's ``get_entity_graph`` is re-exported but wrapped: its inner
``_get_or_create_client`` is the broken ``user=...`` path, so before each
invocation the wrapper primes the library's ``_client_cache`` with a
freshly built (correct) client under the library's cache-key formula and
pops it afterward, so that tool also builds fresh per call and never hits
the broken path. ``_run_async`` is reimplemented locally. Only
``_create_get_entity_graph_tool`` is still imported: its traversal Cypher
is large and the entity graph is intentionally not user-scoped, so forking
it would add risk for no gain.

This ``core`` module depends on ``neo4j_agent_memory``; ``core/__init__``
does not import it, so importers that do not need memory tools never pull
the dependency.
"""

import asyncio
import concurrent.futures
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Managed vector index over :Message(embedding) (see the library's
# graph/schema.py _MANAGED_VECTOR_INDEXES). Used as a literal — never
# interpolated with caller input.
_MESSAGE_VECTOR_INDEX = "message_embedding_idx"

# The vector index returns its top-N globally; we then keep only the calling
# user's messages. Oversample so a user's hits are not crowded out by other
# tenants' more-similar messages before the user filter is applied.
_CANDIDATE_MULTIPLIER = 20
_MIN_CANDIDATES = 50
_MAX_CANDIDATES = 1000

# All parameters below are bound, never string-formatted, so user_id /
# category cannot inject Cypher.
_USER_MESSAGE_SEARCH = f"""
CALL db.index.vector.queryNodes('{_MESSAGE_VECTOR_INDEX}', $candidates, $embedding)
YIELD node AS m, score
WHERE score >= $threshold
MATCH (c:Conversation)-[:HAS_MESSAGE]->(m)
WHERE c.user_identifier = $user_id
RETURN m.role AS role,
       m.content AS content,
       toString(m.timestamp) AS timestamp,
       score AS score
ORDER BY score DESC
LIMIT $limit
"""

_USER_PREFERENCES = """
MATCH (u:User {identifier: $user_id})-[:HAS_PREFERENCE]->(p:Preference)
WHERE $category IS NULL OR toLower(p.category) = toLower($category)
RETURN p.category AS category,
       p.preference AS preference,
       p.context AS context,
       p.confidence AS confidence
ORDER BY p.confidence DESC
LIMIT $limit
"""


def _normalize_user_id(value: object) -> str:
    """Stable, non-empty scope key. Falls back to ``"anonymous"``.

    Scoping must be deterministic even when the model passes an empty or
    whitespace-only ``user_id``; an empty scope would silently merge tenants.
    Cypher injection is not a concern here (the value is always a bound
    parameter), so only emptiness is normalized.
    """
    text = str(value).strip() if value is not None else ""
    return text or "anonymous"


def _candidate_count(top_k: int) -> int:
    """Vector-index fan-out to request before the per-user filter."""
    scaled = max(top_k, 1) * _CANDIDATE_MULTIPLIER
    return max(_MIN_CANDIDATES, min(scaled, _MAX_CANDIDATES))


# Library default when the caller does not pin an embedding model; kept in
# sync with the vendored wheel's _get_or_create_client.
_DEFAULT_EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
_PROVIDER_PREFIXES = {
    "bedrock": "bedrock/",
    "openai": "openai/",
    "vertex_ai": "vertex_ai/",
}


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from a synchronous Strands tool.

    Local copy of the library's helper so this module no longer depends on
    that private symbol. When a loop is already running (the Strands async
    runtime), the coroutine runs in a worker thread.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _embedding_model_string(provider: str, model: str | None) -> str:
    """Normalize a Strands provider/model pair to a ``from_provider`` string.

    Mirrors the vendored wheel's logic so the embedder is built identically;
    only the broken ``Neo4jConfig`` construction is replaced.
    """
    model_id = model or _DEFAULT_EMBEDDING_MODEL
    if provider == "sentence_transformers":
        if "/" in model_id:
            return model_id
        return f"sentence-transformers/{model_id}"
    return f"{_PROVIDER_PREFIXES.get(provider, 'bedrock/')}{model_id}"


def _build_memory_client(config: dict[str, Any]) -> Any:
    """Construct a fresh ``MemoryClient`` with a valid Neo4j config.

    Replaces the vendored wheel's ``_get_or_create_client``, which builds
    ``Neo4jConfig(user=...)`` while that model's field is ``username`` with
    ``extra="forbid"``; every client build there raises
    ``Extra inputs are not permitted [user]``. We pass ``username`` and
    otherwise mirror the library's provider-string and Bedrock embed-kwarg
    handling.

    A new client is returned on every call (no cross-call cache): each tool
    runs in its own event loop via ``_run_async`` and a Neo4j async driver
    binds to the loop of its first ``await``, so a reused client from a
    different loop raises ``Task got Future attached to a different loop``.
    """
    try:
        from neo4j_agent_memory import MemoryClient, MemorySettings
        from neo4j_agent_memory.config.settings import Neo4jConfig
        from neo4j_agent_memory.llm import from_provider
    except ImportError as e:  # pragma: no cover - vendored wheel guaranteed
        raise ImportError(
            "neo4j-agent-memory (strands extra) is required. Its modules "
            "moved or the wheel changed; refresh via "
            "scripts/vendor-memory.sh and re-check this module."
        ) from e

    uri = config["neo4j_uri"]
    username = config["neo4j_user"]
    database = config["neo4j_database"]

    model_string = _embedding_model_string(
        config["embedding_provider"], config.get("embedding_model")
    )
    embed_kwargs: dict[str, Any] = {}
    if config["embedding_provider"] == "bedrock":
        for key in ("aws_region", "aws_profile"):
            if config.get(key) is not None:
                embed_kwargs[key] = config[key]
    embedder = from_provider(model_string, kind="embedding", **embed_kwargs)

    settings = MemorySettings(
        neo4j=Neo4jConfig(
            uri=uri,
            username=username,
            password=config["neo4j_password"],
            database=database,
        ),
        embedding=embedder,
    )
    return MemoryClient(settings)


def user_scoped_context_graph_tools(
    neo4j_uri: str | None = None,
    neo4j_user: str = "neo4j",
    neo4j_password: str | None = None,
    neo4j_database: str = "neo4j",
    embedding_provider: str = "bedrock",
    embedding_model: str | None = None,
    **kwargs: Any,
) -> list[Any]:
    """Build user-scoped Strands memory tools.

    Drop-in replacement for ``neo4j_agent_memory.integrations.strands``'s
    ``context_graph_tools``. Same tool names and signatures (so the agent's
    memory system prompt is unchanged), but ``search_context`` /
    ``add_memory`` / ``get_user_preferences`` isolate by ``user_id``.
    ``get_entity_graph`` is the library's, re-exported unchanged.

    Args mirror ``context_graph_tools``. ``neo4j_uri`` / ``neo4j_password``
    default to ``NEO4J_URI`` / ``NEO4J_PASSWORD`` and a ``ValueError`` is
    raised if either is unresolvable. Memory is a core capability of the
    Finance Agent, so the runtime treats that ``ValueError`` as fatal and
    aborts startup rather than running without memory.

    Returns:
        ``[search_context, add_memory, get_user_preferences,
        get_entity_graph]`` as Strands ``@tool`` callables.
    """
    try:
        from strands import tool
    except ImportError as e:
        raise ImportError(
            "strands-agents is required for the Strands memory tools. "
            "Install with: pip install strands-agents"
        ) from e

    try:
        from neo4j_agent_memory.integrations.strands.tools import (
            _client_cache as _lib_client_cache,
            _create_get_entity_graph_tool,
        )
    except ImportError as e:  # pragma: no cover - vendored wheel guaranteed
        raise ImportError(
            "neo4j-agent-memory (strands extra) is required. Its private "
            "helpers moved or the wheel changed; refresh via "
            "scripts/vendor-memory.sh and re-check this module."
        ) from e

    uri = neo4j_uri or os.environ.get("NEO4J_URI")
    password = neo4j_password or os.environ.get("NEO4J_PASSWORD")
    if not uri:
        raise ValueError(
            "neo4j_uri is required. Provide it or set NEO4J_URI."
        )
    if not password:
        raise ValueError(
            "neo4j_password is required. Provide it or set NEO4J_PASSWORD."
        )

    config: dict[str, Any] = {
        "neo4j_uri": uri,
        "neo4j_user": neo4j_user,
        "neo4j_password": password,
        "neo4j_database": neo4j_database,
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        **kwargs,
    }

    def _log_failures(coro: Any, tool_name: str, uid: str) -> Any:
        """Run ``coro`` via ``_run_async``, logging any failure with traceback.

        The Strands ``@tool`` runtime converts an uncaught exception into a
        generic tool-error the model narrates over, so a Neo4j/embedding
        failure here is otherwise invisible in CloudWatch. Log it with a
        traceback, then re-raise so the tool result still signals failure.
        """
        try:
            return _run_async(coro)
        except Exception:
            logger.exception("%s failed for user_id=%s", tool_name, uid)
            raise

    @tool
    def search_context(
        query: str,
        user_id: str,
        top_k: int = 10,
        min_score: float = 0.5,
        include_relationships: bool = True,
    ) -> list[dict[str, Any]]:
        """Search this user's Context Graph memory for relevant past context.

        Recalls only memories belonging to ``user_id``, across all of that
        user's prior sessions. Call this before answering when the user
        refers to something they may have told you earlier.

        Args:
            query: What to look for.
            user_id: The user whose memory to search (scopes the results).
            top_k: Max results to return (default: 10).
            min_score: Minimum similarity score, 0-1 (default: 0.5).
            include_relationships: Accepted for signature parity with the
                stock tool; this scoped variant returns messages and
                preferences only.

        Returns:
            A list of ``{"type": "message"|"preference", ...}`` items.
        """
        uid = _normalize_user_id(user_id)

        async def _search() -> list[dict[str, Any]]:
            client = _build_memory_client(config)
            async with client:
                embedder = client.short_term._embedder
                if embedder is None:
                    logger.debug("No embedder configured; search disabled")
                    return []
                embedding = await embedder.embed(query)

                results: list[dict[str, Any]] = []
                try:
                    rows = await client._client.execute_read(
                        _USER_MESSAGE_SEARCH,
                        {
                            "embedding": embedding,
                            "candidates": _candidate_count(top_k),
                            "threshold": min_score,
                            "user_id": uid,
                            "limit": top_k,
                        },
                    )
                    results.extend(
                        {
                            "type": "message",
                            "role": r["role"],
                            "content": r["content"],
                            "timestamp": r["timestamp"],
                            "score": r["score"],
                        }
                        for r in rows
                    )
                except Exception as e:  # noqa: BLE001 - best-effort recall
                    logger.debug("Scoped message search failed: %s", e)

                try:
                    prefs = await client._client.execute_read(
                        _USER_PREFERENCES,
                        {"user_id": uid, "category": None, "limit": top_k},
                    )
                    results.extend(
                        {
                            "type": "preference",
                            "category": p["category"],
                            "preference": p["preference"],
                            "context": p["context"],
                        }
                        for p in prefs
                    )
                except Exception as e:  # noqa: BLE001 - best-effort recall
                    logger.debug("Scoped preference search failed: %s", e)

                return results

        return _log_failures(_search(), "search_context", uid)

    @tool
    def add_memory(
        content: str,
        user_id: str,
        session_id: str | None = None,
        extract_entities: bool = True,
    ) -> dict[str, Any]:
        """Persist a durable fact about this user for future sessions.

        The memory is written under the user's ``:User`` node so later
        ``search_context`` calls for the same ``user_id`` recall it, even
        from a different session.

        Args:
            content: The fact to remember.
            user_id: The user this memory belongs to (scopes storage).
            session_id: Optional session label; defaults to a per-user
                bucket so recall spans sessions.
            extract_entities: Whether to extract entities (default: True).

        Returns:
            Confirmation including the stored message id and scope.
        """
        uid = _normalize_user_id(user_id)
        effective_session = session_id or f"user:{uid}"

        async def _add() -> dict[str, Any]:
            client = _build_memory_client(config)
            async with client:
                # Idempotent; guarantees the :User node exists even before
                # the conversation link is written.
                await client.users.upsert_user(identifier=uid)
                message = await client.short_term.add_message(
                    session_id=effective_session,
                    role="user",
                    content=content,
                    user_identifier=uid,
                    extract_entities=extract_entities,
                )
                return {
                    "stored": True,
                    "user_id": uid,
                    "session_id": effective_session,
                    "message_id": str(message.id),
                    "content_preview": (
                        content[:100] + "..." if len(content) > 100 else content
                    ),
                }

        return _log_failures(_add(), "add_memory", uid)

    @tool
    def get_user_preferences(
        user_id: str,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve stored preferences for this user.

        Args:
            user_id: The user whose preferences to fetch (scopes the result).
            category: Optional category filter (case-insensitive).

        Returns:
            A list of ``{category, preference, context, confidence}``.
        """
        uid = _normalize_user_id(user_id)

        async def _get() -> list[dict[str, Any]]:
            client = _build_memory_client(config)
            async with client:
                try:
                    rows = await client._client.execute_read(
                        _USER_PREFERENCES,
                        {"user_id": uid, "category": category, "limit": 50},
                    )
                except Exception as e:  # noqa: BLE001 - best-effort recall
                    logger.debug("Scoped preference fetch failed: %s", e)
                    return []
                return [
                    {
                        "category": r["category"],
                        "preference": r["preference"],
                        "context": r["context"],
                        "confidence": r["confidence"],
                    }
                    for r in rows
                ]

        return _log_failures(_get(), "get_user_preferences", uid)

    # Entity graph is shared (not user-scoped) in 0.2.1 — reuse the library's
    # implementation rather than fake isolation it does not have. Its inner
    # _get_or_create_client is the broken user=... path, so wrap the library
    # tool: prime the library's _client_cache with a freshly built (correct)
    # client under the library's own key formula, delegate, then pop it. This
    # keeps the entity tool building fresh per call (same cross-loop reasoning
    # as _build_memory_client) and off the broken path.
    _lib_entity_graph = _create_get_entity_graph_tool(**config)
    _lib_cache_key = f"{uri}:{neo4j_user}:{neo4j_database}"

    @tool
    def get_entity_graph(
        entity_name: str,
        user_id: str,
        depth: int = 2,
        relationship_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get the relationship graph around an entity.

        Use this tool to understand how an entity connects to other
        entities (customers, projects, team members, issues, etc.).

        Args:
            entity_name: The name of the entity to explore.
            user_id: The user ID for context.
            depth: How many relationship hops to traverse (default: 2, max: 3).
            relationship_types: Optional list of relationship types to filter.

        Returns:
            A dictionary containing the entity and its relationship graph.
        """
        _lib_client_cache[_lib_cache_key] = _build_memory_client(config)
        try:
            return _lib_entity_graph(
                entity_name=entity_name,
                user_id=user_id,
                depth=depth,
                relationship_types=relationship_types,
            )
        finally:
            _lib_client_cache.pop(_lib_cache_key, None)

    return [search_context, add_memory, get_user_preferences, get_entity_graph]
