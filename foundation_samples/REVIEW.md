# simple-oauth-gateway Review and Remediation Plan

Review date: 2026-05-17. Scope: `foundation_samples/simple-oauth-gateway`,
cross-checked against current AWS Bedrock AgentCore documentation and AWS CDK
best practices.

Context: `sample-agentcore-mcp-server` and `simple-agentcore-agent` were removed
from `foundation_samples/` because the finalized `neo4j-agentcore-mcp-server`
stack and `neo4j-agentcore-agents/fleet-agent` already cover those patterns.
`simple-oauth-gateway` is retained because it is the only example in the repo
that demonstrates the AgentCore **Gateway interceptor Lambda** pattern (inbound
auth interception, identity-header injection, request/response transformation,
RBAC). That pattern exists nowhere else, including the finalized neo4j stack.

This document scopes the remediation to `simple-oauth-gateway` only.

---

## Proposal

### Summary (plain English)

`simple-oauth-gateway` teaches how to put an AgentCore Gateway with OAuth2
(Cognito) auth and a Lambda interceptor in front of an MCP server on AgentCore
Runtime. The interceptor and gateway wiring are correct and match AWS docs, but
the sample currently teaches a broken pattern: the server-side RBAC it
advertises is dead code that never runs, the demo client crashes on import,
permanent passwords are committed in source, the execution role omits the
confused-deputy protection AWS requires, and parts of the docs contradict the
working code. A broken security sample is worse than none, so the plan fixes the
dangerous and non-functional items first, then hardens IAM, then corrects
lifecycle hygiene, then aligns the docs.

### Why

Evidence found in code:

- `mcp-server/server.py` declares `_request_headers: ContextVar[dict]` with
  `default={}` and never calls `.set()` anywhere. No middleware copies the
  injected `X-User-Id` / `X-User-Groups` headers into it, so
  `_get_user_context()` always returns `unknown` / unauthenticated. The
  `admin_action` "defense in depth" check and `get_user_info` are dead code.
  README and `docs/ARCHITECTURE.md` claim the server reads these headers.
- `client/demo.py` annotates module-level `_token_cache` / `_token_expiry` with
  `Optional` but never imports it. The annotations are evaluated at import, so
  `python client/demo.py` raises `NameError` before `main()` runs, which also
  breaks `test.sh`.
- `setup_users.py`, `test.sh`, `client/demo.py`, README, and ARCHITECTURE
  hardcode permanent Cognito passwords (`AdminPass123!`, `UserPass123!`);
  `setup_users.py` prints the password to stdout and sets `Permanent=True`.
- The execution role assumes `bedrock-agentcore.amazonaws.com` with no
  `aws:SourceAccount` / `aws:SourceArn` conditions; AWS documents these as
  required confused-deputy protection.
- `FIX_32.md` still presents an unimplemented "Fix Plan" although the fix
  (Gateway role `lambda:InvokeFunction`) is already in
  `simple_oauth_stack.py`. `docs/ARCHITECTURE.md` documents the interceptor
  error response as `immediateGatewayResponse` with a JSON-RPC `error`, but the
  working Lambda returns `transformedGatewayResponse` with `result.isError`.

### Scope

Touches the MCP server, the demo client, `setup_users.py`, the CDK stack
(`simple_oauth_stack.py`), the interceptor and provider Lambdas,
`deploy.sh` / `test.sh`, `cdk.json`, and the README / ARCHITECTURE / FIX_32
docs.

### Removed

- Hardcoded permanent passwords in `setup_users.py`, `test.sh`,
  `client/demo.py`, README, ARCHITECTURE, and the password echoed to stdout.
- The obsolete "Fix Plan" steps in `FIX_32.md`.
- The dead RBAC helpers in `mcp-server/server.py` if header propagation is
  judged out of scope (fallback only; see Decisions).

### Fixed

- `client/demo.py` imports `Optional` (or uses `| None`), so the demo and
  `test.sh` run at all.
- `_request_headers` is populated per request via middleware so server-side
  RBAC actually reflects the caller, or the dead code and its documentation are
  removed together.
- The execution-role trust policy gains `aws:SourceAccount` /
  `aws:SourceArn` confused-deputy conditions.
- Over-broad IAM resources narrowed: CloudWatch Logs scoped to the
  AgentCore log-group ARN, Secrets Manager scoped to a name prefix, the Gateway
  policy references the interceptor Lambda by `function_arn` instead of a
  hand-built ARN string.
- Lambda runtimes bumped to `PYTHON_3_13`; explicit log retention and removal
  policies on the three Lambda log groups; generated names instead of hardcoded
  physical names where they block redeploys.
- `FIX_32.md` marked resolved; `docs/ARCHITECTURE.md` interceptor
  error-response section and code-walkthrough symbols regenerated from current
  source; `cdk.json` feature flags refreshed for the pinned `aws-cdk-lib`.

### Added

- Runtime-generated or Secrets Manager-backed credentials for the Cognito test
  users.
- Per-request header-propagation middleware in `mcp-server/server.py` (if the
  RBAC path is kept).
- A "demo only / not production" warning where weakened auth is retained
  deliberately.

### Deliberately not doing

- Not changing the working interceptor request/response handling. The Lambda
  logic matches AWS docs; only the prose describing it is wrong.
- Not migrating the inline-polling health-check custom resource to the CDK
  `Provider` framework. It works for the demo timings; logged as Low, deferred.
- Not rewriting the stack to L2 constructs for AgentCore. No L2 construct
  exists; L1 `Cfn*` is correct here.
- Not adding new features or new samples. Remediation only.

### Decisions

- Fix order is severity-driven: broken-or-dangerous first, IAM hardening
  second, lifecycle hygiene third, docs last. Reasoning: the Critical items are
  either exploitable or make the sample non-functional; docs depend on the
  final code so they go last. Alternative considered (docs-first to unblock
  readers) dropped because docs would then describe code that is about to
  change.
- LOCKED: wire real per-request header propagation in `mcp-server/server.py`
  rather than deleting the RBAC code. The interceptor pattern (identity flowing
  gateway interceptor -> injected headers -> server reads them -> RBAC) is the
  reason this sample is kept; deleting the server-side half would teach the
  single-point-of-enforcement gap this sample should warn against. FastMCP runs
  on Starlette, so a request middleware that calls
  `_request_headers.set(dict(request.headers))` closes it. "Delete the dead
  code" is dropped as an alternative.
- LOCKED: credentials are generated at deploy time by CDK, stored in a
  `secretsmanager.Secret`, and read by `setup_users.py` / `client/demo.py` /
  `test.sh` from the secret ARN. Reasoning: a sample must model the exemplary
  pattern, and a single Secrets Manager source of truth is teachable where a
  pure runtime-random value gives the test client and scripts nothing shared.
  Alternatives dropped: hardcoded passwords, env-var prompt, unstored
  runtime-random.
- LOCKED: deferred Low items (L1/L2/L3) get a one-line `# demo limitation:`
  comment at each site rather than being silently deferred, so the sample does
  not present a fragile pattern as if it were intentional. Added as a Phase 4
  task.
- Lambda runtimes move to 3.13 for the longest support window; this is the one
  forced version bump.

### Where to look

- Dead RBAC: `mcp-server/server.py` user-context helpers and their callers.
- Broken client: `client/demo.py` module-level imports.
- Secrets: `setup_users.py`, `test.sh`, `client/demo.py`, and the Cognito
  section of `simple_oauth_stack.py`.
- IAM and roles: the role / policy blocks in `simple_oauth_stack.py`.
- Docs: `FIX_32.md`, `docs/ARCHITECTURE.md`, `cdk.json`.

### Done when

- No password or secret appears in source, scripts, or stdout.
- Server-side RBAC observably reflects the caller's identity, or the dead code
  and its documentation are gone together.
- `python client/demo.py --help` and `test.sh` run without `NameError`.
- The execution-role trust policy includes `aws:SourceAccount` and
  `aws:SourceArn` conditions.
- No IAM statement uses a `*` resource where a scoped ARN is feasible; the
  Gateway policy references the Lambda by `function_arn`.
- The three Lambdas use `PYTHON_3_13` with explicit log retention and removal
  policies; a deploy-then-destroy cycle leaves no orphaned log group.
- `FIX_32.md` states the issue is resolved; `ARCHITECTURE.md` matches the
  current code and AWS guidance.

---

## Phased Plan

### Goal

Bring `simple-oauth-gateway` to a state where the Gateway-interceptor pattern it
teaches is secure, runnable, and consistent with current AWS AgentCore
documentation.

### Assumptions

- The sample is for public/educational use, so its security patterns must be
  exemplary, not merely functional.
- The reviewer findings are accurate; each fix is verified against the cited
  AWS doc before implementation.
- FastMCP exposes per-request context (request headers) through
  `mcp.get_context()` or the underlying Starlette request; confirmed in Phase 1.

### Risks

- Wiring real header propagation depends on the FastMCP request-context API; if
  unavailable, fall back to removing the dead code (Decision documented).
- Moving test credentials off hardcoded values changes the token-fetch flow in
  `setup_users.py` / `test.sh` / `client/demo.py`; these must change in
  lockstep or testing breaks.
- Tightening IAM resource scopes risks runtime denials; validate against the
  documented execution-role reference and a deploy test.

### Phase 1 — Critical: make the sample correct and runnable — COMPLETE

Outcome: the advertised RBAC is real or honestly removed, the demo client runs,
and no secrets are in source.

- [x] Added `IdentityHeaderMiddleware` (Starlette `BaseHTTPMiddleware`) in
      `mcp-server/server.py` that sets `_request_headers` from
      `request.headers` per request; `__main__` now serves
      `mcp.streamable_http_app()` with the middleware via uvicorn so
      `get_user_info` / `admin_action` see the injected identity. Declared the
      now-direct `starlette` / `uvicorn` imports in `mcp-server/requirements.txt`.
- [x] `client/demo.py`: switched module-level annotations to `str | None` /
      `datetime | None` (no `Optional` import needed; 3.10+). `demo.py --help`
      runs cleanly; the import-time `NameError` is gone.
- [x] Removed hardcoded passwords from `setup_users.py`, `test.sh`,
      `client/demo.py`, `README.md`, `docs/ARCHITECTURE.md`. CDK now generates
      a `TestUserPassword` Secrets Manager secret at deploy
      (`RemovalPolicy.DESTROY`, alphanumeric, length 20) and outputs
      `TestUserSecretName`; the three scripts read the password from the secret.
      `setup_users.py` no longer prints the password.

Validation: `py_compile` clean for all changed Python; `demo.py --help` and
`setup_users.py --help` run; `starlette`/`uvicorn` import in the venv; grep
confirms no `AdminPass123`/`UserPass123` or `Optional[` outside `.venv`.

Notes: no drift from the locked decisions. RBAC wired (not deleted) and a single
deploy-time Secrets Manager password used for both test users, exactly as
decided. Middleware runtime behavior not exercised (requires a deploy); design
matches the intended FastMCP/Starlette pattern.

Completion: met.

### Phase 2 — IAM hardening — COMPLETE

Outcome: the trust policy carries confused-deputy conditions and no statement
is broader than necessary.

- [x] Added `aws:SourceAccount` (StringEquals) + `aws:SourceArn` (ArnLike
      `arn:aws:bedrock-agentcore:{region}:{account}:*`) conditions to both
      `RuntimeRole` and `GatewayRole` trust relationships.
- [x] Split runtime logs: `logs:DescribeLogGroups` on `log-group:*` (it cannot
      be scoped to one group), the rest on
      `log-group:/aws/bedrock-agentcore/*` and its `log-stream:*`. Scoped
      `custom_resource_role` Secrets Manager and the gateway-role
      `OAuthProviderAccess` secret resource to the
      `secret:bedrock-agentcore*` prefix. Annotated `ecr:GetAuthorizationToken`
      and X-Ray `*` as API-mandated.
- [x] Replaced the hand-built Lambda ARN in the gateway policy with
      `auth_interceptor_lambda.grant_invoke(gateway_role)`. The resource-based
      `add_permission` stays at `gateway/*` with a documented reason: a
      gateway-id-specific scope is a circular dependency (the Gateway is
      created after, and references, the interceptor Lambda).

Validation: `cdk synth` succeeds (EXIT 0, 897-line template). Template confirms
two `aws:SourceAccount` conditions, separate `DescribeLogGroups` on
`log-group:*`, AgentCore log scoping, `secret:bedrock-agentcore*` scoping, and
both the identity (`grant_invoke`) and resource-based `lambda:InvokeFunction`.

Notes: no drift. The `gateway/*` resource scope was explicitly allowed by the
plan ("if feasible"); the circular-dependency reason is recorded in code.

Completion: met (full deploy test deferred; synth-level validation done).

### Phase 3 — CDK lifecycle hygiene — COMPLETE

Outcome: `cdk destroy` (or documented cleanup) leaves no orphaned resources.

- [x] All three Lambdas bumped to `PYTHON_3_13`.
- [x] Added an explicit `logs.LogGroup` (1-week retention,
      `RemovalPolicy.DESTROY`) per Lambda via a local `_log_group` helper and
      the `log_group=` prop.
- [x] Dropped `role_name` (3 roles), `user_pool_name`, and `function_name`
      (3 Lambdas). The custom log group keeps logs tied to each function
      despite the generated name. Lambdas are referenced by object/`function_arn`
      and `grant_invoke`, so no string coupling broke.
- [x] README cleanup section now documents the unmanaged
      `/aws/bedrock-agentcore/runtimes/*` log groups with a delete snippet.
      The `deploy.sh --destroy` path already used `cdk destroy --force` (the
      raw `delete-stack` is only the deferred-L3 rollback retry), so no change
      needed there.

Validation: `cdk synth` succeeds; template shows 3x `Runtime: python3.13`,
3x `RetentionInDays: 7`, and zero hardcoded role/function/pool names.

Notes: no drift. The Lambda log-group construct IDs are new resources; on an
existing stack this replaces the implicit groups, which is the intended
hygiene change.

Completion: met (synth-level; deploy-then-destroy cycle deferred to a real
deploy).

### Phase 4 — Documentation accuracy — COMPLETE

Outcome: docs match the code and AWS guidance.

- [x] `FIX_32.md`: rewritten to a resolved-state record. States the IAM
      `lambda:InvokeFunction` root cause as RESOLVED; the obsolete "Fix Plan"
      steps and the contradictory "CDK config is the root cause" speculation
      were deleted; stale "partially working / not invoked" status tables
      replaced with the verified findings.
- [x] `docs/ARCHITECTURE.md`: error-response section corrected to
      `transformedGatewayResponse` + `result.isError`. Code-walkthrough symbols
      regenerated from current source (`_decode_jwt`, `_deny_request`,
      `_allow_request`); stale `_decode_jwt_claims` / `_error_response` /
      `immediateGatewayResponse` removed. The removed `InvokeLambdaInterceptor`
      inline policy was replaced with `grant_invoke(gateway_role)` to match
      Phase 2. Line references regenerated against the current files.
- [x] `cdk.json` feature flags refreshed to the baseline generated by the
      CDK CLI for the pinned `aws-cdk-lib` (installed 2.233.0); `app` and
      `watch` blocks preserved.
- [x] One-line `# demo limitation:` comments added at the three deferred Low
      sites: `oauth_provider_lambda.py` (shared Create/Update path and the
      unguarded CFN-response PUT), `runtime_health_check_lambda.py` (inline
      ~10-min polling loop), and `deploy.sh` (ECR repo lifecycle managed
      outside CDK).

Validation: `py_compile` clean on both edited Lambdas; `bash -n deploy.sh`
clean; `cdk.json` valid JSON; `cdk synth` exits 0 with the refreshed flags
(two benign metadata-collection warnings, no template impact); doc grep
confirms zero `immediateGatewayResponse` / `_decode_jwt_claims` /
`_error_response` / `InvokeLambdaInterceptor` references remain.

### Deferred (logged, not in scope now)

- OAuth provider custom resource idempotency on UPDATE and unguarded CFN
  response PUT (`infra_utils/oauth_provider_lambda.py`) — Low.
- Inline ~10-minute polling health-check custom resource
  (`infra_utils/runtime_health_check_lambda.py`) → CDK `Provider` framework —
  Low.
- ECR repo lifecycle managed by `deploy.sh` instead of CDK — Low.

---

## Appendix: full findings

| ID | Sev | File | Issue |
|----|-----|------|-------|
| C1 | Critical | `mcp-server/server.py` | `_request_headers` ContextVar never `.set()`; server-side RBAC and `get_user_info` are dead code; docs claim otherwise. |
| H1 | High | `FIX_32.md`, `docs/ARCHITECTURE.md` | FIX_32 fix is implemented but the doc is stale and self-contradictory; ARCHITECTURE shows the wrong interceptor response shape. |
| H2 | High | `setup_users.py`, `test.sh`, `client/demo.py`, docs | Permanent passwords hardcoded and echoed to stdout. |
| H3 | High | `client/demo.py` | `Optional` used at module scope without import; `NameError` at import breaks the demo and `test.sh`. |
| M1 | Medium | `simple_oauth_stack.py` | Broad `*` IAM resources where scoping is feasible (logs, Secrets Manager). |
| M2 | Medium | `simple_oauth_stack.py` | Hardcoded physical resource names block redeploys; Gateway policy couples to a constructed name string. |
| M3 | Medium | `simple_oauth_stack.py` | Lambda runtime 3.11; manual IAM where `grant_*` helpers exist. |
| M4 | Medium | `simple_oauth_stack.py` | No log retention / removal policy on three Lambda log groups. |
| L1 | Low | `infra_utils/oauth_provider_lambda.py` | Custom resource not idempotent on UPDATE; unguarded CFN-response PUT. |
| L2 | Low | `infra_utils/runtime_health_check_lambda.py` | Inline ~10-min polling custom resource; prefer CDK `Provider`. |
| L3 | Low | `deploy.sh`, `simple_oauth_stack.py` | ECR repo lifecycle split from CDK; raw `delete-stack` retry can desync state. |
| L4 | Low | `docs/ARCHITECTURE.md`, `cdk.json` | Code-walkthrough symbols/lines stale; old feature flags. |

Verified correct (no action): Dockerfile port 8000 + ARM64 + `stateless_http` +
`streamable-http` match the MCP protocol contract; interceptor input/output
schema and `interceptorOutputVersion: "1.0"` match the AgentCore interceptor
docs; Gateway `lambda:InvokeFunction` plus the Lambda resource-based policy are
both required and both present (FIX_32's core root cause is genuinely resolved
in code); the Cognito M2M client (`client_credentials`, `generate_secret`,
resource-server scope `simple-oauth/invoke`) and the SECRET_HASH computation in
`demo.py` are correct for a confidential client.
