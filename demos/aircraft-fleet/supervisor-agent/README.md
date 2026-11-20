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

The model and the Gateway MCP client are created on the first request and
shared by later requests. If the MCP session ends, the next request opens a
new one.

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

## Gateway credentials

The agent has two ways to get a Gateway token. The environment picks one.

- **Local:** The agent reads `demos/aircraft-fleet/.mcp-credentials.json`. The path is resolved from the package, so it works from any working directory. Set `MCP_CREDENTIALS_FILE` to use another file.
- **Cloud:** When `GATEWAY_CREDENTIAL_PROVIDER` is set, the agent gets an M2M token from that AgentCore Identity credential provider. `GATEWAY_URL` gives the Gateway endpoint. The runtime holds no client secret.

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
zips this whole folder, and `./agent.sh deploy` refuses to run if any `.env*`
or `.mcp-credentials*.json` file is inside it.

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

Before the first deploy, do two things:

1. **Deploy settings:** Set the `MEM_NEO4J_*` settings in `demos/aircraft-fleet/.env`. `./agent.sh deploy` exports them, plus `GATEWAY_URL` and `GATEWAY_SCOPES` from `gateway_url` and `scope` in the fleet credentials file. A value already set in the shell wins. The files are parsed, not sourced, and nothing else in them is exported. `agentcore/cdk/lib/cdk-stack.ts` copies the settings onto the runtime. Synth stops with one error that lists every missing or malformed setting. `GATEWAY_URL` must use `https://`, and `MEM_NEO4J_URI` must use `neo4j+s://` or `bolt+s://`. `MEM_NEO4J_PASSWORD_SECRET_ARN` must be a complete secret ARN, and the runtime role can read only that secret.
2. **Credential provider:** Add the `fleet-gateway` OAuth credential provider that `GATEWAY_CREDENTIAL_PROVIDER` names. The client ID, scope, and secret come from the fleet credentials file. The discovery URL is an output of the MCP server stack.

   ```bash
   creds=../.mcp-credentials.json
   jq -r .client_secret "$creds" | agentcore add credentials oauth \
       --name fleet-gateway \
       --client-id "$(jq -r .client_id "$creds")" \
       --discovery-url "$(aws cloudformation describe-stacks --region us-east-1 \
           --stack-name "$(jq -r .stack_name "$creds")" \
           --query "Stacks[0].Outputs[?OutputKey=='CognitoDiscoveryUrl'].OutputValue" \
           --output text)" \
       --scopes "$(jq -r .scope "$creds")" \
       --client-secret -
   ```

   The AgentCore CLI creates the provider from this entry on the next deploy,
   before CDK runs. CDK cannot create it, and it grants the runtime access to
   the provider only when the entry exists. For that reason, `./agent.sh deploy`
   refuses to run until the entry is in `agentcore.json`. The client secret is
   stored in `agentcore/.env.local`, which git ignores and the code zip leaves
   out.

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
| `./agent.sh destroy` | Remove the runtime from AgentCore |

`invoke-cloud` and `load-test` find the runtime ARN in `AGENT_ARN`. If it is
unset, they read it from `agentcore status --json`.

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
| `GATEWAY_CREDENTIAL_PROVIDER` | unset | AgentCore Identity provider name. Setting it selects the cloud path. |
| `GATEWAY_URL` | unset | Gateway endpoint for the cloud path. It must use `https://`. On deploy it comes from `gateway_url` in the credentials file. |
| `GATEWAY_SCOPES` | unset | Space-separated OAuth scopes for the cloud path. On deploy they come from `scope` in the credentials file. |

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
