# Fraud Agent Fixes Plan

Status: approved on 2026-11-23. The Decisions section records the answers.

This plan covers two things:

1. Upgrade the fraud memory agent to the latest Strands release and replace custom code with the Strands and Neo4j Agent Memory features built for the same job.
2. Fix the ten follow-ups that Cloud Retest 8 recorded.

The review used <https://strandsagents.com/llms.txt> and these pages from it: MCP tools, MCP transports, hooks, session management, memory, streaming async iterators, observability and traces, and Deploy to Bedrock AgentCore (Python). It also read the Neo4j Agent Memory 0.8.0 wheel and the `bedrock-agentcore` 1.26.0 runtime source.

## Current Versions

| Package | Locked | Latest allowed | Notes |
|---|---|---|---|
| strands-agents | 1.65.0 | 1.65.0 | Already locked. The pyproject floor says `>=1.52`. |
| neo4j-agent-memory | 0.5.0 | 0.8.0 | The pyproject caps it at `<0.6`. |
| bedrock-agentcore | 1.26.0 | 1.26.0 | 1.26.1 and 1.27.0 are under a week old. |
| mcp | 2.3.0 | 2.3.x | strands-agents 1.65 caps mcp below 2.4. |
| httpx2 | 2.16.0 | n/a | Declared but never imported. |
| opentelemetry-api | 1.45.1 | wait | The CVE relock waits until 2026-11-25. |

The fleet agents already run `strands-agents>=1.65`, `bedrock-agentcore[strands-agents]>=1.26` and Neo4j Agent Memory 0.8.0. The fraud agent can follow the same pattern.

## Strands Review: Custom Code Found

| # | Custom code today | Built-in replacement | Plan |
|---|---|---|---|
| a | `runtime_app.py` opens the MCP client with `with mcp_client:` and calls `list_tools_sync()`. | `Agent(tools=[mcp_client])`. MCPClient is a ToolProvider, so the Agent starts and stops it. | Adopt. |
| b | `core/credentials.py` posts the Cognito client_credentials grant by hand. `GatewayTokenAuth` adds the header. | `MCPClient(url, auth={"client_id", "client_secret", "scopes"})`. This finds the token endpoint through OAuth discovery on the server. | Needs a spike. See Question 2. |
| c | `runtime_app.py` and `memory_recall.py` find or create the NAMS conversation, store each turn, recall earlier sessions, and run the reasoning trace. | `Neo4jSessionManager.for_nams(session_id, user_id=..., retrieval_config=..., record_tool_calls=True)` in Neo4j Agent Memory 0.8.0. It uses Strands session hooks. | Adopt. See Question 1. |
| d | Tool calls go to reasoning memory from `current_tool_use` stream events. The input can be partial at first sight. | `record_tool_calls=True` on the session manager records each complete `toolUse` block. | Adopt with c. |
| e | Errors become a custom `{"type": "error"}` event inside an HTTP 200, so nothing logs at ERROR. | `BedrockAgentCoreApp` wraps streaming entrypoints. A raised exception is logged with `logger.exception("Error in async streaming")` and the client receives `{"error", "error_type", "message"}`. | Adopt. See Phase 4. |
| f | Tracing through `opentelemetry-instrument` with ADOT. | The Strands AgentCore guide uses ADOT. StrandsTelemetry is for agents outside AgentCore. | Keep. This one is already correct. |
| g | MCP sessions do not reconnect. | The Strands docs describe `MCPClient(..., auto_reconnect=True)`. The installed strands-agents 1.65.0 has no such parameter. | Not adopted. Revisit when a release that has it is a week old. |

Two items are not Strands code and stay as they are:

- `client/transport.py` is the caller side of `invoke_agent_runtime` and the local SSE stream.
- The FastMCP move for the two hand-built MCP clients is deferred, as agreed earlier (follow-up 5).

## Phases

### Phase 1: Dependencies

1. Raise the floor to `strands-agents>=1.65,<2`.
2. Change `bedrock-agentcore>=1.9.1` to plain `bedrock-agentcore>=1.26`. The fleet agents use the `[strands-agents]` extra, but that extra requires `mcp<2`. This agent needs `mcp>=2.2`, so the extra cannot resolve here.
3. Move Neo4j Agent Memory to 0.8.0 from PyPI.
4. Raise `requires-python` to `>=3.11` and the ruff target to `py311`. Neo4j Agent Memory 0.8.0 requires Python 3.11. The container already runs Python 3.12.
5. Remove `httpx2`. This fixes follow-up 6.
6. Relock with `uv lock --upgrade-package <pkg> --exclude-newer "1 week"` for only these packages. The OTel relock stays on its own date.

Done. The lock moved `neo4j-agent-memory` from 0.5.0 to 0.8.0. The other lock changes only drop the Python 3.10 split.

### Phase 2: MCP Client

1. `build_mcp_client()` stays `MCPClient(url=..., auth_provider=GatewayTokenAuth())`.
2. `runtime_app.py` passes the client in `Agent(tools=[mcp_client, ...])` and drops `with mcp_client` and `list_tools_sync()`.
3. The memory tools from `nams_context_graph_tools()` stay in the same tools list when `MEMORY_TOOLS` is on.
4. `runtime_app.py` calls `agent.cleanup()` in a `finally` block so the MCP session closes on every path.

Done. The MCP client passes straight to `Agent(tools=...)`. `_release` calls `agent.cleanup()` on every path.

### Phase 3: Memory Through the Session Manager

1. Build one `Neo4jSessionManager.for_nams(...)` per request with the resolved `session_id` and `user_id`.
2. Pass it as `Agent(session_manager=...)`. Close it in a `finally` block on every path.
3. Set `record_tool_calls=True` and a `Neo4jRetrievalConfig`.
4. Delete `server/memory_recall.py` and the manual capture code in `runtime_app.py`.
5. Keep the `tool` events sent to the client. They come from the stream and drive the CLI display.

Behavior changes to accept:

- **Conversation key:** The manager finds conversations by `metadata.strands_session_id`. Today the code uses `metadata.client_session_id`. Conversations from earlier retests will not be reused. The memory DB holds only retest data.
- **Recall:** Today recall searches the messages of up to 10 other conversations of the same user. The manager instead restores the current conversation and, with `retrieval_config`, injects workspace entities into each user message. See "NAMS Memory Scope" below.
- **Open traces:** The manager starts a reasoning trace and records each tool call, but 0.8.0 never calls `complete_trace`. Traces stay open after the turn. This is a library gap, not ours to patch through private attributes. Partly addressed on 2026-11-23 by the move to `0.8.0+fleet.9`. That build ends each trace with a `turn outcome` step that records success or failure. NAMS has no endpoint to complete a trace, so the trace still stays open.
- **Stored content:** The manager stores text turns only. Tool results are not stored as messages. This matches today.
- **Extraction:** Extraction runs on assistant turns as well. The three "agent" Person nodes from Retest 8 may come from this. Phase 3 checks whether they keep appearing.

### NAMS Memory Scope

The Neo4j Agent Memory docs set these rules for NAMS. Sources: the multi-tenancy how-to, the cross-agent sharing page, the backend capabilities reference, and the Strands integration page.

- **The workspace is the only tenancy boundary.** The API key selects it. Anyone with the key can read every conversation and entity in it.
- **`user_id` is ownership metadata.** It tags conversations and filters `list_conversations`. It does not isolate reads, and it does not filter entity search.
- **Entities are shared across the workspace by design.** NAMS extracts them server-side from every stored message.
- **Continuity comes from the conversation ID.** The application creates the ID, keeps it, and sends it back. A user ID alone does not resume a conversation.
- **Message search is conversation-scoped on NAMS.** `POST /conversations/{id}/search` searches one conversation only.
- **The application authorizes the caller** before any memory call. The user ID must come from an authenticated identity.
- **Separate tenants need separate workspaces.**

The current README is wrong on two points. It calls recall user-scoped, but the `user_id` filter is not an access boundary. It says the agent avoids entity search for tenancy, but entities are workspace-shared no matter which read the agent uses.

The recommended design for this demo:

1. One `Neo4jSessionManager.for_nams(session_id, user_id=...)` per request. It restores the conversation that `session_id` names.
2. The caller keeps the `session_id`. A new investigation gets a new ID. The runtime generates `fraud-<uuid>` when none is sent.
3. Cross-session recall uses `retrieval_config=Neo4jRetrievalConfig(include_entities=True, top_k=5)`. It injects workspace entities, such as accounts and merchants from earlier investigations, into each user turn. One investigation team shares one workspace.
4. The pull-based memory tools stay behind `MEMORY_TOOLS`. They do not inject context, so they do not conflict with `retrieval_config`.
5. The README states the workspace boundary plainly and drops the user-scoped claim.

Done. `server/memory_recall.py` and its tests are deleted. Each request builds one `Neo4jSessionManager.for_nams(...)` and closes it in a shielded `finally` task.

### Phase 4: Errors and the Anonymous Session

This phase fixes follow-ups 1 and 2.

1. Stop catching `Exception` in the entrypoint. Let it propagate to `BedrockAgentCoreApp`, which logs the traceback at ERROR.
2. Wrap the entrypoint body in an OpenTelemetry span named `fraud_memory_agent.invoke`. The span records the exception and sets ERROR status. `agentcore obs list --errors` filters on span status, so `./agent.sh logs --errors` then finds the trace. Strands only marks spans ERROR for failures inside the agent loop.
3. The session manager's `close()` in `finally` flushes the buffered turn. The manager owns the reasoning trace now, but leaves it open. See Phase 3.
4. Update `client/transport.py` to show the app's `{"error", "error_type", "message"}` event.
5. Handle a request with no `user_id` as Question 4 decides.

Done. Errors propagate to `BedrockAgentCoreApp` inside the `fraud_memory_agent.invoke` span. A request with no prompt or no `user_id` gets HTTP 400. A missing `session_id` starts a new `fraud-<uuid hex>` conversation.

### Phase 5: Deploy Script Memory Flag

This phase fixes follow-up 3. `agent.sh` line 293 runs `agentcore configure -e ... -n ...` without `--disable-memory`, so the prompt answer is lost and deploy creates an unused AgentCore memory. The agent uses NAMS only.

1. Pass `--disable-memory` to `agentcore configure`.
2. Check the generated `.bedrock_agentcore.yaml` shows no memory.

The Strands guide says the AgentCore CLI (`@aws/agentcore`) replaces `bedrock-agentcore-starter-toolkit`. The fleet agents already moved. Moving the fraud agent is a larger change, so Question 5 asks about it.

Done. `configure` passes `--disable-memory`. `invoke-cloud` sends `FRAUD_USER_ID`, which defaults to `demo-user`.

### Phase 6: Answer Accuracy

This phase covers follow-up 4. These are model behavior errors, not transport bugs.

1. Add query rules to `SYSTEM_PROMPT`:
   - Count with `count(DISTINCT ...)`.
   - Sort ranked lists with `ORDER BY` in Cypher.
   - Report only numbers that come from a tool result.
   - Count each cycle once by canonical node order.
   - Do not state amounts, durations or patterns that no query returned.
2. Rerun the Retest 8 prompts and compare with the graph's true values: 33 recipients, 238 transfers, the true fifth hub, and distinct triangles.
3. Question 6 asks about the model.

Step 1 is done. The rules are in `core/config.py`.

Step 2 ran in Cloud Retest 9. Three answers improved and one did not.

- **Recipients:** The agent found 33 recipients, sorted by amount. The top five rows match the graph.
- **Triangles:** The agent reported 899,179 distinct triangles. The graph returns the same count.
- **Transfers:** The agent said 206 transfers. The graph has 238. This is still open.
- **Fifth hub:** The long query did not rank hubs this time, so this row was not checked.

### Phase 7: Graph Loader Query

This phase fixes follow-up 8.

1. Change the shared-KYC query in `graph_loader/analyze_graph.py` from `CALL {` to `CALL (var) {` with an explicit scope.
2. Run `uv run fraud-graph-analyze` against the fraud graph and confirm the warning is gone.
3. Question 7 asks whether to add tests.

Done. The shared-KYC query uses `CALL () {`. Six offline tests in `graph-loader/tests/` cover the query text, the limit, and the empty result. The live run no longer logs the warning.

### Phase 8: Finance MCP Server Request Noise

This phase covers follow-up 9. A separate agent found the cause and made the fix.

- **Cause:** AgentCore Runtime health-checks each live MCP session. The server had no `GET /ping` route, so the Runtime fell back to an MCP `ping` POST to `/mcp` every 2 seconds. That is about 30 requests per minute per session until the 15 minute idle timeout. Six sessions give 180 per minute, and twelve give 360.
- **Tracebacks:** Each `POST /mcp` also logs "Error in message router". This is a race in mcp 1.22.0 in stateless mode. The request still returns 200. mcp 1.23.2 fixes it, but the image cannot reach it while fastmcp 2.13.3 caps mcp below 1.23.
- **Fix:** `neo4j-mcp-server/image/secret_entrypoint.py` adds a `GET /ping` route that returns `{"status": "Healthy"}` with no timestamp. The AWS docs warn that a changing timestamp stops idle sessions from timing out. Four tests cover the route.
- **Left over:** One traceback per real MCP request remains. Removing it needs a fastmcp and mcp upgrade in the external mcp-neo4j-cypher repo. That is out of scope here.
- **Retest check:** The Runtime log shows `GET /ping 200` and almost no idle `POST /mcp` lines.

Reviewed. The 47 MCP server tests pass.

Cloud Retest 9 shows the fix is not enough. The Runtime called `GET /ping` 29 times, and each call returned 200. In the same 40 minutes it also logged 4,608 `POST /mcp` requests. The rate climbed from 2 per minute at 16:02Z to 794 per minute at 16:16Z. The agent made about 20 tool calls in that window. The source of the rest is still unknown.

**Investigation, 2026-11-23.** The finance MCP stack was deployed by itself, with no agent, and its Runtime log was read per log stream.

- **One session per tool call:** The Gateway opens a new Runtime session for every tool call. One `./cloud.sh test` client session made four tool calls and started four Runtime sessions, four seconds apart.
- **Health ping:** Each Runtime session calls `GET /ping` once. After that it gets a `POST /mcp` every 2 seconds for as long as it lives. These requests do not keep the session alive.
- **Idle baseline:** With no client connected, the two sessions from the Gateway's tool sync gave 60 requests per minute. Both shut down exactly 15 minutes later, at the default idle timeout.
- **Retest 9 explained:** About 20 tool calls, each holding a session for 15 minutes, gives about 600 requests per minute. That matches the 794 seen.
- **Fix:** `neo4j-mcp-server/cdk/neo4j_mcp_stack.py` sets the Runtime's `idle_runtime_session_timeout` to 60 seconds, the AgentCore minimum. Every call is stateless, so a session holds nothing worth keeping. The change updates the Runtime without interruption.
- **Verified in the cloud:** After the fix, each of four new sessions lived about 64 seconds and handled 36 or 37 requests. Before it, a session ran about 450. The Gateway test passed 4/4, and the stack was torn down at 17:21Z.
- **Left for later:** One Runtime session per tool call is Gateway behavior. Session reuse can be revisited when the server moves off the mcp-neo4j-cypher fork.

### Phase 9: Leftover AWS Resources

This phase covers follow-up 7. Each resource gets a describe call first, then a deletion only with approval.

- **us-east-1:** Workload identity `finance_agent-Yuwcn1Ccw3` and the Lambda log groups `/aws/lambda/neo4j-mcp-server-finance-*`, `neo4j-agentcore-mcp-server-finance-*`, `neo4j-mcp-server-fleet-*` and `simple-neo4j-mcp-server-*`.
- **us-west-2:** The `neo4j-mcp-server-*` Lambda and CodeBuild log groups and the secret `neo4j-mcp/default`.
- **S3:** The bucket `neo4j-finance-demo`.

Done on 2026-11-23, except the workload identity.

- **Deleted in us-east-1:** The `oauth-provider` and `runtime-health-check` log groups for `neo4j-mcp-server-finance`, `neo4j-agentcore-mcp-server-finance`, `neo4j-mcp-server-fleet`, and `simple-neo4j-mcp-server`. No stack or function owned them.
- **Deleted in us-west-2:** The five `/aws/lambda/neo4j-mcp-server-*` log groups and `/aws/codebuild/neo4j-mcp-server-mcp-server-build`.
- **Not deleted:** AWS refused to delete `finance_agent-Yuwcn1Ccw3` with "WorkloadIdentity is linked to a service and cannot be deleted by the caller." It stays.
- **Not in scope:** The us-east-1 log groups for `neo4j-agentcore-mcp-server-fleet-*` and `neo4j-agentcore-mcp-server-supplier-*` and the us-west-2 `simple-neo4j-mcp-server-*` groups stay. The plan did not list them.
- **Kept by decision:** The secret `neo4j-mcp/default` and the bucket `neo4j-finance-demo`.

### Phase 10: Verification

1. Run unit tests with `uv run python -m unittest discover -s tests` and ruff with `uvx --exclude-newer "1 week" ruff check`.
2. Run locally with `uv run fraud-server` and `uv run fraud-cli`. Check that one conversation per session appears in NAMS, the tool calls are recorded, and a forced error logs at ERROR.
3. Run Cloud Retest 9. Deploy, invoke the Retest 8 prompts, check `logs --errors`, then destroy.
4. Update the Retest record.

Steps 2 to 4 ran on 2026-11-23. The record is Cloud Retest 9 in `demos/aircraft-fleet/docs/e2e-test-plan.md`.

- **Local:** The local checks passed. These were the 400 for a missing user ID, session restore, one NAMS conversation per session, recorded tool calls, and the forced error at `ERROR`.
- **Cloud:** Configure created no memory. Deploy, verify, and both prompts passed. `logs --errors` found no failed trace, and no turn failed, so the cloud error path was not exercised.
- **Teardown:** Both stacks were destroyed. No stack, Runtime, Gateway, or Runtime log group is left in us-east-1.
- **Open:** The transfer count in Phase 6 and the `POST /mcp` traffic in Phase 8 are still open.
- **Next:** Retest again after the OTel relock on or after 2026-11-25.

**AgentCore CLI cloud test, 2026-11-23.** After the move to the AgentCore CLI, the fraud agent was deployed to us-east-1 next to the finance MCP stack. Three failures came up before it passed.

- **No workload access token:** The smoke test failed with "The request has no workload access token for AgentCore Identity." A SigV4 caller gets that token only when it sends a runtime user ID. The smoke test, `invoke-cloud`, and the `fraud-cli --remote` transport now send the payload's `user_id` as the runtime user ID. The user's role already allowed `bedrock-agentcore:InvokeAgentRuntimeForUser`. Commits 68475b1 and 7f20f99.
- **Legacy model:** Bedrock then refused Sonnet 4.5. It marks the model as Legacy, and the account had not used it in 30 days. The default moved to Sonnet 5.5. Commit 54fa1f7.
- **Temperature:** Sonnet 5.5 rejected the request because it sets `temperature`. The agent no longer sets it. Commit 5bb37c2.
- **Pass:** The fourth deploy finished at 18:36Z, and its graph smoke test passed. One `./agent.sh invoke-cloud "Find circular transfer chains"` question returned HTTP 200 with `complete=true` and 11,954 bytes. Only the end of the answer was saved, so its accuracy was not checked.
- **Teardown:** `./agent.sh destroy` removed the Runtime, both Identity credentials, and the Runtime log group. `./deploy.py --env finance cleanup` deleted the MCP stack, its log group, the shared `neo4j-mcp-server` ECR repository, and the password secret. No matching stack, Runtime, or credential provider is left in us-east-1.

**fleet.9 cloud test, 2026-11-23.** After the move to `0.8.0+fleet.9` in commit 44ce0af, both stacks were deployed again in us-east-1.

- **Deploy:** The deploy finished at 19:30Z, and its graph smoke test passed. The CodeZip held `neo4j_agent_memory-0.8.0+fleet.9`.
- **Invoke:** One `./agent.sh invoke-cloud "Find circular transfer chains"` question returned HTTP 200 with `complete=true` and 11,815 bytes.
- **Trace:** The turn's NAMS trace has 8 tool-call steps and a last `turn outcome` step. That step's thought is "The turn succeeded." and its observation is `success`. The trace's completion time, outcome, and success fields are still empty. The 18:36Z trace from 0.8.0 has no outcome step.
- **Teardown:** `./agent.sh destroy` and `./deploy.py --env finance cleanup` ran at 19:37Z and 19:41Z. No matching stack, Runtime, or credential provider is left in us-east-1.

### Phase 11: Documentation Refresh

The fraud docs have no mermaid diagrams today. They describe the system in prose and code blocks only. The fleet demo replaced its mermaid and ASCII diagrams with hand-written SVG files in `docs/images/`. The fraud demo follows the same pattern.

1. Add SVG diagrams in `demos/fraud-amazon-quick/docs/images/`, styled like the fleet set:
   - `architecture.svg`: The dataset, graph loader, Neo4j, MCP server and Gateway, the agent, NAMS, the Iceberg loaders, Athena and Amazon Quick.
   - `agent-request-flow.svg`: One request through the agent, the MCP Gateway and NAMS.
   - `memory-lifecycle.svg`: The session manager opening, restoring, injecting entities, saving and closing. It also shows the workspace boundary.
   - `data-model.svg`: The fraud graph labels and relationship types.
   - `deployment-topology.svg`: The deploy steps, the stacks and the two stores.
2. Each README opens with an overview and a features list, like the fleet READMEs, and embeds its diagram.
3. Rewrite the memory sections of the agent README to match the NAMS Memory Scope rules.
4. Rewrite `fraud-memory-agent/docs/agent-memory-strands.md`. It describes the Bolt graph tools, not the NAMS session manager this agent uses.
5. Check every command and path in the top README quick start against the code.

Progress:

- **Diagrams:** All five SVGs are in `docs/images/`. They pass `xmllint`.
- **Top README:** It embeds the architecture diagram and lists all five. The quick start runs each block from the repo root.
- **Agent README:** The memory sections follow the NAMS Memory Scope rules. The request format, `FRAUD_USER_ID`, and teardown notes match the code. The obsolete limitation section is gone.
- **Memory doc:** `agent-memory-strands.md` now covers the session manager, the workspace boundary, and why the agent adopted 0.8.0.
- **Subproject READMEs:** The graph loader README embeds the data model. The Iceberg README embeds the architecture.

## Not Code Fixes

- **Follow-up 5:** The FastMCP move for `neo4j-mcp-server/client/mcp_operations.py` and `patterns/gateway-rbac-interceptor/client/demo.py` was deferred at first. It was done on 2026-11-23. See Decision 13.
- **Follow-up 10:** The SSO registration expiry is an account setting. Run `aws sso login` before cloud work. The registration expired at 2026-11-23T16:22:21Z.
- **Supervisor test hang:** Two `supervisor-agent/agent.sh deploy` processes from pytest runs were still alive about 2.5 days later. Both came from the test `test_anything_left_at_the_copy`. They were killed on 2026-11-23. A supervisor `agent.sh` test can leave a deploy hanging. Look into it with the supervisor IAM work.

## Decisions

1. **Memory library:** Adopt Neo4j Agent Memory 0.8.0 from PyPI and the session manager. Accept the Phase 3 behavior changes. On 2026-11-23 the agent moved to the fleet build `0.8.0+fleet.9`, as the fleet agents did. That build records each turn's outcome as a last trace step. NAMS still keeps the trace open. The release-age exception approved for the fleet agents now covers the fraud agent too. Only `neo4j-agent-memory` changed in the lock.
2. **OAuth:** Keep `GatewayTokenAuth` and `core/credentials.py`, as the fleet supervisor does.
3. **Errors:** Let every error propagate to the AgentCore app.
4. **No user_id:** Reject the request with an error.
5. **Deploy tooling:** Reversed on 2026-11-23. The agent moved from the starter toolkit to the AgentCore CLI. The reasons:
    - **Build:** The CLI builds a CodeZip from `agentcore/`, with a root `main.py` as the entrypoint. The Dockerfile and both cleanup scripts are gone.
    - **NAMS key:** The key is the `nams-api-key` Identity API-key credential, not a Runtime environment variable. The Runtime reads it on the first request with the request's workload token.
    - **Gateway token:** The Runtime gets it from the `fraud-gateway` OAuth2 credential provider. Local runs keep `.mcp-credentials.json`.
    - **IAM:** The CDK stack grants exactly the two credential providers and their two secrets, with no wildcards.
    - **Secret files:** `.env` and `.mcp-credentials.json` live in `demos/fraud-amazon-quick/`, one level above the zip folder. `./agent.sh deploy` refuses to run if a secret file is inside it.
6. **Model:** Add the prompt rules. After Cloud Retest 9 miscounted transfers, the default moved from Haiku 4.5 to Sonnet 4.5. On 2026-11-23 Bedrock refused Sonnet 4.5 as a Legacy model the account had not used in 30 days, so the default moved to Sonnet 5.5. The next retest compares accuracy.
7. **Graph loader:** Fix the query and add tests.
8. **AWS cleanup:** Delete the leftover log groups and the workload identity. Leave the secret `neo4j-mcp/default` and the bucket `neo4j-finance-demo`.
9. **MCP request noise:** A separate agent investigates and fixes it. The fix is a 60-second Runtime idle timeout. See Phase 8.
10. **Cloud retest:** Run Retest 9 now, then again after the OTel relock on 2026-11-25.
11. **Recall:** Adopt the NAMS Memory Scope design, with workspace entity injection through `retrieval_config`. The reasons:
    - The NAMS docs name the workspace as the only tenancy boundary. A `user_id` filter is a label, so the old user-scoped recall promised an isolation it did not have.
    - Entities are shared across the workspace whatever the agent reads. Avoiding entity search protected nothing.
    - The session manager is the library's supported path for restore and injection. It replaces about 150 lines of custom recall code.
    - Fraud investigation is team work. Accounts and merchants found in one investigation help the next one, so workspace sharing is the behavior the demo wants.
    - Message search on NAMS covers one conversation. Searching other conversations meant one call per conversation and a hand-made cap.
12. **Docs:** Refresh all fraud docs and add SVG diagrams like the fleet demo. See Phase 11.
13. **FastMCP client:** The MCP server clients moved to `fastmcp-slim[client]` 4.2. They use `mode="legacy"`, because the deployed server runs mcp 1.22 and answers the newer discover probe with a 400. Moving the server off the mcp-neo4j-cypher fork comes later.

## Open Questions

None.
