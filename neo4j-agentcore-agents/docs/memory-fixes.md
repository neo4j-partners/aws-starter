# Finance Agent Memory: What Broke and How We Fixed It

## ELI5 (explain it like I'm 5)

We gave the finance agent a "memory" so it can remember things you tell it
(like "I prefer low-risk energy stocks") and recall them in a later chat.

The memory never actually saved anything. Every time the agent tried to
remember something, it quietly failed and pretended it worked. The agent
even said "Got it, I noted that!" but nothing was written down.

The cause was tiny. The memory library we use has a one-word typo deep
inside it. It tried to fill out a form field called `user`, but the form
only accepts a field called `username`, and the form rejects any field it
does not recognize. So the form was thrown away every single time, before
anything could be saved. No error reached our logs because the failure was
swallowed and the agent talked over it.

We could not just edit the library (the typo is in someone else's code that
we only borrow). So instead we wrote our own small piece that fills out the
form correctly with `username`, and told the library to use ours.

## Why this was hard to find

The failure was invisible:

1. The memory tools caught their own errors and returned a vague string to
   the model instead of crashing.
2. The model (Claude Haiku) read that vague string and cheerfully said
   "Got it!" anyway, so from the outside it looked like it worked.
3. Nothing was logged at a level that reached CloudWatch.

We found it by adding a ground-truth check (`invoke_agent.py --verify-neo4j`)
that queries the database directly instead of trusting the agent's words,
and by adding logging that surfaces the real exception with a traceback.
That exposed the actual error:

```
pydantic_core.ValidationError: 1 validation error for Neo4jConfig
  Extra inputs are not permitted [type=extra_forbidden, input_value='neo4j']
```

at `neo4j_agent_memory/integrations/strands/tools.py:122`, where the
library calls `Neo4jConfig(user=...)` but the model's field is `username`
and the model is configured with `extra="forbid"`.

## The decision

Three fix options were considered:

1. **Patch the upstream library source and re-vendor the wheel.** Smallest
   change, but edits a separate repository (`neo4j-labs/agent-memory`) that
   this project only borrows from.
2. **Fix it inside our own wrapper (chosen).** Self-contained. No external
   repo edits. We stop calling the library's broken helper and build the
   client ourselves with the correct field name.
3. **Monkeypatch the library at import time.** Fewest lines but fragile and
   tightly coupled to library internals.

**We chose option 2: fix it in our wrapper only.**

Reasoning: the fix lives entirely in this project, does not depend on the
upstream `neo4j-labs/agent-memory` checkout being present or patched, and
does not silently diverge from a third-party repo. The cost is that our
wrapper now duplicates roughly 30 lines of the library's client-building
logic (provider-string normalization and Bedrock embedding kwargs), which
we keep in sync with the vendored wheel and document inline.

## What the fix does, concretely

In `common/memory.py` we added `_build_memory_client(config)`. It:

- Builds `Neo4jConfig(uri=..., username=..., password=..., database=...)`
  with the correct `username` field, so the form is accepted.
- Mirrors the library's embedding-provider setup (Bedrock region/profile
  kwargs, provider-string normalization) so the embedder is built
  identically. Only the broken Neo4j config construction is replaced.
- Caches the built client in the library's own private `_client_cache`
  under the exact same cache-key formula the library uses. This matters
  because the `get_entity_graph` tool is still the library's own and it
  calls the broken helper internally. Priming the cache means it gets a
  cache hit and reuses our correctly-built client, so it never reaches
  the broken code path.

We also reimplemented the library's `_run_async` locally (so we no longer
depend on that private symbol) and added `_log_failures`, which runs each
memory tool's coroutine, logs any exception with a full traceback, and
re-raises. This is a permanent quality improvement: it is what made the
original bug visible and will surface any future memory failure instead of
letting the agent talk over it.

## Files changed

| File | Change |
|---|---|
| `common/memory.py` | Core fix. Added `_build_memory_client` (correct `username` field, primes the library cache so `get_entity_graph` reuses it), local `_run_async`, and `_log_failures` (traceback logging + re-raise) wrapping `search_context`, `add_memory`, `get_user_preferences`. |
| `strands/runtime_app.py` | Switched to `common.memory.user_scoped_context_graph_tools` for genuinely per-user memory. Raised the `neo4j_agent_memory` logger to DEBUG so library-level failures reach CloudWatch. |
| `invoke_agent.py` | Added `--verify-neo4j`: after the memory demo, queries Neo4j directly for the persisted `:Message` nodes and prints an honest pass/fail, instead of trusting the agent's wording. This is the ground-truth check that exposed the bug. |
| `pyproject.toml` | Declared `pyyaml` explicitly (used by `invoke_agent.py`); added the numpy ARM64 manylinux cross-compile sensitivity note. |

## A second bug, found only after the first fix worked

Once memory actually saved, a new failure showed up on the *next* turn:
recall crashed with

```
RuntimeError: Task ... got Future <Future pending> attached to a
different loop  (common/memory.py, get_user_preferences._get())
```

ELI5: each memory tool call runs on its own little "engine" (an event
loop). The first save built a database connection and glued it to engine
#1. We then cached that connection and handed it to the next call, which
runs on engine #2. The connection only works with the engine it was glued
to, so the second call blew up.

Why it only appeared now: before the username fix nothing ever got far
enough to build and cache a working connection, so the cross-engine reuse
was never reached.

### The fix (option 1, chosen and approved)

Stop caching the connection. `_build_memory_client` now builds a fresh
`MemoryClient` on every tool call and the tool closes it (`async with`)
when done, so each connection is glued to exactly the engine that uses it.
The re-exported `get_entity_graph` (whose library internals still call the
broken `user=...` helper) is now wrapped: before each call the wrapper
primes the library's own client cache with a freshly built, correct client
under the library's key, delegates, then pops it. That keeps the entity
tool both fresh-per-call and off the broken path.

Considered but rejected: keeping one cached client but making it
loop-agnostic (more code, fights the driver's design); running all tool
calls on one shared loop (large change to how Strands invokes sync tools).
Option 1 is the smallest change and matches how the tools already scope
their client (open, use once, close).

| File | Change |
|---|---|
| `common/memory.py` | Removed the module-level `_CLIENT_CACHE` and the library-cache priming from `_build_memory_client` (now builds fresh per call). Wrapped `get_entity_graph` so it primes/pops the library cache per call instead of relying on a persistent prime. Updated the module docstring. |

## Status

- Both root causes confirmed and fixed in `common/memory.py`.
- Deployed to the live AgentCore runtime (`finance_strands`) and verified
  end-to-end: `uv run python invoke_agent.py memory-demo
  --user-id loop-fix-eve --verify-neo4j` returns **PASS** — the preference
  persisted to Neo4j scoped to the user (`Conversation.user_identifier`
  set, `:User` linked) **and** Turn 2 recalled it without being re-told,
  confirming cross-session recall now works.
