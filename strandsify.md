# Strandsify: dual-framework agents over a shared core

> Note: since this proposal was written, `fleet-agent` has moved to
> `fleet-agent-demo/agent/` (alongside the GraphRAG pipeline that populates
> its graph). Path references to `neo4j-agentcore-agents/fleet-agent` below
> reflect the original layout and are kept as a historical record.

## Proposal

### ELI5

Two agents in `neo4j-agentcore-agents/` (`finance-agent` and `fleet-agent`)
are written for LangGraph only. We want each one to exist in two flavors —
LangGraph and Strands — sitting side by side so they can be compared and
deployed independently. The credential, config, and schema plumbing they share
gets pulled into one small `common/` package per agent so it is written once.
The Strands flavor is written the Strands way (its own idioms for MCP, model,
and streaming), not a line-by-line copy of the LangGraph code. Everything is
installed and run through `uv`.

### Why

- `finance-agent` and `fleet-agent` are LangGraph-only today. There is no
  Strands variant to compare framework behavior or deploy as an alternative.
- The credential loading, OAuth2 token refresh, model/config, and (for
  `fleet-agent`) schema fetch logic is duplicated. `finance-agent` already
  factored part of this into `agent_common.py`; `fleet-agent`'s
  `aircraft-agent.py` is a monolith with the same logic inlined. Evidence: both
  agents contain the same `load_credentials` / `check_token_expiry` /
  `refresh_token` shape and the same `MultiServerMCPClient` Gateway wiring.
- A naive Strands port carried over from the notebook would keep the
  module-load-once token and reused MCP context, which expires the Bearer token
  on a long-running runtime. The Strands variant must use per-request MCP
  context entry with a fresh token from the transport factory.

### Scope

- `neo4j-agentcore-agents/finance-agent/`
- `neo4j-agentcore-agents/fleet-agent/`
- `neo4j-agentcore-agents/sync-credentials.sh` and `local_test.py` (path
  references only, if needed)
- Repository `CLAUDE.md` (command paths for the two agents)

### Removed

- `finance-agent/agent_common.py` as a flat module (its contents move into the
  `common/` package).
- `fleet-agent/aircraft-agent.py` as a monolith (decomposed into `common/` plus
  `langgraph/agent.py`).
- Any `pip`/`requirements.txt`-style install path in the touched agents (uv
  only).

### Fixed

- Credential path resolution: today it is anchored to the entrypoint file's
  directory; it must resolve to the agent root so it keeps working when
  entrypoints move into `langgraph/` and `strands/`.
- Duplicated credential/token/schema logic becomes one `common/` package per
  agent.
- `fleet-agent` LangGraph behavior (schema caching, token streaming, ADOT
  tracing, load-test harness) is preserved exactly, just sourced from
  `common/`.

### Added

- Per agent: a `common/` package (`config`, `credentials`, and for
  `fleet-agent` a framework-agnostic `schema` fetch/cache).
- Per agent: `langgraph/` and `strands/` directories, each with `agent.py`
  (AgentCore entrypoint), `simple-agent.py` (local CLI), `Dockerfile`, and
  `agent.sh`.
- A single `pyproject.toml` + `uv.lock` per agent declaring `common` as an
  installed package and carrying both frameworks' dependencies.
- A Strands-native entrypoint: module-level `BedrockModel` and
  `MCPClient(transport_factory)`; per-request `with mcp_client:` →
  `list_tools_sync()` → `Agent(...)` → `async for ... in agent.stream_async()`;
  fresh OAuth2 token resolved inside the transport factory on every context
  entry.

### Deliberately not doing

- Not touching `orchestrator-agent/` — the request is finance + fleet only.
- Not merging `langgraph-neo4j-mcp-agent/` into this tree — it is the
  standalone + SageMaker-notebook story and stays separate.
- Not changing the Neo4j MCP server, the Gateway, or credential file format.
- Not changing LangGraph agent behavior or model IDs — the LangGraph variant is
  a move + import swap, not a rewrite.
- Not adding session/memory persistence to the Strands variant — it is
  stateless per request like the LangGraph one.
- Not renaming `simple-agent.py` (keeps the hyphenated script name; only its
  directory changes).

### Decisions

- **Layout: framework subdirs per agent over a shared `common/`.** Chosen so
  each agent's domain stays together with framework as the inner axis.
  Dropped: sibling `-strands` dirs (more duplication); a new top-level
  `strands-neo4j-mcp-agent/` (splits deployable agents across two trees).
- **One uv project per agent, shared deps.** Single `pyproject.toml` +
  `uv.lock` + `.mcp-credentials.json` at the agent root; both frameworks'
  deps coexist (`fleet-agent` already ships `strands-agents`). Dropped:
  separate project per variant (two `uv sync`s, more files).
- **`common` is an installed package, not a `sys.path` insert.** Directories
  named `langgraph/` and `strands/` would shadow the installed `langgraph` and
  `strands` packages if the agent root were on `sys.path`. Declaring `common`
  as a package installed by `uv sync` avoids any `sys.path` manipulation and
  keeps the chosen directory names. Dropped: `sys.path.insert` of the agent
  root (package shadowing risk).
- **Strands variant is native, not a port.** Per-request MCP context entry,
  fresh token in the transport factory, `stream_async()` in the async
  entrypoint, schema injected via `system_prompt` at `Agent(...)`
  construction. Reasoning: the notebook's module-load-once token + reused
  context expires on a long-running runtime. Dropped: mechanical translation
  of the LangGraph control flow.
- **agent.sh + Dockerfile for all four variants.** Consistent deploy UX;
  `finance-agent` gains tooling it did not have. Dropped: Strands-only or
  docs-only tooling for finance-agent.
- **uv everywhere.** All variants, `agent.sh`, and `Dockerfile`s install and
  run via uv (`uv sync`, `uv run`); no pip/requirements path. The existing
  `fleet-agent` Dockerfile already does this and is the pattern to follow.

### Where to look

- `finance-agent/agent_common.py` — the already-factored shared logic; the
  template for the `common/` package contents.
- `fleet-agent/aircraft-agent.py` — the monolith to decompose; contains the
  schema fetch/cache and streaming patterns to preserve in the LangGraph
  variant.
- `fleet-agent/agent.sh` and `fleet-agent/Dockerfile` — the uv-based deploy
  pattern to replicate for every variant.
- `fleet-agent/invoke_agent.py`, `queries.txt` — stay at the agent root,
  shared by both variants' load-test path.
- `neo4j-agentcore-agents/sync-credentials.sh`, `local_test.py` — verify
  credential paths still resolve to the agent root.
- `CLAUDE.md` — the `cd finance-agent` / `cd fleet-agent` command blocks need
  variant subpaths.

### Done when

- Each agent has `common/`, `langgraph/`, and `strands/` with the files listed
  in **Added**, and a single root `pyproject.toml` + `uv.lock`.
- `uv sync` in each agent root installs `common` as an importable package; no
  `sys.path` manipulation exists in any entrypoint.
- Both LangGraph variants run locally and produce the same behavior as before
  the split (finance: ReAct over Gateway tools; fleet: schema-cached, streamed,
  load-testable).
- Both Strands variants run locally: per-request MCP context, token refreshed
  via the transport factory, streamed response from `stream_async()`.
- `agent.sh` in all four variants supports the documented lifecycle
  (start/test/configure/deploy/status/invoke-cloud/destroy) via uv, and each
  variant has a uv-based ARM64 `Dockerfile`.
- Credential resolution works with entrypoints in subdirectories;
  `sync-credentials.sh` still populates each agent root.
- `CLAUDE.md` command blocks reference the new variant paths.
- No `requirements.txt`/pip install path remains in either agent.

## Execution plan

### Goal

`finance-agent` and `fleet-agent` each expose a LangGraph and a Strands variant
over a shared `common/` package, all uv-managed and independently deployable to
AgentCore Runtime, with LangGraph behavior unchanged and Strands written
natively.

### Assumptions

- The Neo4j MCP server, Gateway, and `.mcp-credentials.json` format are stable.
- `strands-agents` / `strands-agents-tools` are installable alongside the
  existing LangGraph stack in one environment.
- AgentCore deploy of a subdirectory entrypoint works when run from the agent
  root with `common` installed (`agentcore configure -e <variant>/agent.py`).
- Local validation (start + test request) is sufficient; full cloud deploy is
  not required to call a phase complete unless the user asks.

### Risks

- **Package shadowing** if the agent root ever lands on `sys.path` — mitigated
  by installing `common` as a package and never inserting the root.
- **Credential path regressions** when entrypoints move into subdirs —
  validated explicitly in Phase 1.
- **Strands lifecycle correctness** (token expiry on long-running runtime) —
  the native pattern (per-request context + factory token) is the mitigation;
  verify the factory is invoked per request.
- **fleet-agent decomposition drift** — LangGraph behavior must match
  pre-split; validated by a before/after request comparison.
- **agentcore multi-variant config** — two deployable entrypoints per agent
  root may need distinct agent names in `.bedrock_agentcore.yaml`.

### Phase checklist

#### Phase 1 — finance-agent skeleton + shared core

Outcome: `finance-agent` has the new layout, `common/` package, single uv
project; nothing framework-specific moved yet.

- [ ] Create `finance-agent/common/` (`__init__.py`, `config.py`,
      `credentials.py`) from `agent_common.py`, with credential path anchored
      to the agent root.
- [ ] Author single `finance-agent/pyproject.toml` declaring `common` as a
      package and carrying LangGraph + Strands deps; regenerate `uv.lock`.
- [ ] Remove `agent_common.py` once `common/` supersedes it.
- [ ] Validate: `uv sync` installs `common`; a throwaway `from common...`
      import resolves; no `sys.path` inserts.

#### Phase 2 — finance-agent LangGraph variant

Outcome: existing finance behavior preserved under `langgraph/`.

- [ ] Move `agent.py` and `simple-agent.py` into `finance-agent/langgraph/`,
      swapping inline logic for `from common import ...`.
- [ ] Add `finance-agent/langgraph/Dockerfile` and `agent.sh` (uv-based,
      fleet-agent pattern, distinct agent name).
- [ ] Validate: local start + test request returns a correct ReAct answer
      over Gateway tools; credential refresh path exercised.

#### Phase 3 — finance-agent Strands variant (native)

Outcome: a Strands-native finance agent deployable the same way.

- [ ] Add `finance-agent/strands/agent.py` (module-level `BedrockModel` +
      `MCPClient(factory)`; per-request context; `stream_async()` in async
      entrypoint; token from `common.get_active_credentials()` inside the
      factory).
- [ ] Add `finance-agent/strands/simple-agent.py` (Strands CLI), `Dockerfile`,
      `agent.sh`.
- [ ] Validate: local start + test request; confirm the transport factory runs
      per request and a refreshed token is used.

#### Phase 4 — fleet-agent skeleton + shared core (incl. schema)

Outcome: `fleet-agent` decomposed into the new layout with a
framework-agnostic schema module.

- [ ] Create `fleet-agent/common/` (`config`, `credentials`, `schema` —
      raw-MCP schema fetch + cache extracted from `aircraft-agent.py`).
- [ ] Single `fleet-agent/pyproject.toml` (uv, both frameworks, `common`
      package); regenerate `uv.lock`; keep `invoke_agent.py` + `queries.txt`
      at agent root.
- [ ] Validate: `uv sync`; `common` imports; schema fetch helper callable in
      isolation.

#### Phase 5 — fleet-agent LangGraph variant

Outcome: pre-split fleet behavior preserved exactly under `langgraph/`.

- [ ] Build `fleet-agent/langgraph/agent.py` + `simple-agent.py` from the
      decomposed monolith (schema-cached system prompt, token streaming, ADOT).
- [ ] Add `langgraph/Dockerfile` + `agent.sh`; wire `load-test` to the
      root-level `invoke_agent.py`.
- [ ] Validate: before/after request comparison shows unchanged behavior;
      `agent.sh load-test` works.
- [ ] Retire `aircraft-agent.py`.

#### Phase 6 — fleet-agent Strands variant (native)

Outcome: Strands-native fleet agent with schema via system prompt.

- [ ] Add `fleet-agent/strands/agent.py` (native pattern; cached schema
      injected into `system_prompt` at `Agent(...)` construction) +
      `simple-agent.py` + `Dockerfile` + `agent.sh`.
- [ ] Validate: local start + test request; schema present in prompt; token
      refresh via factory.

#### Phase 7 — repo wiring + docs

Outcome: tooling and docs reflect the new structure.

- [ ] Update `sync-credentials.sh` / `local_test.py` path references if needed
      (creds still land at each agent root).
- [ ] Update `CLAUDE.md` command blocks for finance + fleet with variant
      subpaths.
- [ ] Confirm no `requirements.txt`/pip path remains in either agent.
- [ ] Validate: documented commands run as written from a clean checkout.

### Completion criteria

All **Done when** items hold; each of the four variants starts locally and
returns a correct response to a test query; LangGraph variants match pre-split
behavior; Strands variants demonstrate per-request MCP context with a
factory-refreshed token; `CLAUDE.md` and credential tooling reflect the new
paths.

## Status

| Phase | Status |
|-------|--------|
| 1 — finance-agent skeleton + shared core | Complete |
| 2 — finance-agent LangGraph variant | Complete |
| 3 — finance-agent Strands variant (native) | Complete |
| 4 — fleet-agent skeleton + shared core | Complete |
| 5 — fleet-agent LangGraph variant | Complete |
| 6 — fleet-agent Strands variant (native) | Complete |
| 7 — repo wiring + docs | Complete |
