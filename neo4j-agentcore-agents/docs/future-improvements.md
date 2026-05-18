# Finance Agent Memory: Future Improvements

Tracks known limitations and follow-up work for the user-scoped Context Graph
memory added to the Strands variant (`common/memory.py`, `strands/runtime_app.py`,
`invoke_agent.py`).

## Resolved: memory never persisted (`user` vs `username` wheel bug)

### Explain it like I'm 5

Imagine a notebook where the agent writes down things to remember about
you. To open the notebook, the library fills out a tiny form. One field on
that form was labeled `user`, but the notebook only accepts a field labeled
`username` and throws away any form with a label it does not recognize. So
the notebook never opened. The agent acted like it was writing notes, but
every page stayed blank, and next time it had nothing to read back.

The fix: we now fill out that form ourselves with the correct `username`
label, so the notebook opens. Notes get saved, and the agent can read them
back later, even in a brand-new conversation.

### Simple summary

The vendored `neo4j_agent_memory` 0.2.1 wheel builds its database client
with `Neo4jConfig(user=...)`, but that model's field is `username` and it is
configured to reject unknown fields. Every memory client construction raised
`1 validation error for Neo4jConfig / user / Extra inputs are not
permitted`, so `add_memory`, `search_context`, and `get_entity_graph` all
failed silently from the model's point of view. The agent narrated success
("I'll store that") while nothing reached Neo4j.

`common/memory.py` now builds the `MemoryClient` itself in
`_build_memory_client`, passing `username`, and otherwise mirrors the
library's embedder/provider-string handling. It also primes the library's
own `_client_cache` under the same cache key, so the re-exported
`get_entity_graph` tool reuses the correctly built client instead of hitting
the broken path. The library's `_run_async` is reimplemented locally so that
private symbol is no longer a dependency.

### Why it was necessary

This was not a tuning or polish issue. It was a hard failure: the per-user
memory feature could never persist or recall a single fact. It was found by
the live verification in "Next steps" #1 below. The bug is internal to the
pinned wheel (a `user` vs `username` skew between
`integrations/strands/tools.py` and `config/settings.py`); our wrapper had
been passing the documented `neo4j_user` argument correctly.

### Verified

Deployed to AgentCore Runtime (`finance_strands`, us-west-2) and run via
`invoke_agent.py memory-demo --user-id demo-user --verify-neo4j`. Result:
**PASS**. Turn 2 recalled the preference in a new session, and the Neo4j
ground-truth query found the `:Message` scoped to `user_id="demo-user"` with
`Conversation.user_identifier` set and the `:User` node linked.

### Files added / changed

- **Changed `common/memory.py`**: removed the `_get_or_create_client` /
  `_run_async` imports; added `_build_memory_client`, `_run_async`,
  `_embedding_model_string`, and the `_CLIENT_CACHE` /
  `_DEFAULT_EMBEDDING_MODEL` / `_PROVIDER_PREFIXES` constants; the three
  scoped tools now call `_build_memory_client`; the entity-graph setup
  primes the cache. Module docstring updated to document the workaround.
- **Changed `future-improvements.md`**: this section, plus the two items
  below that the fix made stale.
- No new files. No change to `strands/runtime_app.py`, `strands/agent.sh`, or
  `invoke_agent.py`; the agent wiring and per-user Cypher were already
  correct.

## Known limitations

### Global vector index, then per-user filter

`search_context` issues a vector query against the global
`message_embedding_idx`, which returns a top-N across all tenants, and only
then filters to the calling `user_id`. To compensate it oversamples (up to
1000 candidates) before the filter. At demo scale this is fine. Under heavy
multi-tenant load a user's relevant messages could fall outside the candidate
window if other tenants' messages are more similar to the query. The fully
robust fix is a user-partitioned vector index, which is a library-level
change in `neo4j-agent-memory` beyond this workaround.

### `search_messages(session_id=...)` is unimplemented upstream

`neo4j_agent_memory` 0.2.1 documents a `session_id` filter on
`short_term.search_messages` but the method body never applies it. We had to
write custom Cypher to scope retrieval. If a future wheel implements that
parameter, revisit whether the custom query is still needed. Report this
upstream.

### Entity graph is not user-scoped

`get_entity_graph` is the library's implementation, re-exported unchanged.
Entity nodes are shared across all users in 0.2.1, so this tool can surface
entities derived from another tenant's conversations. Acceptable for the
finance demo because the entity tool is rarely the recall path, but it is a
real cross-tenant boundary that the message and preference tools do not have.

### Preferences are not written as `:Preference` nodes

`add_memory` stores a `:Message` and relies on the library's entity
extraction. It does not call `long_term.add_preference`, so
`get_user_preferences` returns results only if extraction happened to create
`:Preference` nodes. Durable preference capture is therefore best-effort.

### Reliance on private library symbols

After the `user`/`username` fix, `common/memory.py` no longer depends on
`_get_or_create_client` or `_run_async`. It still imports
`_create_get_entity_graph_tool` and writes into `_client_cache` (both from
`neo4j_agent_memory.integrations.strands.tools`) so the shared entity-graph
tool reuses our correctly built client. The wheel is pinned by exact
filename, so these are stable today. A version bump via
`scripts/vendor-memory.sh` can break them silently, and could also fix or
move the underlying `user`/`username` defect, which would make
`_build_memory_client` redundant. The module raises a pointed `ImportError`
if the symbols move, but a bump still requires re-checking this file.

### Runtime-verified (positive path only)

The Strands agent has been deployed to AgentCore Runtime and the
cross-session memory path verified end to end against live Neo4j (see
"Resolved" above): a preference stored in one session is recalled in another
under the same `user_id`, with the Neo4j ground-truth check passing. Not yet
done: the negative isolation test (store as user A, query as user B, assert
no leakage) in "Next steps" #2, and any load-scale validation.

## What still needs fixing

- `langgraph/agent.sh` carries the same wrong `# Finance Agent (LangGraph)`
  header that was corrected in `strands/agent.sh`. Both `agent.sh` files are
  copies that derive the variant at runtime; the duplication itself is a
  maintenance hazard worth collapsing into one shared script.
- `finance-agent/queries.txt` does not exist, so `invoke_agent.py load-test`
  exits with a clear error instead of running. Seed it with finance prompts
  if load testing the deployed agent matters.
- `verify_neo4j_persistence` matches on both literal tokens `energy` and
  `nvidia`. The agent paraphrases before calling `add_memory`, so a wording
  like "the chip maker" instead of "NVIDIA" yields a false FAIL. Loosen to
  either-token matching or match on the stored preference category.
- Oversample bounds (`_CANDIDATE_MULTIPLIER`, `_MIN_CANDIDATES`,
  `_MAX_CANDIDATES`) and `min_score` defaults are untuned guesses. Calibrate
  against real recall once there is live data.

## Next steps

1. Deploy and verify end to end:
   - `strands/agent.sh deploy`
   - `strands/agent.sh memory-demo demo-user`
   - `uv run python invoke_agent.py memory-demo --user-id demo-user --verify-neo4j`
   - Confirm a PASS and that a second `--user-id other-user` run does not
     recall the first user's memory.
2. Add a negative isolation test: store memory as user A, query as user B,
   assert no leakage. This is the test that actually proves the fix.
3. Write durable preferences explicitly. Have `add_memory` (or a new tool)
   call `long_term.add_preference(user_identifier=...)` so
   `get_user_preferences` is reliable rather than extraction-dependent.
4. Upstream contributions to `neo4j-agent-memory`:
   - Implement `search_messages(session_id=...)`.
   - User-scope the Strands `context_graph_tools` so the workaround can be
     dropped.
   - User-partition or user-filter the message vector search to remove the
     oversample heuristic.
5. After any `scripts/vendor-memory.sh` bump, re-validate the private-symbol
   imports in `common/memory.py` and re-run the deploy verification.
6. Consolidate the two `agent.sh` copies into one shared script and fix the
   `langgraph/agent.sh` header.
