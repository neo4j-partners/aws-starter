# Plan: Local clients for the deployed supervisor, then the UI on Lambda

## Summary

Today the supervisor can run in the cloud, but you still have to copy its ARN
into `.env` by hand before any client can use it. After this plan, a deploy
writes the ARN for you. One `uv` command then runs the CLI or the UI on your
machine against either the local supervisor or the cloud one, and you choose
which. In the second phase, the browser UI itself moves to AWS Lambda. It
streams answers through a Lambda function URL, and Cognito protects it with a
login.

- **Removed:**
  - The manual step of copying `AGENT_ARN` and `AWS_REGION` into `.env` after a deploy.
  - The UI's habit of switching to the cloud just because `AGENT_ARN` is set.
- **Fixed:**
  - The CLI ignores the shared `.env`, so `--remote` fails unless `AGENT_ARN` is exported in the shell. It will read the file.
  - The UI sends no user ID, so the supervisor stores every browser user's memory under `anonymous`. The hosted UI will send the signed-in user's ID.
- **Added:**
  - `./agent.sh deploy` writes `AGENT_ARN` and `AWS_REGION` to the shared `.env`. `./agent.sh destroy` removes them.
  - A `fleet-client` command that runs the CLI or the UI, local by default, cloud with `--cloud`.
  - A UI stack: a Lambda function with response streaming, a function URL, a Cognito user pool, and an IAM role.
  - `./agent.sh` style commands to deploy, check, and destroy the UI stack.

## Facts this plan rests on

Each of these was checked in the code or the AWS docs.

- **UI cloud switch:** `ui/server.py` calls the deployed runtime whenever `AGENT_ARN` is set, and the local server otherwise.
- **CLI cloud switch:** `fleet-supervisor-cli --remote` reads `AGENT_ARN` from the process environment. No client module loads the shared `.env`. Only `fleet_supervisor/server.py` and `setup_secrets.py` do.
- **Deploy:** `./agent.sh deploy` runs `agentcore deploy` and prints a message. It writes nothing back. `runtime_arn()` in `agent.sh` already finds the ARN from `agentcore status --json`.
- **Memory user:** The supervisor reads `user_id` from the payload and uses `anonymous` when it is missing. The UI's payload holds only `prompt` and `trace`.
- **Deployed call:** `stream_deployed` needs only `bedrock-agentcore:InvokeAgentRuntime` on the runtime. Its read timeout is 300 seconds.
- **Streaming on Lambda:** Lambda Web Adapter runs an ordinary web app on Lambda. With `AWS_LWA_INVOKE_MODE=response_stream` and a function URL in `RESPONSE_STREAM` mode, an SSE response streams to the browser as it is written. AWS publishes a FastAPI streaming example for both zip and container packaging.
- **CloudFront in front:** A CloudFront origin access control can lock a function URL so only CloudFront reaches it. The browser must then send a SHA-256 hash of each POST body in `x-amz-content-sha256`.

## Decisions

- **Lambda with response streaming hosts the UI.** You chose it. It costs nothing when idle and fits a demo. Fargate behind an ALB is dropped. It costs money while idle, and the stack is larger.
- **Lambda Web Adapter runs the Starlette app unchanged.** The same `server.py` then runs locally and on Lambda. A Lambda-native handler, or Mangum, is dropped. Mangum does not stream, and a native handler would fork the code.
- **Local stays the default.** `fleet-client` uses the local supervisor unless you pass `--cloud`. A deploy writing the ARN to `.env` must never silently move local testing to the cloud.
- **The client passes the choice to the UI explicitly.** The UI reads a mode setting instead of guessing from `AGENT_ARN`. A missing ARN in cloud mode stops the UI at startup with a clear message.
- **The UI stack is its own CDK app, in `ui/`.** The AgentCore CLI owns `supervisor-agent/agentcore/cdk` and regenerates parts of it. A hand-built stack inside it could be overwritten. TypeScript matches that stack's tooling.
- **The UI stack reads the existing secrets.** The Lambda role reads the read-only fleet login from `NEO4J_PASSWORD_SECRET_ARN`. No new secret is created.
- **Users are created by an admin.** Cognito self sign-up is off, so only people you add can query the fleet.

## Phase 2 decisions (answered 2026-11-24)

1. **The app checks the login.** The function URL is public, and the app requires a Cognito session on every route except login and its callback. A request without a login is rejected before it reaches Bedrock or Neo4j. CloudFront with an origin access control is dropped for now. It adds a distribution, and the frontend would have to hash each POST body. Add it if the UI is shared beyond a small group.
2. **Memory is per user.** The hosted UI sends the Cognito user's ID as `user_id`, so each person gets their own memory. Without it, every signed-in user would share the `anonymous` memory, and one user's learned facts would reach another. Local runs keep `anonymous`.
3. **Measure, then pick the packaging.** The UI imports `fleet_supervisor`, whose dependencies include Strands, ADOT, neo4j-graphrag, and agent memory. That set may exceed the 250 MB unzipped limit for a zip package. This is a hypothesis. Phase 2's first task measures it. A zip with the Web Adapter layer is used if it fits, and an arm64 container image if not.

## Deliberately not doing

- **No custom domain or WAF.** The function URL is enough for a demo. Both can sit on CloudFront later.
- **No change to the supervisor's runtime or its stack.** The UI only calls the runtime that already exists.
- **No new Neo4j users or secrets.** The UI reuses the read-only login the deployed supervisor already uses.
- **No splitting `fleet_supervisor` into a smaller client package.** It would shrink the UI's image, but it is a bigger refactor than this needs. Revisit it only if packaging forces it.
- **No hosted CLI.** The CLI stays a local tool.
- **No change to `agentcore` CLI settings or to X-Ray indexing.**

## Where to look

- **Deploy and destroy:** the `deploy`, `destroy`, and `runtime_arn` parts of `supervisor-agent/agent.sh`.
- **Cloud vs local choice:** `supervisor_stream` in `ui/server.py`, and the `--remote` handling in `fleet_supervisor/client/cli.py`.
- **Deployed call:** `stream_deployed` in `fleet_supervisor/client/transport.py`.
- **Memory user:** the payload handling in `fleet_supervisor/server.py`.
- **Docs:** Steps 2 and 3 in the fleet `README.md`, the UI `README.md`, `docs/architecture/deployment.md`, and `docs/images/deployment-topology.svg`.

## Assumptions

- The AgentCore runtime `fleetsupervisor_default_supervisor` stays deployed in `us-east-1` while Phase 2 is built and tested.
- The account's SCP blocks the default CDK bootstrap. The UI stack uses the account's existing scoped bootstrap.
- Lambda Web Adapter and every new package meet the one-week release-age rule. No existing lock is re-resolved.

## Risks

- **Size:** The image could be large and slow to start cold. Phase 2 measures the cold start before the docs promise anything.
- **Timeout:** A Lambda function runs at most 15 minutes, and the stream reader waits up to 300 seconds. The function timeout must cover the longest answer.
- **Cost of a public URL:** Even with app-level login, anyone can call the function URL and cost a small invocation. Decision 1 accepts this for now.
- **`.env` edits:** Deploy and destroy rewrite a file that holds passwords. The edit must change only the two lines, keep every other line byte for byte, and never print values.

## Phase 2 decisions (answered 2026-11-24)

1. **The app checks the login.** The function URL is public, and the app requires a Cognito session on every route except login and its callback. A request without a login is rejected before it reaches Bedrock or Neo4j. CloudFront with an origin access control is dropped for now. It adds a distribution, and the frontend would have to hash each POST body. Add it if the UI is shared beyond a small group.
2. **Memory is per user.** The hosted UI sends the Cognito user's ID as `user_id`, so each person gets their own memory. Without it, every signed-in user would share the `anonymous` memory, and one user's learned facts would reach another. Local runs keep `anonymous`.
3. **Measure, then pick the packaging.** The UI imports `fleet_supervisor`, whose dependencies include Strands, ADOT, neo4j-graphrag, and agent memory. That set may exceed the 250 MB unzipped limit for a zip package. This is a hypothesis. Phase 2's first task measures it. A zip with the Web Adapter layer is used if it fits, and an arm64 container image if not.

## Deliberately not doing

- **No custom domain or WAF.** The function URL is enough for a demo. Both can sit on CloudFront later.
- **No change to the supervisor's runtime or its stack.** The UI only calls the runtime that already exists.
- **No new Neo4j users or secrets.** The UI reuses the read-only login the deployed supervisor already uses.
- **No splitting `fleet_supervisor` into a smaller client package.** It would shrink the UI's image, but it is a bigger refactor than this needs. Revisit it only if packaging forces it.
- **No hosted CLI.** The CLI stays a local tool.
- **No change to `agentcore` CLI settings or to X-Ray indexing.**

## Where to look

- **Deploy and destroy:** the `deploy`, `destroy`, and `runtime_arn` parts of `supervisor-agent/agent.sh`.
- **Cloud vs local choice:** `supervisor_stream` in `ui/server.py`, and the `--remote` handling in `fleet_supervisor/client/cli.py`.
- **Deployed call:** `stream_deployed` in `fleet_supervisor/client/transport.py`.
- **Memory user:** the payload handling in `fleet_supervisor/server.py`.
- **Docs:** Steps 2 and 3 in the fleet `README.md`, the UI `README.md`, `docs/architecture/deployment.md`, and `docs/images/deployment-topology.svg`.

## Assumptions

- The AgentCore runtime `fleetsupervisor_default_supervisor` stays deployed in `us-east-1` while Phase 2 is built and tested.
- The account's SCP blocks the default CDK bootstrap. The UI stack uses the account's existing scoped bootstrap.
- Lambda Web Adapter and every new package meet the one-week release-age rule. No existing lock is re-resolved.

## Risks

- **Size:** The image could be large and slow to start cold. Phase 2 measures the cold start before the docs promise anything.
- **Timeout:** A Lambda function runs at most 15 minutes, and the stream reader waits up to 300 seconds. The function timeout must cover the longest answer.
- **Cost of a public URL:** Even with app-level login, anyone can call the function URL and cost a small invocation. Decision 1 accepts this for now.
- **`.env` edits:** Deploy and destroy rewrite a file that holds passwords. The edit must change only the two lines, keep every other line byte for byte, and never print values.

## Phase 1: Deploy writes `.env`, and `fleet-client` runs the clients locally

**Status:** Complete. Merged to main as 67d20b7 (c96eed4 from olliz, 25dbd17 from qaz) and pushed on 2026-11-24. 424 tests pass on the merge.

**Notes:** Destroy removes only `AGENT_ARN` and keeps `AWS_REGION`, because the pipeline, the local server, and the secrets script share that region. `agent.sh` writes `demos/aircraft-fleet/.env` and does not read `FLEET_ENV_FILE`. The UI picks its supervisor from `FLEET_SUPERVISOR_MODE`, local when unset.

**Outcome:** After `./agent.sh deploy`, `uv run fleet-client ask --cloud "..."` and `uv run fleet-client ui --cloud` reach the deployed runtime with no manual edit. The same commands without `--cloud` reach the local supervisor, even with `AGENT_ARN` in `.env`.

- [ ] `./agent.sh deploy` writes `AGENT_ARN` and `AWS_REGION` to the shared `.env` after a successful deploy. It replaces old values and leaves every other line unchanged.
- [x] `./agent.sh destroy` removes `AGENT_ARN` after a successful teardown. It keeps `AWS_REGION` (decided 2026-11-24).
- [ ] A failed deploy or destroy leaves `.env` unchanged.
- [ ] The UI chooses local or cloud from an explicit mode setting, not from whether `AGENT_ARN` is set.
- [ ] `fleet-client ask` runs the CLI, and `fleet-client ui` runs the UI. Both load the shared `.env` and honor `FLEET_ENV_FILE`.
- [ ] `--cloud` without an `AGENT_ARN` stops with a message that says to run `./agent.sh deploy`.
- [ ] Tests cover the `.env` line edits, the mode choice, and the missing-ARN message.
- [ ] Steps 2 and 3 of the fleet README and the UI README describe the new commands.

**Done when:** `uv run pytest` passes. A real run shows the CLI and the UI answering in both modes, against the local server and runtime version 4.

## Phase 2: The UI on Lambda with response streaming

**Status:** Pending

**Outcome:** One command deploys the UI. A signed-in user opens the function URL and gets a streamed answer and the evidence graph from the deployed supervisor. A request without a login gets no answer and causes no Bedrock or Neo4j call.

- [ ] Measure the UI's installed dependency size to settle zip vs container image.
- [ ] A `ui/` CDK app defines the function, the streaming function URL, the Cognito user pool and app client, and the role.
- [ ] The role can invoke only the fleet runtime and read only the fleet login secret.
- [ ] The app requires a Cognito session on every route except login and its callback.
- [ ] The UI sends the signed-in user's ID as `user_id`.
- [ ] The function's timeout covers the stream reader's 300-second wait.
- [ ] Commands deploy, check, and destroy the UI stack, and print the URL after a deploy.
- [ ] CDK tests check streaming mode, the role's scope, and that self sign-up is off.
- [ ] The UI README, the deployment doc, and the topology diagram show the hosted UI.

**Done when:**

- A browser test against the hosted URL shows tokens arriving as they stream, not all at once.
- The evidence graph shows for a hydraulic-issues question.
- A request with no session gets a 401 or a redirect, and the function logs show no runtime call for it.
- Two different users see separate memory.
- The CDK tests pass, and `cdk destroy` removes the stack cleanly.

## Completion criteria

- Both phases' checklists are done or explicitly deferred.
- No `.env`, credentials, or secret values are committed or printed.
- The supervisor's runtime and stack are unchanged.
