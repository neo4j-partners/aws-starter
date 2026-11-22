# Aircraft Fleet Supervisor Agent

This Strands supervisor agent answers questions about the aircraft fleet graph.
It hands each question to one or both specialist agents. The specialists query
Neo4j through the Neo4j MCP server and AgentCore Gateway.

![Supervisor agent request flow](../docs/images/supervisor-request-flow.svg)

## Overview

- **Supervisor:** The supervisor is a Strands `Agent`. Its two tools are the specialists, and the model picks one or both from the tool descriptions.
- **Maintenance Agent:** This specialist handles faults, components, sensors, and reliability.
- **Operations Agent:** This specialist handles flights, delays, routes, and airports. It also takes general questions, such as the schema or simple counts.
- **Gateway tools:** Both specialists use the same two tools, `get_neo4j_schema` and `read_neo4j_cypher`, through the AgentCore Gateway.
- **Memory:** The supervisor remembers each session and what it learns about each user. Memory lives in its own Neo4j database.

## Features

- **Parallel specialists:** The supervisor can call both specialists, or one specialist twice, in the same turn. Each call gets a fresh specialist `Agent`, so calls never wait on each other.
- **Session recovery:** Each Gateway tool rebuilds its MCP session and retries once when the session drops.
- **Error scrubbing:** The tools replace raw database errors before the model sees them. No database address reaches an answer.
- **Two credential paths:** Local runs read a credentials file. The deployed runtime gets its Gateway token from AgentCore Identity and holds no client secret.
- **Token refresh:** The cloud path caches the M2M token until shortly before it expires. A rejected token triggers one fresh fetch and one retry.
- **Streaming:** The server streams `agent`, `tool`, `chunk`, `complete`, and `error` events over SSE.
- **Safe deploys:** The deploy refuses to zip any credentials file. The Gateway client secret never appears on a command line.

## Quick start

Run these commands from `demos/aircraft-fleet/supervisor-agent/`:

```bash
uv sync
../../../scripts/sync-credentials.sh   # writes ../.mcp-credentials.json

./agent.sh start                       # terminal 1: serves http://localhost:7071
./agent.sh test-maintenance            # terminal 2: a question for Maintenance
./agent.sh test-operations             # a question for Operations
uv run fleet-supervisor-cli "Compare fault counts with delay counts"
```

## Prerequisites

- **Python:** You need Python 3.12 and the `uv` package manager.
- **AWS:** You need AWS credentials with Bedrock access to Claude Sonnet 5.5.
- **Graph:** You need the fleet graph loaded by the [pipeline](../pipeline/).
- **MCP server:** You need a `fleet` Neo4j MCP server deployment that points at the same Neo4j database. Run `./deploy.py --env fleet` and `./deploy.py --env fleet credentials` from `neo4j-mcp-server/`.
- **Memory database:** You need a second Neo4j database or instance for memory. It can be empty. Keep it apart from the fleet graph.

## Routing

The supervisor model reads the two tool descriptions in
`fleet_supervisor/core/agents.py` and the prompt in
`fleet_supervisor/core/prompts.py`. A question that spans both domains calls
both specialists, and the supervisor combines their answers.

| Question mentions | Goes to |
|-------------------|---------|
| maintenance, faults, failures, components, systems, sensors, readings, severity | Maintenance Agent |
| flights, delays, delay causes, routes, airports, operators, schedules, on-time performance | Operations Agent |
| the schema, simple counts, or other general topics | Operations Agent |

## Gateway connection

- **Shared client:** The model, the Gateway MCP client, and the tools are created on the first request and shared by later requests.
- **Session ends between requests:** The next request opens a new session.
- **Session ends during a request:** A call in flight returns an error result, or a later call raises `MCPClientInitializationError`. In either case, `GatewayTool` rebuilds the client and retries once.
- **One rebuild:** A rebuild happens only if the failed client is still the current one. Other calls reuse the new client. The old client stops when its last call finishes.
- **Logging:** Each rebuild is logged at WARNING with the session ID and the cause class.
- **Retry fails:** The specialist gets "The graph database is unavailable right now." The details stay in the server log.
- **Stable specs:** The tool specs come from the first client, so a rebuild never changes what the model sees.

### Tool errors the model sees

The Neo4j MCP server returns the driver's error message as the tool result.
That message can name the database address. `GatewayTool` replaces every error
result before the model sees it and logs the original.

| Error | What the model gets |
|-------|---------------------|
| The server rejected the query: a syntax error, an unknown function or procedure, a bad argument, or a refused write | The Neo4j code and message, cut to 500 characters and without addresses, so the model can fix its Cypher |
| The query hit the transaction timeout | "The query took too long and was stopped." |
| Neo4j, the MCP server, or the Gateway could not be reached, or auth failed | "The graph database is unavailable right now." |
| Any other error | "The graph database returned an error." |

`fleet_supervisor/core/tool_errors.py` classifies the text by the Neo4j code
and the driver's connection messages. The wording matches the GraphRAG agent.

## Gateway credentials

The environment picks one of two paths.

- **Local:** The agent reads `demos/aircraft-fleet/.mcp-credentials.json`. Set `MCP_CREDENTIALS_FILE` to use another file.
- **Local token:** The agent sends the OAuth `client_credentials` request to the `token_url` in that file. It does not use OAuth discovery, so the secret goes only to that URL.
- **Cloud:** When `CREDENTIAL_FLEET_GATEWAY_NAME` or `GATEWAY_URL` is set, the agent gets an M2M token from the AgentCore Identity provider. Both must be set, or the agent stops with an error that names the missing one.
- **Cloud token:** Each request fetches the token with its own workload access token. The cache is shared because the token is M2M and not tied to a user.
- **File location:** The credentials file sits outside this folder on purpose, because `agentcore deploy` zips this whole folder.

## Conversation memory

![Conversation memory lifecycle](../docs/images/memory-lifecycle.svg)

- **Package:** Memory uses `neo4j-agent-memory` 0.8.0+fleet.8, a build of the `neo4j-partners/agent-memory` fork. `pyproject.toml` pins the wheel URL, and `uv.lock` records its sha256.
- **Extraction model:** The extractor runs on Claude Sonnet 5.5. It sends no temperature and lets the model choose the tool, because Sonnet 5.5 rejects both.
- **What it stores:** Memory keeps the user and assistant text of each turn. It does not store specialist calls.
- **One client per process:** The client opens on the first request and closes at shutdown. Each request gets its own session manager on it.
- **Background extraction:** Entity extraction runs after the reply. The health check reports busy until it ends, so AgentCore Runtime keeps the session alive.
- **Shutdown:** Shutdown waits up to 30 seconds for open requests to write their memory, then closes the client. The whole close takes at most about 100 seconds.
- **Lost work:** An extraction still running at the deadline is lost. The stored message keeps its text without entities.
- **Password rotation:** If Neo4j rejects the memory password, the server reads the secret again and reopens the client with it.

## Run locally

- **Shared .env:** The server loads `demos/aircraft-fleet/.env` at startup. Set `FLEET_ENV_FILE` to use another file. A value already set in the environment wins.
- **Memory settings:** Set `MEM_NEO4J_URI` and `MEM_NEO4J_PASSWORD`. Set `MEM_NEO4J_USERNAME` and `MEM_NEO4J_DATABASE` too if they are not `neo4j`. The server stops at startup if the URI or the password is missing.
- **Server:** `./agent.sh start` runs `uv run fleet-supervisor-server` on port 7071, beside the GraphRAG agent on 7070. Set `AGENT_PORT` to change it.
- **Runtime entrypoint:** `uv run python main.py` starts the same server on port 8080, the port AgentCore Runtime uses.

### Events

| Event | Meaning |
|-------|---------|
| `{"type": "agent", "name": ...}` | A specialist was called |
| `{"type": "tool", "name": ...}` | A specialist called a Gateway tool |
| `{"type": "chunk", "data": ...}` | Text of the supervisor's answer |
| `{"type": "complete"}` | The answer is finished |
| `{"type": "error", "error": ...}` | The request failed. The message is generic, and the details are in the server log. |

## Deploy

```bash
./agent.sh deploy                  # takes several minutes
./agent.sh invoke-cloud "What are the most common maintenance faults?"
./agent.sh invoke-cloud "Which routes have the most delays?"
```

### Deploy settings

- **Memory:** Set the `MEM_NEO4J_*` settings in `demos/aircraft-fleet/.env` before the first deploy. `MEM_NEO4J_URI` must use `neo4j+s://` or `bolt+s://`.
- **Gateway:** The deploy reads `GATEWAY_URL` and `GATEWAY_SCOPES` from `gateway_url` and `scope` in the fleet credentials file. `GATEWAY_URL` must use `https://`.
- **Password secret:** `MEM_NEO4J_PASSWORD_SECRET_ARN` must be a complete secret ARN. The runtime role can read only that secret.
- **Parsing:** The files are parsed, not sourced. A value exported in the shell wins.
- **Validation:** Synth stops with one error that lists every missing or malformed setting.

### Gateway credential provider

- **Declared per deploy:** `./agent.sh deploy` declares the `fleet-gateway` OAuth credential for that one deploy. The CLI creates or updates the provider before CDK runs.
- **Sources:** The client ID, scope, and secret come from the fleet credentials file. The discovery URL comes from the MCP server stack's `CognitoDiscoveryUrl` output.
- **Secret handling:** The script passes the secret on stdin. The CLI stores it, encrypted, in `agentcore/.env.local`, which git ignores and the zip leaves out.
- **Cleanup:** When the deploy ends, on success, error, or Ctrl+C, the script removes that line and restores the tracked `agentcore.json`.
- **Grants:** The runtime role reads the provider through the construct's `bedrock-agentcore-identity!*` grant, and the memory secret through its own grant.

Never run a bare `agentcore deploy` in this folder. Without the entry, the CLI
treats the provider as orphaned and deletes it. If it happens, run
`./agent.sh deploy` again to recreate the provider and the grants.

### How the deploy works

- **Code zip:** The zip holds this folder except `.venv`, `agentcore/`, `__pycache__`, and `.pytest_cache`. The runtime runs `main.py`.
- **Secret guard:** `./agent.sh deploy` refuses to run if any `.env*`, `.mcp-credentials*.json`, `.agentcore.json`, `credentials*.json`, or `*.pem` file, or a `venv/` folder, is inside this folder.
- **CDK dependencies:** `deploy` and `destroy` run `npm ci` in `agentcore/cdk` when the install is missing, incomplete, or older than `package-lock.json`. `configure` always runs it.

### Remove the deployment

`./agent.sh destroy` removes the runtime, its stack, and the Gateway credential provider.

- **Confirmation:** It asks first. Pass `--yes` to skip the question.
- **Account check:** It confirms that the active credentials belong to the account in `agentcore/aws-targets.json`, before it asks and again before its final lookups.
- **How it works:** The CLI has no destroy command. The script removes the runtime from the spec and deploys, which deletes the stack and the provider.
- **Final check:** It reads `agentcore status` and looks up the stack and the provider in AWS by name. If anything remains, it prints the command that deletes it and exits with an error.
- **Lost local state:** If `agentcore/.cli/` is lost, destroy still deletes the stack. The AWS check then names the leftover provider.

### Upgrade a checkout that already deployed

Git used to track `agentcore/aws-targets.json`, and the first deploy edited it.
A `git pull` in that checkout can stop with "Your local changes to the
following files would be overwritten by merge", or with "cannot pull with
rebase: You have unstaged changes".

Keep the file, because destroy needs it. Run these two commands from this
folder in one shell. The first backs the file up, prints the backup name, then
discards the change and pulls. The second restores the file only if the backup
was complete:

```bash
backed_up= && backup=$(mktemp) && cp agentcore/aws-targets.json "$backup" && backed_up=1 && echo "Backup: $backup" && git checkout -- agentcore/aws-targets.json && git pull
[ "${backed_up:-}" = 1 ] && cp "$backup" agentcore/aws-targets.json && rm -f "$backup"
```

If the last `cp` fails, copy the backup back by hand from the printed name. If
the backup is lost, recreate the file with the account and region you deployed
to:

```json
[{"name": "default", "account": "<12-digit account ID>", "region": "<region>"}]
```

## Commands

| Command | Description |
|---------|-------------|
| `./agent.sh start` / `stop` | Start or stop the agent locally on port 7071 |
| `./agent.sh test ["question"]` | Send a question to the local agent. The default asks for the schema. |
| `./agent.sh test-maintenance` | Send a question that goes to the Maintenance Agent |
| `./agent.sh test-operations` | Send a question that goes to the Operations Agent |
| `./agent.sh configure` | Create the AgentCore project if it is missing, and install its CDK dependencies |
| `./agent.sh deploy` | Deploy to AgentCore Runtime |
| `./agent.sh status` | Show the deployment status |
| `./agent.sh logs [30m]` | Show runtime logs from the given window |
| `./agent.sh invoke-cloud ["question"]` | Call the deployed agent through `agentcore invoke --runtime supervisor` |
| `./agent.sh load-test [N]` | Send a random test question to the deployed agent every N seconds. It reads the ARN from `AGENT_ARN` or `agentcore status`. |
| `./agent.sh destroy [--yes]` | Remove the runtime, its stack, and the Gateway credential provider |

## Layout

| Path | Purpose |
|------|---------|
| `main.py` | The AgentCore entrypoint. It starts the server on port 8080. |
| `fleet_supervisor/server.py` | The `BedrockAgentCoreApp`, its entrypoint, and `main()` |
| `fleet_supervisor/core/config.py` | The model, region, token limit, effort, and local port |
| `fleet_supervisor/core/prompts.py` | The supervisor prompt and the two specialist prompts |
| `fleet_supervisor/core/agents.py` | The supervisor and `SpecialistTool` |
| `fleet_supervisor/core/model.py` | The Bedrock model factory |
| `fleet_supervisor/core/credentials.py` | The local or cloud Gateway credentials |
| `fleet_supervisor/core/mcp.py` | The Gateway MCP client, its bearer-token auth, and the tool filter |
| `fleet_supervisor/core/gateway_tools.py` | `GatewayTool`, with the rebuild, retry, and error scrubbing |
| `fleet_supervisor/core/tool_errors.py` | The error classifier |
| `fleet_supervisor/core/events.py` | The mapping from Strands stream events to client events |
| `fleet_supervisor/client/cli.py` | `fleet-supervisor-cli`, which asks the local server one question |
| `fleet_supervisor/client/invoke.py` | `fleet-supervisor-invoke`, for cloud calls and load testing |
| `fleet_supervisor/client/queries.txt` | 20 test questions: 10 for maintenance and 10 for operations |
| `agentcore/` | The AgentCore CLI project and its CDK app |
| `tests/` | Offline unit tests |
| `agent.sh` | The command wrapper for local runs and deployment |

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MODEL_ID` | `global.anthropic.claude-sonnet-5-5` | The Bedrock model for all three agents |
| `AWS_REGION` | `us-east-1` | The Bedrock and AgentCore region |
| `MAX_TOKENS` | `16000` | The output token limit |
| `MODEL_EFFORT` | `high` | The adaptive thinking effort |
| `AGENT_PORT` | `7071` | The local server port |
| `MCP_CREDENTIALS_FILE` | `../.mcp-credentials.json` | The local credentials file |
| `CREDENTIAL_FLEET_GATEWAY_NAME` | unset | The AgentCore Identity provider name. The deploy sets it. It selects the cloud path. |
| `GATEWAY_URL` | unset | The Gateway endpoint for the cloud path. It must use `https://`. |
| `GATEWAY_SCOPES` | unset | Space-separated OAuth scopes for the cloud path |
| `MEM_NEO4J_URI` | required | The memory database URI |
| `MEM_NEO4J_USERNAME` | `neo4j` | The memory database user. The secret's `username` key wins when it has one. |
| `MEM_NEO4J_DATABASE` | `neo4j` | The memory database name |
| `MEM_NEO4J_PASSWORD` | unset | Local runs only. Required when `MEM_NEO4J_PASSWORD_SECRET_ARN` is unset. |
| `MEM_NEO4J_PASSWORD_SECRET_ARN` | unset | Set by the deploy. The secret holds a JSON object with a `password` key and an optional `username` key. |
| `FLEET_ENV_FILE` | `../.env` | The shared env file the server loads at startup |

## Tests

The tests run offline. They make no Bedrock, Gateway, or Neo4j calls.

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

To try the agent without the Gateway, run `neo4j-mcp-server/local.sh start`.
The local server has no auth and no `___` tool prefix. Point a test launcher at
it and loosen `SPECIALIST_TOOL_FILTERS` to the bare tool names.

## Example questions

- **Maintenance:** Try "Which components have the most failures?" or "What is the reliability history of avionics?"
- **Operations:** Try "What are the most common delay causes?" or "Which airports have the highest traffic?"
- **Both:** The question "Compare maintenance fault counts with flight delay counts" calls both specialists.
- **General:** The question "What is the database schema?" goes to the Operations Agent.

See `fleet_supervisor/client/queries.txt` for all 20 questions.

## See also

- **Fleet demo:** The [fleet README](../README.md) shows how the pipeline and both agents fit together.
- **Single agent:** The [GraphRAG agent](../graphrag-agent/) answers the same questions with a direct Neo4j driver.
- **Architecture:** The [supervisor architecture document](../docs/architecture/supervisor-agent.md) explains routing, Gateway reconnects, and the token paths. The [deployment document](../docs/architecture/deployment.md) covers the `fleet-gateway` provider.
