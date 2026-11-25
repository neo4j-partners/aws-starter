# Custom code that native libraries could replace

This review covers `demos/aircraft-fleet` on simplify-fleet at 859e566. It also covers 8B at 24d1007 and its follow-up 35fb475, 8C at 9579344, and the 8A worktree as it stands uncommitted. It looks for custom code that the Strands Agents SDK, neo4j-graphrag, or another locked library already does natively.

## Locked versions checked

Every claim below was checked against the source in each project's `.venv`. Each venv matches its `uv.lock`.

| Package | Locked | Released | Latest | Notes |
|---|---|---|---|---|
| neo4j-graphrag | 1.24.0 | 2026-11-10 | 1.24.0 | Pipeline and supervisor agent |
| strands-agents | 1.65.0 | 2026-11-13 | 1.66.0, released 2026-11-23 | 1.66.0 fails the 1-week policy until 2026-11-30 |
| bedrock-agentcore | 1.26.1 | 2026-11-18 | 1.27.0, released 2026-11-20 | 1.27.0 fails the policy until 2026-11-27 |
| neo4j-agent-memory | 0.8.0+fleet.9 | 0.8.0 released 2026-10-22 | fork | Fleet fork |
| neo4j | 6.4.1 | | | |
| mcp | 1.30.0 | | | |
| boto3 | 1.44.7 | | | Pipeline |
| httpx | 0.28.1 | | | Supervisor client and UI |

**Upgrade status:** No recommendation needs an upgrade. Every replacement below works on the locked versions.

`strands-agents-tools` is not a dependency. The `anthropic` package is an optional pipeline extra and is not installed in the pipeline venv.

## Summary

| # | File and symbol | What it does | Native replacement | Effort | Risk | Recommendation |
|---|---|---|---|---|---|---|
| 1 | `supervisor-agent/fleet_supervisor/client/transport.py` `iter_events`, `invoke_deployed`; `ui/server.py` `supervisor_stream` | Hand-written SSE parser over boto3 and httpx bytes. The UI repeats the invoke code. | `bedrock_agentcore.runtime.iter_events(response)` for the boto3 path | S | Low | Replace on the cloud path. Dedupe the UI onto `transport`. |
| 2 | `core/graph/tools.py` error strings; `core/events.py` `GRAPH_ERROR_PREFIXES` | Tools return failure text with `status: success`. The mapper detects failure by text prefix. | Return a `ToolResult` dict with `"status": "error"` from the `@tool` function | S | Medium | Simplify |
| 3 | `pipeline/.../bedrock_structured.py` `StructuredBedrockLLM` | Structured extraction through an `emit_graph` tool, `toolChoice: auto`, and a retry when no tool is called | Converse `outputConfig.textFormat` with a JSON schema | M | Medium | Simplify, behind a live test |
| 4 | `pipeline/.../agent_samples.py` `_create_llm_client`, Bedrock branch | Raw boto3 `converse` call that picks the first text block | `neo4j_graphrag.llm.BedrockLLM.invoke(...)` | S | Low | Optional simplify |
| 5 | `core/memory.py` `_Shared`, `_Open`, `password_rejected`; `server.py` `_build_agent` retry | Refcounted shared memory client, retired and rebuilt on a password rotation | An `auth_manager` option on the fork's `Neo4jConfig`, fed `RotatingLoginAuthManager` | L | Medium | Keep now. Simplify later through the fork. |
| 6 | `pipeline/.../anthropic_effort.py` `EffortAnthropicLLM` | Adds effort to `AnthropicLLM` and skips thinking blocks | None in 1.24.0 | S to delete | Low | Keep, or delete if the Anthropic provider is dropped |
| 7 | `core/graph/text2cypher.py` `BoundedText2CypherRetriever` | Copy of `get_search_results` with a query timeout and a row cap | None in 1.24.0 | | | Keep |
| 8 | `core/graph/retrieval.py` `RotatingLoginAuthManager`, `retry_on_rotated_login` | Auth manager that reloads the secret once per rejection | `neo4j.auth_management.AuthManagers.basic` does not fit | | | Keep |
| 9 | `core/agents.py` `SpecialistTool` | Builds a fresh specialist `Agent` for each call | `Agent.as_tool` locks per agent | | | Keep |
| 10 | `core/tool_stream.py` `_stream_result`, `observe_tool_results` | Streams each tool result before the turn ends | Already the native middleware hook | | | Keep |
| 11 | `core/events.py` `EventMapper` | Maps Strands events to the client event protocol | AG-UI, which needs a new dependency | | | Keep |
| 12 | `pipeline/.../pipeline.py` `ContextPrependingSplitter` | Prepends document and section context to each chunk | None in 1.24.0 | | | Keep |
| 13 | `pipeline/.../pipeline.py` `DimensionAwareOpenAIEmbeddings` | Passes `dimensions` on every OpenAI embed call | None in 1.24.0 | | | Keep |
| 14 | `pipeline/.../pipeline.py` `EXTRACTION_PROMPT` | Custom extraction prompt | Already the native `prompt_template` hook | | | Keep. 8A and 8B already shrink it. |
| 15 | `core/graph/retrieval.py` `fulltext_query`, type filter pool | Escapes Lucene input and filters hybrid results by type | `HybridRetriever` takes no filters and does not escape | | | Keep |
| 16 | `pipeline/.../agent_samples.py` `graph_schema`, `_extract_cypher`, `_run_text2cypher`, `_run_similarity_search` | Simulates the Aura Agent for the demo | `get_schema`, `extract_cypher`, `Text2CypherRetriever`, `VectorRetriever` | | | Keep |
| 17 | Domain logic: `link_to_existing_graph`, 8B `link_limits_to_chunks` and `limit_sources`, 8A `generator/limits.py`, `schema.py` constraint helpers | Fleet-specific Cypher, the limit generator and constraint setup | None | | | Keep |

## Findings to act on

### 1. Use the AgentCore SSE reader on the cloud path

**Code:**
- `client/transport.py` `iter_events(chunks: Iterable[bytes])` decodes UTF-8 incrementally, splits on `"\n\n"`, strips `"data: "`, and drops events that are not JSON objects.
- `invoke_deployed` feeds it boto3's `response["response"].iter_chunks()`. `invoke_local` feeds it httpx's `response.iter_bytes()`.
- `ui/server.py` `supervisor_stream` repeats both invoke paths. It imports only `READ_TIMEOUT_S` and `iter_events` from `transport`.

**Native replacement:** bedrock-agentcore 1.26.1 exports `bedrock_agentcore.runtime.iter_events(response)`. It is defined in `bedrock_agentcore/runtime/streaming.py:22` and parses with `bedrock_agentcore/_utils/sse.py` `SSEParser`.

**Why it is better:**
- `SSEParser` follows the SSE spec. It accepts CRLF, CR and LF line endings, and it joins multi-line `data:` fields. The custom parser handles only LF and a single `data:` line. Today the server emits one-line LF events, so this is a robustness gain, not a live bug fix.
- The library reads `read1(65536)` from the raw stream, so each event is yielded as soon as it arrives. botocore's `iter_chunks()` reads fixed-size blocks and can hold events back until a block fills. That can bunch tool events in the CLI and the UI.
- It closes the response body when the stream ends.

**Limits:**
- It takes the boto3 `invoke_agent_runtime` response, not an httpx response. `SSEParser` and its helpers are private, so the local httpx path should keep a small parser.
- It yields a `str` when the data is not JSON. The caller must keep the current "dict events only" filter.

**Version:** Works on 1.26.1. No upgrade.

**Recommendation:** Replace the cloud path with `runtime.iter_events`. Keep the custom parser for the local path, or narrow it to that path. Move `ui/server.py` onto the `transport` invoke helpers so there is one implementation of each path. Effort S, low risk. The existing transport tests cover the local path. The cloud path needs a test with a fake `_raw_stream`.

### 2. Return tool errors as an error status

**Code:**
- `core/graph/tools.py` `graph_query_tool` and `vector_search_tool` always return a plain `str`. On failure they return `QUERY_ERROR_PREFIX` text, `TIMEOUT_RESULT`, `UNAVAILABLE_RESULT`, `DATABASE_ERROR_RESULT`, `QUERY_FAILED_RESULT` or `SEARCH_FAILED_RESULT`.
- Strands wraps every plain return as `status: "success"`.
- `core/events.py` `EventMapper` then recognizes failures by matching `GRAPH_ERROR_PREFIXES` against the result text.

**Native replacement:** The Strands decorator passes a returned dict through as the tool result when it has both `"status"` and `"content"`. See `strands/tools/decorator.py:689` `_wrap_tool_result`. A tool can return `{"status": "error", "content": [{"text": TIMEOUT_RESULT}]}`.

**Why it is better:**
- The failure becomes structured data, not a string convention shared between two files.
- `EventMapper` can read `status` and drop `GRAPH_ERROR_PREFIXES`.
- Traces and the Strands tool metrics record the call as an error.

**Risks:**
- The model now sees an error status, which can change how a specialist retries or words its answer. A run of the routing tests and a live check are needed.
- `tests/test_tools.py` and `tests/test_ui_trace.py` use these constants and must change.

**Version:** Works on 1.65.0. No upgrade.

**Recommendation:** Simplify. Keep the message constants, because the model and the tests read them. Effort S, medium risk because of prompt behavior.

### 3. Move StructuredBedrockLLM to native structured output

**Code:** `pipeline/src/populate_aircraft_db/bedrock_structured.py` `StructuredBedrockLLM(BedrockLLM)`:
- It sets `supports_structured_output = True`, so `SimpleKGPipeline` asks for `response_format=Neo4jGraph`.
- It turns the schema into one `_RawSchemaTool` named `emit_graph`. Sonnet 5.5 rejects a forced `toolChoice`, so it offers the tool with `auto` and instructs the model to call it.
- It retries up to twice when the reply has no tool call or fails validation. It counts misses in `miss_count` behind a lock.
- `_build_converse_kwargs` forwards `additional_request_fields` for thinking and effort.

**Native replacement:** Bedrock Converse structured outputs, `outputConfig.textFormat` with type `json_schema`. The [structured output guide](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html) documents it. The [Sonnet 5.5 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html) lists support for it. The locked botocore accepts the field.

**What goes away:**
- The `emit_graph` tool, the tool instruction, and the "no tool call" retry. Constrained decoding always returns schema-shaped JSON.
- Most of `miss_count`. A miss would mean only a `max_tokens` cut-off.

**What stays:**
- The subclass itself. neo4j-graphrag 1.24.0 `BedrockLLM.__invoke_v2` and `__ainvoke_v2` raise "BedrockLLM does not currently support structured output" at `neo4j_graphrag/llm/bedrock_llm.py:208` and `:246`.
- The `additional_request_fields` forwarding.

**Risks:**
- Every object must set `additionalProperties: false`, and recursion is unsupported. `Neo4jGraph` has open-map `properties` fields. neo4j-graphrag converts them for Anthropic with `_to_anthropic_schema` and `_restore_open_maps` in `anthropic_llm.py`, but both are private. The pipeline would need its own copy of that conversion.
- A schema may hold at most 12 optional and 16 union-typed properties. The generated schema must be measured against those limits.
- The first compile of a schema can take about 90 seconds, so the read timeout must be at least 120 seconds. Bedrock caches the grammar for 24 hours.
- Structured outputs cannot be combined with citations. The pipeline does not use citations.
- Strands has `to_native_output_schema` in `strands/models/bedrock.py`, near `_native_output_config` at line 118. It does not convert open maps, so it is not a drop-in.

**Version:** Works on the locked boto3 and neo4j-graphrag 1.24.0. No upgrade.

**Recommendation:** Simplify, behind a live extraction test on a few chunks that compares graph counts with the current path. This needs a Bedrock call, so it is a decision for tuq. Effort M, medium risk.

**Measured and dropped (simplify-11 item 7):** The change was built on `simplify-11-structured-output` (e904fb9) and compared live on 4 chunks of `MAINTENANCE_A321neo.md`. Extraction quality matched, with the same label sets and no misses on either path. The new path was about 2x slower per chunk, 20 s against 10 s on the largest chunk. It also produced 10-30% more output tokens, from the key/value encoding of open maps. The current `StructuredBedrockLLM` stays. The branch is kept unmerged for reference.

### 4. Use BedrockLLM for the Aura Agent simulation chat

**Code:** `pipeline/.../agent_samples.py` `_create_llm_client` builds a raw boto3 `converse` call with `system`, `maxTokens`, and `additionalModelRequestFields` for thinking and effort. It returns the first text block. It also has OpenAI and Anthropic branches.

**Native replacement:** `neo4j_graphrag.llm.BedrockLLM.invoke(list[LLMMessage], additionalModelRequestFields=...)`. In 1.24.0 the sync `invoke` merges its keyword arguments into `_build_converse_kwargs`. `_parse_response` joins all text blocks and skips thinking blocks.

**Limits:** The async `__ainvoke_v2` drops the keyword arguments, which is a library bug. The sample is synchronous, so it is not affected.

**Version:** Works on 1.24.0.

**Recommendation:** Optional. The gain is about 15 lines and one fewer response parser. Effort S, low risk. Do it only if `agent_samples.py` is touched for another reason.

### 5. Memory lifecycle depends on a fork hook

**Code:** `core/memory.py` is 531 lines. It builds `MemorySettings`, `Neo4jConfig` and `BedrockProvider`. Most of the file is lifecycle:
- `_Build` dedup and `forget_memory_settings`
- `password_rejected`
- The `_Shared` and `_Open` acquire, release and retire refcounting
- `CLIENT_CLOSE_SECONDS`

`server.py` `_build_agent` retries once when the password is rejected.

**Why it exists:** neo4j-agent-memory builds its driver with a static `auth=(username, password)` at `neo4j_agent_memory/graph/client.py:77`. `Neo4jConfig` has no auth manager option. When the Secrets Manager password rotates, the only fix is to retire the client and build a new one, while in-flight sessions keep the old one. `SharedMemory` in `integrations/strands/shared.py` has no refcounting and no rotation.

**Possible replacement:** The fleet fork could add an optional `auth_manager` to `Neo4jConfig` and pass it to the driver. The supervisor would then pass its `RotatingLoginAuthManager`. That could remove `_Shared`, `_Open`, retire, `password_rejected`, and the retry in `_build_agent`.

**Recommendation:** Keep for now. The change is in the fork, so it is a dependency change for tuq to decide. Effort L, medium risk. The memory tests and a rotation test would both need updates.

## Honest keep cases

Each item lists what would have to change before the custom code could go.

**EffortAnthropicLLM.** neo4j-graphrag 1.24.0 `AnthropicLLM` has no effort setting, and it reads `content[0]`, which is a thinking block when thinking is on. The class fixes both. It has no tests. It could go if the library adds effort and skips thinking blocks. It could also go if the pipeline drops the Anthropic provider, which is a design question for tuq.

**BoundedText2CypherRetriever.** `Text2CypherRetriever.get_search_results` already runs an `EXPLAIN` read-only check with READ routing, at `neo4j_graphrag/retrievers/text2cypher.py:221-237`. It sets no query timeout and no row cap. The subclass adds `neo4j.Query(timeout=)` and `result_transformer_` with `fetch(max_rows + 1)`. It could go if upstream adds a timeout or a row limit. A signature-guard test already catches upstream changes to the copied method.

**RotatingLoginAuthManager and retry_on_rotated_login.** The docstring already records why `AuthManagers.basic` does not fit. `basic` retries on every rejection, which costs about 30 seconds per query with a wrong password. neo4j 6.4.1 also does not consult the manager for an `AuthError` on a new connection. These could go if the driver fixes both behaviors.

**SpecialistTool.** Strands 1.65.0 `Agent.as_tool` holds an unconditional `threading.Lock` in `strands/agent/_agent_as_tool.py`. A second concurrent call returns "Agent '...' is already processing a request", at line 213. `Agent(concurrent_invocation_mode=...)` controls the agent lock, not this one. The supervisor runs tool calls concurrently and can call the same specialist twice in one turn, so it needs a fresh agent per call. `delegate=True` installs the `_agent_delegation.py` plugin, which is not an agent factory. It could go if Strands adds a per-call factory or a concurrent `as_tool`.

**tool_stream middleware.** `ToolResultEvent.is_callback_event` is False in `strands/types/_events.py`, so `stream_async` never yields tool results. `ToolResultMessageEvent` arrives only after every tool in the turn finishes. The `ExecuteToolStage` middleware added through `agent.add_middleware` is the supported hook for streaming each result. It is 32 lines and already native.

**EventMapper.** It maps Strands events, nested `tool_stream_event` events from specialists, and tool results to the client's event protocol. The only library alternative is AG-UI. bedrock-agentcore's `runtime/ag_ui.py` `AGUIApp` needs the `ag_ui` package, which is not installed, and the CLI and the UI would both need a rewrite. Keep, but finding 2 removes its prefix matching.

**ContextPrependingSplitter.** `extract_for_chunk` formats only the chunk text, the schema and the examples into the prompt. No document metadata reaches the model, so the splitter puts the aircraft type, title and section path into the chunk text. neo4j-graphrag 1.24.0 ships only `FixedSizeSplitter` and the LangChain and LlamaIndex adapters, with no markdown or heading splitter. `TextChunk` has no offsets, and 8B's `startOffset` and `endOffset` depend on chunks being substrings of the manual. It could go if the library passed chunk metadata into the extraction prompt.

**DimensionAwareOpenAIEmbeddings.** `BaseOpenAIEmbeddings.__init__` takes no `dimensions` argument, though `embed_query(text, **kwargs)` passes keyword arguments through. The subclass is a few lines. `BedrockEmbeddings` already takes `dimensions`, so it could go if the OpenAI class gains the same argument.

**EXTRACTION_PROMPT.** A custom `ERExtractionTemplate` is the library's intended hook. 8A and 8B move OperatingLimits to a CSV generator, which removes rules 4, 5 and 8 from it.

**fulltext_query and the hybrid type filter.** `HybridRetriever` takes no filters, and it passes the fulltext text to Lucene unescaped. The custom code escapes the query and widens the pool by `TYPE_FILTER_POOL_FACTOR` before filtering by type. `CHUNK_RETRIEVAL_QUERY` and `_chunk_formatter` already use the native `retrieval_query` and `result_formatter` hooks.

**get_graph_schema TTL cache.** It caches the schema text for the Text2Cypher prompt. The library has no cache.

**agent_samples Aura Agent simulation.** This code mimics what the hosted Aura Agent does, and it prints its Cypher for the demo.
- `graph_schema` checks each pattern against the data and adds `_LABEL_NOTES` hints. The library `get_schema` and `get_structured_schema` need APOC and add no hints.
- `_extract_cypher` strips a prose preamble. The library `extract_cypher` takes the first fenced block or else the whole text.
- `_run_text2cypher` uses a custom prompt, a timeout and a retry on empty results.
- `_run_similarity_search` could use `VectorRetriever`, but it would lose the printed Cypher that the demo shows.

**Domain logic.** `link_to_existing_graph`, 8B's `link_limits_to_chunks`, `limit_sources` and `check_limit_nodes`, 8A's `generator/limits.py`, and the `schema.py` constraint helpers are fleet-specific. No library covers them. `drop_extraction_constraints` exists because the pipeline writes duplicates before entity resolution. `create_embedding_indexes` and `build_extraction_schema` already use native neo4j-graphrag APIs.

**8C.** It changes docs, SVGs, `samples.py`, `prompts.py` and `test_agents.py`. None of it duplicates a library feature.

## Deliberately not recommending

- **AG-UI or ag-ui-strands:** Both are new dependencies, and both need a client and UI redesign.
- **LangChain `MarkdownHeaderTextSplitter` through the adapter:** It is a new dependency, and its chunks are not substrings, which breaks 8B's offsets.
- **Effort through top-level `outputConfig.effort`:** `core/model.py` sets effort in `additional_request_fields`. Strands `BedrockConfig.additional_args` could send it at the top level instead. Both work, and the current form is deployed and tested.
- **pydantic-settings for `GraphSettings.from_env`:** It adds a dependency to replace a small dataclass.
- **aws-secretsmanager-caching for `secrets.py`:** It adds a dependency, and rotation needs the custom reload anyway.
- **Strands 1.66.0 or bedrock-agentcore 1.27.0:** Both fail the release-age policy today, and no finding needs them.
- **Copying Strands `to_native_output_schema` into the pipeline:** It does not handle open maps, which `Neo4jGraph` needs.
- **FuzzyMatchResolver or the SpaCy resolvers:** The pipeline uses the default exact-match resolver, and the extraction rules already scope names by aircraft model. Fuzzy matching risks merging names that differ on purpose. The SpaCy resolver also needs a new dependency.

## Suggested order

1. **SSE reader and UI dedupe:** Finding 1 is small, local and low risk.
2. **Error status from graph tools:** Finding 2 removes a string convention. Run the routing tests and one live check.
3. **StructuredBedrockLLM to native structured output:** Finding 3 needs a live extraction comparison first.
4. **Anthropic provider decision:** Decide whether the pipeline keeps it. If not, delete `EffortAnthropicLLM` and the Anthropic branch in `agent_samples.py`.
5. **Memory auth hook in the fork:** Finding 5 is the largest change and needs a fork release.

Finding 4 can ride along with any other change to `agent_samples.py`.
