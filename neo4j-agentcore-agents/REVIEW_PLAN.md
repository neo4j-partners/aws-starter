# neo4j-agentcore-agents — Review & Fix Plan

Review date: 2026-05-17. Scope: `neo4j-agentcore-agents/` (fleet-agent,
finance-agent-gateway, finance-agent, orchestrator-agent, cfn/, Dockerfiles,
pyproject, credentials handling) checked against AWS Bedrock AgentCore
documentation.

## Proposal

### ELI5

Several agents in this folder will not stay working when deployed: one agent
never refreshes its login token so it dies after a few hours, the deploy
template hands the agent keys to the entire AWS account, the container ships
with a secret file inside it, and the "we have tracing" claim does not match
how the container is started. None of these are visible until the thing runs
in the cloud for a while. This plan fixes the breakages, tightens the
security posture, and corrects the docs.

### Removed

- Unused `strands-agents` dependency in `pyproject.toml` (no agent imports it).
- Per-request rebuild of the orchestrator graph and its `MemorySaver`.

### Fixed

- `finance-agent-gateway/agent.py` loads a static `access_token` and never
  refreshes it; deployed agent returns auth errors once the Cognito token
  expires. The token currently in `.mcp-credentials.json` expired on
  2026-01-23.
- `finance-agent/simple-agent.py` token handling reviewed for the same defect.
- CFN execution role grants `bedrock:*`, `ecr:*`, `logs:*`, `xray:*`,
  `cloudwatch:*`, `bedrock-agentcore:*`, `secretsmanager:*`, `sts:AssumeRole`
  on `*`; AWS guidance specifies a scoped policy.
- CFN trust policy has no `aws:SourceAccount` / `aws:SourceArn` conditions
  (confused-deputy exposure); AWS docs require them.
- `NetworkMode` parameter offers `PRIVATE`, which is not a documented
  AgentCore network mode (hypothesis — see Decisions).
- Observability: `aws-opentelemetry-distro` is a dependency but the Dockerfile
  `CMD` runs the agent directly, not through the ADOT auto-instrumentation
  entrypoint, so the README's OpenTelemetry claim does not hold for the
  Docker/CFN path (hypothesis — see Decisions).
- Inconsistent model IDs: fleet-agent and orchestrator use
  `global.anthropic.claude-sonnet-4-5-20250929-v1:0`; finance-agent-gateway
  uses the older `us.anthropic.claude-sonnet-4-20250514-v1:0`.
- README does not mention the one-time CloudWatch Transaction Search account
  setup that AgentCore observability requires.

### Added

- Token-refresh logic in `finance-agent-gateway/agent.py` (mirroring the
  working pattern in `fleet-agent/aircraft-agent.py`).
- Confused-deputy condition keys on the CFN trust policy.
- A documented decision on credential delivery to the container.

### Deliberately not doing

- Not rewriting the multi-agent orchestration design; routing logic works.
- Not changing the MCP server side (`neo4j-agentcore-mcp-server/`); out of
  scope.
- Not migrating from raw CFN to CDK; the CFN path is intentional.
- Not converting per-request MCP client creation into a shared pooled client
  beyond what the orchestrator memory fix requires; latency optimization is
  deferred unless it blocks correctness.
- Not rotating the leaked-looking credentials in `.mcp-credentials.json`: it
  is gitignored and verified **not** committed to git. It is still baked into
  ECR images (see Decisions).

### Decisions

- **Credential delivery (needs user input).** The CFN role already grants
  Secrets Manager read. Options: (a) keep `COPY .mcp-credentials.json` into
  the image (simplest, current behavior, secret lives in ECR), (b) inject via
  AgentCore runtime environment variables, (c) read from Secrets Manager at
  startup. Recommendation: (c) for anything beyond a throwaway workshop.
  Locked only after user confirms; alternatives recorded here.
- **IAM scope (needs user input).** The template comment says the broad
  policy is intentional for workshop/demo. Option A: keep broad, add a loud
  warning. Option B: replace with the scoped policy from the AWS docs
  (`runtime-permissions.html`). Recommendation: B, with the broad policy kept
  as a commented alternative. Decision deferred to user because it changes
  workshop ergonomics.
- **Trust policy conditions (locked).** Add `StringEquals aws:SourceAccount`
  and `ArnLike aws:SourceArn arn:aws:bedrock-agentcore:<region>:<account>:*`.
  This is a pure security hardening with no functional downside; AWS docs
  state the trust policy "must include" it. No alternative retained.
- **`NetworkMode` value (hypothesis to verify).** AWS docs describe `PUBLIC`
  and VPC-based networking; `PRIVATE` as an enum value is unverified. Verify
  against the `AWS::BedrockAgentCore::Runtime` CFN resource schema before
  changing the AllowedValues; do not guess.
- **Observability entrypoint (hypothesis to verify).** AWS docs say
  AgentCore-runtime-hosted agents are auto-instrumented and the ADOT library
  step is "non-runtime only." A CFN `ContainerConfiguration` deployment may
  or may not count as "runtime-hosted." Verify whether CFN-deployed
  containers get auto-instrumentation; only change the Dockerfile `CMD` if
  they do not.

### Where to look

- Token refresh: `finance-agent-gateway/agent.py`, compare to
  `fleet-agent/aircraft-agent.py` `refresh_token` / `check_token_expiry`.
- IAM + trust + network mode: `cfn/agent-runtime.yaml`.
- Observability: `*/Dockerfile` `CMD`, `pyproject.toml` ADOT dependency,
  `README.md` observability claim.
- Model IDs: `MODEL_ID` constant in each agent module.
- Orchestrator memory: `orchestrator-agent/orchestrator_agent.py`
  `create_orchestrator_graph` (MemorySaver created per request).

### Done when

- A deployed finance-agent-gateway answers a query after its initial token
  would have expired (token refresh exercised).
- `cfn/agent-runtime.yaml` trust policy contains the two condition keys and
  the stack still deploys.
- `NetworkMode` AllowedValues match verified AgentCore-supported values.
- Observability claim in README matches actual behavior of the deployed
  container (verified by traces appearing, or claim corrected/qualified).
- All agents reference one agreed model ID.
- `strands-agents` removed and every agent still imports and runs.
- README documents the Transaction Search prerequisite.

---

## Phased Plan

### Goal

Make every agent in `neo4j-agentcore-agents/` survive a real cloud
deployment, align IAM and trust configuration with AWS AgentCore guidance,
and make the documentation match reality.

### Assumptions

- The MCP server and Gateway in `neo4j-agentcore-mcp-server/` are deployed and
  reachable; this review does not change them.
- Workshop usability matters, so security tightening is proposed with the
  broad/demo alternative preserved, not silently removed.
- `.mcp-credentials.json` is local-only (verified not in git).

### Risks

- Scoping IAM down can break deployment if a required action is missed;
  validate with an actual stack deploy + invoke.
- Changing the Dockerfile entrypoint for observability could break startup if
  the auto-instrumentation assumption is wrong; gate on verification.
- Model ID change can hit Bedrock model-access / region availability errors.

### Phase 1 — Verify the open hypotheses

Status: Pending

- [ ] Confirm supported `AWS::BedrockAgentCore::Runtime`
      `NetworkConfiguration` modes from the CFN resource schema / AWS docs.
- [ ] Confirm whether a CFN `ContainerConfiguration` deployment is
      auto-instrumented for observability or needs the ADOT entrypoint.
- [ ] Confirm current recommended Bedrock model ID for the target region.
- [ ] Record findings in this file's Decisions section.

Completion: every hypothesis above is either confirmed or refuted in writing.

### Phase 2 — Functional breakages

Status: Pending (depends on Phase 1 for observability item)

- [ ] Add token expiry check + refresh to `finance-agent-gateway/agent.py`.
- [ ] Audit `finance-agent/simple-agent.py` for the same static-token defect;
      fix if present.
- [ ] If Phase 1 shows containers are not auto-instrumented, switch the
      Dockerfile `CMD` to the ADOT auto-instrumentation entrypoint; otherwise
      record that no change is needed.
- [ ] If Phase 1 refutes `PRIVATE`, correct `NetworkMode` AllowedValues.

Completion: a redeployed finance-agent-gateway answers a query past the
original token lifetime; network mode and observability match verified facts.

### Phase 3 — Security alignment

Status: Pending (IAM scope + credential delivery gated on user decision)

- [ ] Add `aws:SourceAccount` / `aws:SourceArn` trust-policy conditions to
      `cfn/agent-runtime.yaml` (locked, no user input needed).
- [ ] Apply the user's chosen IAM-scope option (broad+warning or scoped).
- [ ] Apply the user's chosen credential-delivery option.
- [ ] Redeploy the stack and confirm the agent still assumes the role and
      invokes Bedrock.

Completion: stack deploys with hardened trust policy; agent runs under the
chosen IAM/credential model.

### Phase 4 — Consistency & cleanup

Status: Pending

- [ ] Unify `MODEL_ID` across all agents to the agreed value.
- [ ] Remove `strands-agents` from `pyproject.toml`; re-sync; smoke-test each
      agent import.
- [ ] Fix orchestrator so the graph/`MemorySaver` is built once, not per
      request, so `thread_id` session memory actually persists.
- [ ] README: document the one-time CloudWatch Transaction Search setup and
      qualify the observability claim to match verified behavior.

Completion: one model ID everywhere, no dead dependency, orchestrator session
memory persists across calls, README matches reality.

### Completion criteria

All four "Done when" checklist items from the proposal hold, each phase's
completion line is satisfied, and the two user-gated decisions (IAM scope,
credential delivery) are recorded as locked with their reasoning.
