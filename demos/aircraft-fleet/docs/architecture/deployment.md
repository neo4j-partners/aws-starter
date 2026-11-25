# Deployment Architecture

The fleet demo deploys two CloudFormation stacks into one AWS account and
reads two Neo4j databases outside it. The supervisor stack is required. The
hosted UI stack is optional. The supervisor needs the fleet graph loaded
before it can answer. The Runtime reads both Neo4j passwords from
Secrets Manager, so no password appears in a template, an environment
variable, or a deployment package.

![One AgentCore CLI stack holds the supervisor Runtime. Before the deploy, the developer creates the two Neo4j secrets. The Runtime reads the fleet graph and the memory database directly. It calls Claude and Titan on Bedrock. It reads both Neo4j passwords from Secrets Manager and writes its logs to CloudWatch Logs. The optional FleetUi stack hosts the browser UI. The browser signs in on the Cognito managed login page and opens a public function URL that streams each answer. The URL invokes the UI function, which Lambda Web Adapter runs. The function reads the app client ID from an SSM parameter and calls the supervisor Runtime. It reads the fleet reader secret and looks up each answer's evidence in the fleet graph, read only.](../images/deployment-topology.svg)

| Stack | Deployed by | Holds |
|-------|-------------|-------|
| `AgentCore-fleetsupervisor-default` | `supervisor-agent/agent.sh deploy` | The `supervisor` Runtime and its role |
| `FleetUi` | `ui/deploy.sh deploy` | The UI function, its streaming function URL, the Cognito user pool, and the function's role |

The deploy runs in this order.

1. **Load the graph:** `pipeline/setup.sh` builds the fleet graph and the chunk indexes. [Pipeline](pipeline.md) covers the stages.
2. **Create the read-only user:** An admin creates `fleet_reader` on the fleet database, with the `reader` role and, on Aura, the `graphql_app_read_only_<AURA_ID>` role.
3. **Create the secrets:** `uv run fleet-supervisor-secrets` creates `fleet/neo4j-reader` and `fleet/memory-neo4j` and prints their two ARN lines. Add both lines to the shared `.env`.
4. **Deploy the supervisor:** `supervisor-agent/agent.sh deploy` deploys its Runtime and writes `AGENT_ARN` to the shared `.env`.
5. **Deploy the UI:** `ui/deploy.sh deploy` deploys the `FleetUi` stack to the runtime's region and prints its URL. `ui/deploy.sh add-user EMAIL` adds each user.

The [supervisor README](../../supervisor-agent/README.md#create-the-secrets)
covers steps 2 and 3.

## The supervisor Runtime

`supervisor-agent/agent.sh deploy` wraps the AgentCore CLI. The project in
`agentcore/agentcore.json` is `fleetsupervisor`, with one runtime,
`supervisor`.

- **Package:** The Runtime is a CodeZip on Python 3.12 for arm64, with `main.py` as the entrypoint on port 8080.
- **Settings:** The deploy reads the Neo4j URIs, user names, and database names from the shared `../.env` and passes them to the Runtime. Synth refuses a URI that does not use `neo4j+s://` or `bolt+s://`.
- **Secrets:** `NEO4J_PASSWORD_SECRET_ARN` and `MEM_NEO4J_PASSWORD_SECRET_ARN` name the fleet and memory secrets. Each secret is a JSON object with a `password` key and an optional `username` key. The Runtime reads each secret once per process and caches each one on its own. When Neo4j rejects the memory password or the fleet graph password, the same request reads only that secret again. The other secret stays cached. Memory builds once more with the new password, and the graph tools and the schema fetch run again with it. `graph_query_tool` asks Claude for the Cypher again, so the second query can differ.
- **User names:** A secret's `username` key replaces `NEO4J_USERNAME` or `MEM_NEO4J_USERNAME`. The shared `.env` names the admin user the pipeline writes as, and the fleet secret names the read-only user the Runtime reads as.
- **IAM:** The CDK stack grants `secretsmanager:GetSecretValue` on exactly those two ARNs and checks that each is a complete secret ARN. It grants no `kms:Decrypt`, so the secrets must use the AWS managed key.
- **Secret guard:** The deploy refuses to run when a `.env*`, `.mcp-credentials*.json`, `.agentcore.json`, `credentials*.json`, or `*.pem` file or a `venv/` folder sits in the agent folder, because the CodeZip would ship it.

## The hosted UI

`ui/deploy.sh deploy` runs the CDK app in `ui/infra/`. It uses the account's
existing CDK bootstrap.

- **Function:** The function is an arm64 container image built from `ui/Dockerfile`. Lambda Web Adapter runs the app in response stream mode. The function gets 2048 MB and a 15-minute timeout, which covers the stream reader's 300-second wait for each read.
- **Function URL:** The URL has no IAM auth and streams each answer. The app checks the Cognito session on every route except login, its callback, and the `/ready` check.
- **Cognito:** The user pool allows no self sign-up. The app client is public, with no secret, and uses the authorization code grant with the `openid` scope. A sign-in lasts one hour, the ID token's lifetime.
- **Client ID:** The app client's callback needs the function URL, so the function cannot take the client ID without a dependency cycle. An SSM parameter holds the ID, and the function gets the parameter's name and reads it at startup.
- **Settings:** The deploy reads `AGENT_ARN` and the fleet graph settings from the shared `.env`. The fleet password comes from `NEO4J_PASSWORD_SECRET_ARN`, which must be in the runtime's region.
- **IAM:** The role can invoke only the `AGENT_ARN` runtime on its `DEFAULT` endpoint, read only the fleet secret and the client ID parameter, and write its own logs. It has no managed policies.

The [UI README](../../ui/README.md#deploy-to-the-cloud) covers the commands.

## Runtime start and TLS

The Runtime starts Python under `opentelemetry-instrument`, which imports
botocore and urllib3 before `main.py` runs. The agent injects `truststore`
only when urllib3, botocore, requests, httpx, and neo4j are not yet imported.
In the Runtime they are, so the agent logs "Skipping truststore". TLS then
falls back to each library's default CA store. Botocore and httpx use the
certifi bundle, and the neo4j driver loads the system CAs. To catch an
import-order failure before a deploy, run the local start check in the
[supervisor README](../../supervisor-agent/README.md#check-the-runtime-start-locally).

## Teardown

Teardown runs in reverse order.

- **UI:** `ui/deploy.sh destroy` deletes the `FleetUi` stack, its user pool and users, and its log group. It asks first, and `--yes` skips the prompt. It works after the supervisor is gone. The image stays in the CDK bootstrap repository.
- **Supervisor:** `supervisor-agent/agent.sh destroy` removes the Runtime, its stack, and its log groups. It checks the account first and fails while the stack still exists. `--yes` skips the prompt.
- **Secrets and user:** Destroy leaves the two secrets and the `fleet_reader` user in place. The [supervisor README](../../supervisor-agent/README.md#remove-the-secrets-and-the-reader) shows how to remove them.

The Neo4j databases live outside the account, so teardown leaves the fleet
graph and the memory graph in place.
