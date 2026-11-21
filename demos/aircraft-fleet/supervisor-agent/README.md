# Aircraft Fleet Supervisor Agent

This Strands supervisor agent answers questions about the aircraft fleet graph.
It hands each question to one or both specialist agents. The specialists query
Neo4j through the Neo4j MCP Gateway.

## Overview

- **Supervisor:** The supervisor is a Strands `Agent`. Its two tools are the specialists, and the model picks one or both from the tool descriptions.
- **Maintenance Agent:** This specialist handles faults, components, sensors, and reliability.
- **Operations Agent:** This specialist handles flights, delays, routes, and airports. It also takes general questions, such as the schema or simple counts.
- **Shared tools:** Both specialists use the same two Gateway tools: `get_neo4j_schema` and `read_neo4j_cypher`.
- **Streaming:** The server streams events as the answer is produced. Clients see which specialists ran and which tools they called.

## Quick start

Run these commands from `demos/aircraft-fleet/supervisor-agent/`:

```bash
uv sync
../../../scripts/sync-credentials.sh   # writes ../.mcp-credentials.json

./agent.sh start                       # Terminal 1: serves http://localhost:7071
./agent.sh test-maintenance            # Terminal 2: a question for Maintenance
./agent.sh test-operations             # a question for Operations
```

## Architecture

```
                        User query
                            |
                        Supervisor
              calls one or both specialist tools
                            |
              +-------------+-------------+
              |                           |
       Maintenance Agent          Operations Agent
       faults, components         flights, delays
       sensors, reliability       routes, airports
              |                           |
              +-------------+-------------+
                            |
          AgentCore Gateway -> Neo4j MCP Server -> Neo4j
```

### Routing

The supervisor model reads the two tool descriptions in
`fleet_supervisor/core/agents.py` and the supervisor prompt in
`fleet_supervisor/core/prompts.py`. A question that spans both domains
calls both specialists, and the supervisor combines their answers.

| Question mentions | Goes to |
|-------------------|---------|
| maintenance, faults, failures, components, systems, sensors, readings, severity | Maintenance Agent |
| flights, delays, delay causes, routes, airports, operators, schedules, on-time performance | Operations Agent |
| the schema, simple counts, or other general topics | Operations Agent |

### One Agent per specialist call

The supervisor runs tool calls in parallel, so it can call the same specialist
twice in one turn. A Strands `Agent` serves one call at a time. For that
reason, `SpecialistTool` builds a fresh specialist `Agent` for every call.
Parallel calls never wait on each other.

### Gateway connection

The model, the Gateway MCP client, and the Gateway tools are created on the
first request and shared by later requests. If the MCP session ends, the next
request opens a new one.

### Gateway session recovery

The Gateway can also end the MCP session while a request is running. Each
Gateway tool is wrapped in `GatewayTool`, which handles both ways a call can
fail then:

- A call already in flight returns an error result while the session is down.
- A later call raises `MCPClientInitializationError` before it is sent.

In either case, the tool rebuilds the MCP client and retries the call once. A
rebuild happens only if the failed client is still the current one. Calls that
find the session down after another call rebuilt it reuse the new client. The
old client stops when its last call finishes. The rebuild is logged at WARNING
with the request's session ID and the cause class.

If the retry fails too, or the rebuild fails, the specialist gets a fixed
message: "The graph database is unavailable right now." The error details stay
in the server log. This includes an auth failure that persists after the
forced token refresh. The next request rebuilds the client again.

The tool specs come from the first client and never change, so a rebuild never
changes what the model sees. If a rebuilt client lacks a tool, calls to that
tool get the same fixed message.

### Tool errors the model sees

The Neo4j MCP server returns the driver's error message as the tool result.
That message can name the database address, and the specialist could quote it
to the user. So `GatewayTool` replaces every error result before the model
sees it. The original text goes to the server log.

| Error | What the model gets |
|-------|---------------------|
| The server rejected the query: a syntax error, an unknown function or procedure, a bad argument, or a refused write | The Neo4j code and message, cut to 500 characters and without addresses, so the model can fix its Cypher |
| The query hit the transaction timeout | "The query took too long and was stopped." |
| Neo4j, the MCP server, or the Gateway could not be reached, or auth failed | "The graph database is unavailable right now." |
| Any other error | "The graph database returned an error." |

The wording matches the graphrag agent's tools. The supervisor sees only the
error text, so `fleet_supervisor/core/tool_errors.py` classifies it by the Neo4j code and the
driver's connection messages.

## Prerequisites

1. **Python:** You need Python 3.12 and the `uv` package manager.
2. **AWS:** You need the AWS CLI configured, with Bedrock access to Claude Sonnet 5.5.
3. **Graph:** You need the fleet graph loaded into Neo4j by [`demos/aircraft-fleet/pipeline/`](../pipeline/).
4. **MCP server:** You need a `fleet` Neo4j MCP server deployment that points at the same Neo4j database. Run these commands from the repo root:

   ```bash
   cd neo4j-mcp-server
   ./deploy.py --env fleet
   ./deploy.py --env fleet credentials
   ```

5. **Memory database:** You need a second Neo4j database or instance for the supervisor's conversation memory. It can be empty. The agent creates its schema on first connect. Keep it separate from the fleet graph.

## Gateway credentials

The agent has two ways to get a Gateway token. The environment picks one.

- **Local:** The agent reads `demos/aircraft-fleet/.mcp-credentials.json`. The path is resolved from the package, so it works from any working directory. Set `MCP_CREDENTIALS_FILE` to use another file.
- **Cloud:** When `CREDENTIAL_FLEET_GATEWAY_NAME` or `GATEWAY_URL` is set, the agent gets an M2M token from the AgentCore Identity credential provider that `CREDENTIAL_FLEET_GATEWAY_NAME` names. Both must be set. If one is missing, the agent stops with an error that names it. The AgentCore CDK construct sets `CREDENTIAL_FLEET_GATEWAY_NAME` on the runtime because `./agent.sh deploy` declares the `fleet-gateway` credential. `GATEWAY_URL` gives the Gateway endpoint. The runtime holds no client secret.

On the cloud path, each request fetches the Gateway token before it starts,
because AgentCore Identity needs that request's workload access token. The
token is cached until shortly before the expiry in its `exp` claim. If the
Gateway rejects a token, the agent asks Identity for a new one, bypassing the
token vault cache, and retries once. The cache is shared by all requests,
which is valid only because the token is M2M and not tied to a user.

On the local path, the agent sends the OAuth `client_credentials` request to
the `token_url` in the credentials file. It does not use OAuth discovery, so
the client secret only goes to that URL.

The credentials file sits outside this folder on purpose. `agentcore deploy`
zips this whole folder, and `./agent.sh deploy` refuses to run if any `.env*`,
`.mcp-credentials*.json`, `.agentcore.json`, `credentials*.json`, or `*.pem`
file, or a `venv/` folder, is inside it.

## Run locally

Run these commands from `demos/aircraft-fleet/supervisor-agent/`:

```bash
uv sync
../../../scripts/sync-credentials.sh

./agent.sh start                   # Terminal 1: serves http://localhost:7071
./agent.sh test-maintenance        # Terminal 2
./agent.sh test-operations
uv run fleet-supervisor-cli "Compare fault counts with delay counts"
```

- **Memory settings:** Set `MEM_NEO4J_URI` and `MEM_NEO4J_PASSWORD` in the shared `demos/aircraft-fleet/.env`. Set `MEM_NEO4J_USERNAME` and `MEM_NEO4J_DATABASE` too if they are not `neo4j`. They point at the memory database, not the fleet graph. The server stops at startup if the URI or the password is missing.
- **Memory package:** Memory uses `neo4j-agent-memory` 0.8.0+fleet.4, a build of the `neo4j-partners/agent-memory` fork. Its entity extractor runs on Claude Sonnet 5.5. Sonnet 5.5 rejects a temperature and a forced tool choice, so the extractor sends no temperature and lets the model choose the tool. For now `pyproject.toml` pins the wheel by a local path, so `uv sync` works only where that file exists. The pin moves to the published wheel's URL before the merge. Memory stores the user and assistant text of each turn but no specialist calls, so the supervisor prompt says that a restored turn without one does not mean no specialist ran. The server holds one memory client per process. It opens on the first request and closes at shutdown. Shutdown waits up to 30 seconds for open requests to write their memory, then closes the client. Closing the memory clients takes at most about 100 seconds. An extraction still running at that deadline is lost. A client still opening when the 30-second wait ends closes itself after shutdown returns, so the process may exit first. No request used that client, so no memory is lost. Each request gets its own session manager on that client. Entity extraction runs after the reply, in the background. The health check reports busy until it finishes, so AgentCore Runtime does not stop the session in the middle of it.
- **Shared .env:** The server loads `demos/aircraft-fleet/.env` at startup. The path comes from the package, so it works from any working directory. Set `FLEET_ENV_FILE` to use another file. A value already set in the environment wins.
- **Server:** `./agent.sh start` runs `uv run fleet-supervisor-server`. Set `AGENT_PORT` to change the port.
- **Runtime entrypoint:** `uv run python main.py` starts the same server on 8080, the port AgentCore Runtime uses.
- **Port:** The default port is 7071, so the supervisor can run beside `graphrag-agent` on 7070.

### Events

The server streams JSON events over SSE:

| Event | Meaning |
|-------|---------|
| `{"type": "agent", "name": ...}` | A specialist was called |
| `{"type": "tool", "name": ...}` | A specialist called a Gateway tool |
| `{"type": "chunk", "data": ...}` | Text of the supervisor's answer |
| `{"type": "complete"}` | The answer is finished |
| `{"type": "error", "error": ...}` | The request failed. The message is generic, and the details are in the server log. |

## Deploy to AgentCore Runtime

The project lives in `agentcore/`. It was created with the AgentCore CLI, and
its runtime `codeLocation` is this folder.

The CLI also needs the CDK dependencies in `agentcore/cdk/node_modules`. Git ignores that folder, so a fresh clone has none. `./agent.sh deploy` and `./agent.sh destroy` run `npm ci` there when the install is missing or incomplete, or older than `package-lock.json`, as after a pull that changes it. `./agent.sh configure` always runs it. Where `package-lock.json` is missing, as in a project `agentcore create` has just made, each runs `npm install` instead, which writes it. To install them once by hand, run:

```bash
(cd agentcore/cdk && npm ci)
```

**Deploy settings:** Before the first deploy, set the `MEM_NEO4J_*` settings in `demos/aircraft-fleet/.env`. `./agent.sh deploy` exports them, plus `GATEWAY_URL` and `GATEWAY_SCOPES` from `gateway_url` and `scope` in the fleet credentials file. A value exported in the shell wins. The files are parsed, not sourced, and nothing else in them is exported. `agentcore/cdk/lib/cdk-stack.ts` copies the settings onto the runtime. Synth stops with one error that lists every missing or malformed setting. `GATEWAY_URL` must use `https://`, and `MEM_NEO4J_URI` must use `neo4j+s://` or `bolt+s://`. `MEM_NEO4J_PASSWORD_SECRET_ARN` must be a complete secret ARN, and the runtime role can read only that secret.

**Gateway credential provider:** `./agent.sh deploy` declares the `fleet-gateway` OAuth credential for that one deploy. It reads the client ID, scope, and secret from the fleet credentials file. It reads the discovery URL from the `CognitoDiscoveryUrl` output of the MCP server stack. The AgentCore CLI creates or updates the provider before CDK runs, because CDK cannot create it. The construct grants the runtime access to the provider, and sets `CREDENTIAL_FLEET_GATEWAY_NAME`, only while the entry exists.

The script passes the secret to the CLI on stdin, never on the command line. The CLI stores it, encrypted, in `agentcore/.env.local`, which git ignores and the code zip leaves out. When the deploy ends, the script removes that line and restores the tracked `agentcore.json`. It does this on an error or Ctrl+C too. The tracked spec never declares the credential, so it holds no account-specific values.

Never run a bare `agentcore deploy` in this folder. Without the entry, the CLI treats the provider as orphaned and deletes it, and the runtime loses its grant. If it happens, run `./agent.sh deploy` again. That recreates the provider and the grants.

The runtime role has two `secretsmanager:GetSecretValue` resources. The `bedrock-agentcore-identity!*` wildcard comes from the AgentCore construct's own grant for the credential provider, not from `cdk-stack.ts`. The other is the memory password secret. The server reads it once. If Neo4j rejects the password, the server reads the secret again and reopens the shared memory client with it.

Then run these commands:

```bash
./agent.sh deploy                  # takes several minutes
./agent.sh invoke-cloud "What are the most common maintenance faults?"
./agent.sh invoke-cloud "Which routes have the most delays?"
```

## Commands

| Command | Description |
|---------|-------------|
| `./agent.sh start` / `stop` | Start or stop the agent locally on port 7071 |
| `./agent.sh test ["question"]` | Send a question to the local agent. The default asks for the schema. |
| `./agent.sh test-maintenance` | Send a question that goes to the Maintenance Agent |
| `./agent.sh test-operations` | Send a question that goes to the Operations Agent |
| `./agent.sh configure` | Create the AgentCore project in `agentcore/` if it is missing, and install its CDK dependencies |
| `./agent.sh deploy` | Deploy to AgentCore Runtime |
| `./agent.sh status` | Show the deployment status |
| `./agent.sh logs [30m]` | Show runtime logs from the given window |
| `./agent.sh invoke-cloud ["question"]` | Call the deployed agent |
| `./agent.sh load-test [N]` | Send a random test question to the deployed agent every N seconds. The default is 5. |
| `./agent.sh destroy [--yes]` | Remove the runtime, its stack, and the Gateway credential provider. It asks first. `--yes` skips the question. |

`invoke-cloud` calls `agentcore invoke --runtime supervisor`. `load-test`
finds the runtime ARN in `AGENT_ARN`. If it is unset, it reads the ARN from
`agentcore status --json`.

Before it asks, and before any AWS change, `./agent.sh destroy` confirms that
the active AWS credentials belong to the account recorded for the target in
`agentcore/aws-targets.json`. Credentials for another account would deploy
there. The first deploy writes that file, and git ignores it. If the file is
missing, destroy stops and says to run it from the checkout that deployed.

**Upgrading a checkout that already deployed:** Git used to track
`agentcore/aws-targets.json`, and the first deploy edited it. So a `git pull`
in that checkout can stop with one of these errors:

- A merge or fast-forward pull stops with "Your local changes to the
  following files would be overwritten by merge".
- A rebase pull stops with "cannot pull with rebase: You have unstaged
  changes".

Keep the file, because destroy needs it. Run these commands from this folder
in one shell. The first command backs the file up to a temporary name and
prints it. It discards your change and pulls only after the backup is made.
The second command puts the file back, even if the pull failed, and removes
the backup. It runs only if the backup was complete, so a partial backup
never replaces the file:

```bash
backed_up= && backup=$(mktemp) && cp agentcore/aws-targets.json "$backup" && backed_up=1 && echo "Backup: $backup" && git checkout -- agentcore/aws-targets.json && git pull
[ "${backed_up:-}" = 1 ] && cp "$backup" agentcore/aws-targets.json && rm -f "$backup"
```

After the pull, git ignores the file. If that last `cp` fails, the backup is
kept, so copy it back by hand from the printed name. If the backup is lost,
recreate the file with the account and region you deployed to:

```json
[{"name": "default", "account": "<12-digit account ID>", "region": "<region>"}]
```

The CLI has no destroy command. `./agent.sh destroy` removes the runtime from
the spec and deploys. A deploy with nothing to deploy deletes the target's
stack. It also deletes each credential provider that the CLI's state records
but the spec no longer declares, and that includes the `fleet-gateway`
provider. So destroy does not declare the credential, and it needs neither the
fleet credentials file nor the MCP server stack. With no runtime in the spec,
`cdk-stack.ts` reads no deploy settings. The script then restores the tracked
spec and checks what remains. It reads `agentcore status`, and it looks up the
stack and the credential provider in AWS by name. Before those lookups, it
checks the account again, because the credentials can change during the
deploy. Credentials for another account would not see the stack or the
provider. If anything is still deployed, it
lists it with the command that deletes it and exits with an error.

The CLI's local state in `agentcore/.cli/` holds account-specific ARNs, so git
ignores it. If it is lost, destroy still deletes the stack, which the CLI
finds by name. The credential provider stays, because only that state records
it. The AWS check then names the provider and prints the command that deletes
it.

## Layout

| Path | Purpose |
|------|---------|
| `main.py` | AgentCore entrypoint. It calls `fleet_supervisor.server.main` on port 8080. |
| `fleet_supervisor/server.py` | The `BedrockAgentCoreApp`, its entrypoint, and `main()`, run by `fleet-supervisor-server` |
| `fleet_supervisor/core/config.py` | Model ID, region, token limit, effort, and local port. Environment variables can override them. |
| `fleet_supervisor/core/prompts.py` | The supervisor prompt and the two specialist system prompts |
| `fleet_supervisor/core/agents.py` | The supervisor and `SpecialistTool` |
| `fleet_supervisor/core/model.py` | The Bedrock model factory |
| `fleet_supervisor/core/credentials.py` | Picks the local or cloud Gateway credentials |
| `fleet_supervisor/core/mcp.py` | The Gateway MCP client, its bearer-token auth, and the tool filter |
| `fleet_supervisor/core/gateway_tools.py` | `GatewayTool`, which reconnects and retries once when the MCP session ends, and scrubs error results |
| `fleet_supervisor/core/tool_errors.py` | Classifies a tool's error text into the result the model may see |
| `fleet_supervisor/core/events.py` | Maps Strands stream events to the client events |
| `fleet_supervisor/client/cli.py` | Asks the local server one question, run by `fleet-supervisor-cli` |
| `fleet_supervisor/client/invoke.py` | Cloud calls and load testing, run by `fleet-supervisor-invoke` |
| `fleet_supervisor/client/queries.txt` | 20 test questions: 10 for maintenance and 10 for operations |
| `agentcore/` | The AgentCore CLI project and its CDK app |
| `tests/` | Offline unit tests |
| `agent.sh` | The command wrapper for local runs and deployment |

The deployed code zip holds this whole folder except `.venv`, `agentcore/`,
`__pycache__`, and `.pytest_cache`. The runtime runs `main.py`.

AgentCore runs a file, not a module, and CodeZip installs the dependencies
but not the project. The package imports because its folder sits next to
`main.py`. Locally, `uv sync` installs the package for the console scripts.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MODEL_ID` | `global.anthropic.claude-sonnet-5-5` | Bedrock model for all three agents |
| `AWS_REGION` | `us-east-1` | Bedrock and AgentCore region |
| `MAX_TOKENS` | `16000` | Output token limit |
| `MODEL_EFFORT` | `high` | Adaptive thinking effort |
| `AGENT_PORT` | `7071` | Local server port |
| `MCP_CREDENTIALS_FILE` | `../.mcp-credentials.json` | Local credentials file |
| `CREDENTIAL_FLEET_GATEWAY_NAME` | unset | AgentCore Identity provider name. The AgentCore construct sets it on deploy. Setting it, or `GATEWAY_URL`, selects the cloud path. |
| `GATEWAY_URL` | unset | Gateway endpoint for the cloud path. It must use `https://`. On deploy it comes from `gateway_url` in the credentials file. |
| `GATEWAY_SCOPES` | unset | Space-separated OAuth scopes for the cloud path. On deploy they come from `scope` in the credentials file. |
| `MEM_NEO4J_URI` | unset, required | Memory database URI. The deploy requires `neo4j+s://` or `bolt+s://`. |
| `MEM_NEO4J_USERNAME` | `neo4j` | Memory database user |
| `MEM_NEO4J_DATABASE` | `neo4j` | Memory database name |
| `MEM_NEO4J_PASSWORD` | unset | Local runs only. Required when `MEM_NEO4J_PASSWORD_SECRET_ARN` is unset. |
| `MEM_NEO4J_PASSWORD_SECRET_ARN` | unset | Unset locally. Set by the deploy. The memory password comes from this secret, a JSON object with a `password` key. |
| `FLEET_ENV_FILE` | `../.env` | The shared env file the server loads at startup |

## Tests

The tests run offline. They make no Bedrock, Gateway, or Neo4j calls.

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

To try the agent without the Gateway, run the Neo4j MCP server locally with
`neo4j-mcp-server/local.sh start`. The local server has no auth and no
`___` tool prefix, so point a test launcher at it and loosen
`SPECIALIST_TOOL_FILTERS` to the bare tool names.

## Example questions

- **Maintenance:** "Which components have the most failures?", "Show hydraulic system issues", and "What is the reliability history of avionics?"
- **Operations:** "What are the most common delay causes?", "Compare on-time performance by airline", and "Which airports have the highest traffic?"
- **Both:** "Compare maintenance fault counts with flight delay counts" calls both specialists.
- **General:** "What is the database schema?" goes to the Operations Agent.

See `fleet_supervisor/client/queries.txt` for all 20 questions.

## See also

- **System design:** [`docs/ARCHITECTURE.md`](../../../docs/ARCHITECTURE.md) describes the full system.
- **Single agent:** [`demos/aircraft-fleet/graphrag-agent/`](../graphrag-agent/) is the single-agent version. It connects to Neo4j directly.
