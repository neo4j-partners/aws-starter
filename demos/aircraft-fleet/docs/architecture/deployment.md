# Deployment Architecture

The fleet demo deploys three CloudFormation stacks into one AWS account and
reads two Neo4j databases outside it. The order matters. The supervisor's
deploy reads outputs from the MCP server stack, and both agents need the
fleet graph loaded before they can answer. Every Runtime reads its Neo4j
password from Secrets Manager, so no password appears in a template, an
environment variable, or a deployment package.

![Fleet deployment topology: the developer machine runs five deploy steps and a teardown into three stacks in us-east-1, with two Neo4j Aura databases outside the account](../images/deployment-topology.svg)

| Stack | Deployed by | Holds |
|-------|-------------|-------|
| `neo4j-mcp-server-fleet` | `neo4j-mcp-server/deploy.py --env fleet` | The Gateway, the MCP server Runtime, Cognito, and the MCP password secret |
| `AgentCore-AircraftFleet-default` | `graphrag-agent/agent.sh deploy` | The `graphrag_agent` Runtime and its role |
| `AgentCore-fleetsupervisor-default` | `supervisor-agent/agent.sh deploy` | The `supervisor` Runtime, its role, and the `fleet-gateway` credential provider |

The deploy runs in this order.

1. **Load the graph:** `pipeline/setup.sh` builds the fleet graph and the chunk indexes. [Pipeline](pipeline.md) covers the stages.
2. **Deploy the MCP server:** `./deploy.py --env fleet` deploys the MCP server stack. `./deploy.py --env fleet credentials` writes `.mcp-credentials.fleet.json`.
3. **Copy the credentials:** `scripts/sync-credentials.sh` copies that file to `demos/aircraft-fleet/.mcp-credentials.json`.
4. **Deploy the GraphRAG agent:** `graphrag-agent/agent.sh deploy` deploys its Runtime.
5. **Deploy the supervisor:** `supervisor-agent/agent.sh deploy` deploys its Runtime and the `fleet-gateway` provider.

The GraphRAG agent does not use the MCP server, so it can deploy after step 1.

## The MCP server deployment

The `fleet` deployment is a named deployment of
[`neo4j-mcp-server/`](../../../../neo4j-mcp-server/). `--env fleet` reads
`.env.fleet`, adds `-fleet` to the stack name, and writes
`.mcp-credentials.fleet.json`. The root
[architecture document](../../../../docs/ARCHITECTURE.md) covers the stack
itself.

- **Server:** The image is `mcp-neo4j-cypher`, the Python FastMCP server from `neo4j-partners/mcp-neo4j`. Docker buildx builds it for arm64 from the folder in `NEO4J_MCP_REPO`, then adds the Secrets Manager entrypoint from `neo4j-mcp-server/image/`.
- **Image tags:** Each build gets the git short SHA and `latest`. `IMAGE_TAG` overrides the SHA tag.
- **Read-only:** The container runs with `NEO4J_READ_ONLY=true`, so the supervisor gets only `get_neo4j_schema` and `read_neo4j_cypher`.
- **Password:** `deploy.py` writes the password to the secret `<stack>/neo4j-password` and passes only the ARN to the stack. The Runtime gets the ARN as `NEO4J_PASSWORD_SECRET_ARN`. At startup, the image entrypoint reads the password with the Runtime role, which can read only that secret.
- **Tokens:** Cognito issues 24-hour access tokens to the machine client, with the scope `neo4j-mcp-server-fleet-mcp/invoke`.

`NEO4J_USERNAME` in `.env.fleet` names the read-only Neo4j user
`fleet_reader`, not the admin user. The MCP server already refuses writes,
so the read-only user is a second guard. `./deploy.py redeploy` replaces
only the image. A change to the Neo4j settings needs a full `./deploy.py
--env fleet`.

## The GraphRAG agent Runtime

`graphrag-agent/agent.sh deploy` wraps the AgentCore CLI. The project in
`agentcore/agentcore.json` is `AircraftFleet`, with one runtime,
`graphrag_agent`.

- **Package:** The Runtime is a CodeZip on Python 3.12 for arm64, with `main.py` as the entrypoint on port 8080.
- **Settings:** The deploy reads the Neo4j URIs, user names, and database names from the shared `../.env` and passes them to the Runtime.
- **Secrets:** `NEO4J_PASSWORD_SECRET_ARN` and `MEM_NEO4J_PASSWORD_SECRET_ARN` name the fleet and memory passwords. Each secret is a JSON object with a `password` key. The agent reads each one once at startup.
- **User names:** A secret's optional `username` key replaces `NEO4J_USERNAME` or `MEM_NEO4J_USERNAME`. The shared `.env` names the admin user the pipeline writes as, and the secret names the read-only user the agent reads as.
- **IAM:** The CDK stack grants `secretsmanager:GetSecretValue` on exactly those two ARNs and checks that each is a complete secret ARN. It grants no `kms:Decrypt`, so the secrets must use the AWS managed key.
- **Secret guard:** The deploy refuses to run when a `.env*` or `.mcp-credentials*.json` file sits in the agent folder, because the CodeZip would ship it.

## The supervisor Runtime

`supervisor-agent/agent.sh deploy` deploys the `fleetsupervisor` project with
one runtime, `supervisor`. The supervisor reaches the fleet graph through the
Gateway, so it needs no fleet password. Its one secret ARN is
`MEM_NEO4J_PASSWORD_SECRET_ARN`. That secret's optional `username` key
works the same way.

The Runtime gets its Gateway token from AgentCore Identity, through an OAuth2
credential provider named `fleet-gateway`. The AgentCore CLI creates or
updates that provider from a credentials entry in `agentcore.json` before CDK
runs, and the construct grants the Runtime access only while the entry
exists. A deploy without the entry deletes the provider. `agent.sh deploy`
handles this for each deploy.

1. **Read the inputs:** The client ID and scope come from the fleet credentials file. The discovery URL comes from the MCP stack's `CognitoDiscoveryUrl` output.
2. **Declare the provider:** The script adds the `fleet-gateway` entry and passes the client secret to the CLI on stdin, never in argv. The CLI stores the secret in `agentcore/.env.local`.
3. **Deploy:** The CLI deploys the stack. The Runtime role gets a grant on the provider and on the memory secret.
4. **Restore:** An exit trap removes the secret line and restores the tracked `agentcore.json`, which never holds account details.

A bare `agentcore deploy` from the supervisor folder skips step 2 and deletes
the provider. Always deploy through `agent.sh`.

## Teardown

Teardown runs in reverse order.

- **Agents:** `agent.sh destroy` in each agent folder removes its Runtime and stack. The GraphRAG destroy checks the account first and waits for `DELETE_COMPLETE`. `--yes` skips the prompt. The supervisor destroy also removes the `fleet-gateway` provider.
- **MCP server:** `./deploy.py --env fleet cleanup` deletes the MCP server stack, the Neo4j password secret, and, after a separate confirmation, the ECR repository.

The Neo4j databases live outside the account, so teardown leaves the fleet
graph and the memory graph in place.
