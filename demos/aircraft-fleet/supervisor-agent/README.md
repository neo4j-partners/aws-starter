# Aircraft Fleet Supervisor Agent

This LangGraph supervisor agent reads each question and sends it to one
specialist worker. The workers query the aircraft fleet graph through the Neo4j
MCP Gateway.

## Overview

- **Supervisor:** The supervisor classifies each question and sends it to exactly one worker. Unclear or general questions go to the Operations Agent.
- **Maintenance Agent:** This worker handles faults, components, sensors, and reliability.
- **Operations Agent:** This worker handles flights, delays, routes, and airports.
- **Shared tools:** Each worker is a focused ReAct agent. Both use the same MCP tools.
- **Traces:** CloudWatch traces show the routing decision, the chosen worker, its tool calls, and the final answer in one session.
- **Purpose:** This agent is the reference example for multi-agent routing and observability.

## Quick start

Run these commands from `demos/aircraft-fleet/supervisor-agent/`:

```bash
uv sync
../../../scripts/sync-credentials.sh   # copy the fleet MCP credentials here

./agent.sh start                       # serves http://localhost:8080
./agent.sh test-maintenance            # a question that goes to Maintenance
./agent.sh test-operations             # a question that goes to Operations

./agent.sh configure                   # deploy to AgentCore Runtime
./agent.sh deploy
./agent.sh invoke-cloud "What are the most common maintenance faults?"
```

## Architecture

```
                        User query
                            |
                        Supervisor
                   classifies, then routes
                            |
              +-------------+-------------+
              |                           |
       Maintenance Agent          Operations Agent
       faults, components         flights, delays
       sensors, reliability       routes, airports
              |                           |
              +-------------+-------------+
                            |
                    Neo4j MCP Server -> Neo4j
```

### Routing

The supervisor asks the LLM to classify each question. The router prompt in
`core/prompts.py` gives the LLM these keywords:

| Question mentions | Goes to |
|-------------------|---------|
| maintenance, fault, failure, component, system, reliability, sensor, reading, repair, hydraulic, engine, avionics, critical, severity | Maintenance Agent |
| flight, delay, route, airport, operator, schedule, departure, arrival, on-time, airline, carrier | Operations Agent |
| Neither, or a general topic such as schema or counts | Operations Agent |

## Prerequisites

1. **Python:** You need Python 3.10 or later and the `uv` package manager.
2. **AWS:** You need the AWS CLI configured, with Bedrock model access.
3. **Graph:** You need the fleet graph loaded into Neo4j by [`demos/aircraft-fleet/pipeline/`](../pipeline/).
4. **MCP server:** You need a `fleet` Neo4j MCP server deployment that points at the same Neo4j database. Run these commands from the repo root:

   ```bash
   cd neo4j-mcp-server
   ./deploy.py --env fleet
   ./deploy.py --env fleet credentials
   ```

## Run locally

Run these commands from `demos/aircraft-fleet/supervisor-agent/`:

```bash
uv sync
../../../scripts/sync-credentials.sh

./agent.sh start                   # serves http://localhost:8080
./agent.sh test-maintenance        # a question that goes to Maintenance
./agent.sh test-operations         # a question that goes to Operations
```

- **Credentials:** `sync-credentials.sh` copies `neo4j-mcp-server/.mcp-credentials.fleet.json` to `.mcp-credentials.json` in this folder. You can also copy the file by hand.
- **Server:** `./agent.sh start` runs `uv run fleet-supervisor-server`.

## Deploy to AgentCore Runtime

Run these commands from `demos/aircraft-fleet/supervisor-agent/`:

```bash
./agent.sh configure
./agent.sh deploy                  # takes several minutes
./agent.sh invoke-cloud "What are the most common maintenance faults?"
./agent.sh invoke-cloud "Which routes have the most delays?"
```

## Commands

| Command | Description |
|---------|-------------|
| `./agent.sh start` / `stop` | Start or stop the agent locally on port 8080 |
| `./agent.sh test` | Send a general question to the local agent |
| `./agent.sh test-maintenance` | Send a question that goes to the Maintenance Agent |
| `./agent.sh test-operations` | Send a question that goes to the Operations Agent |
| `./agent.sh configure` | Create the AWS deployment config in `AWS_REGION`, or `us-east-1` if it is unset |
| `./agent.sh deploy` / `destroy` | Deploy to or remove from AgentCore Runtime |
| `./agent.sh status` | Show the deployment status |
| `./agent.sh invoke-cloud "prompt"` | Call the deployed agent |
| `./agent.sh load-test [N]` | Send a random test question to the deployed agent every N seconds. The default is 5. |

## Layout

The agent follows the shared `core/`, `server/`, and `client/` layout:

- **`core/`:** This folder holds the reusable code.
- **`server/`:** This folder is the only code that ships in the Docker image.
- **`client/`:** This folder holds local tools only.

| Path | Purpose |
|------|---------|
| `core/config.py` | The model ID and region. Environment variables can override them. |
| `core/prompts.py` | The router prompt and the two specialist system prompts |
| `core/credentials.py` | Credential loading and in-memory OAuth2 token refresh |
| `core/factory.py` | The Bedrock LLM and MCP tool factories |
| `core/graph.py` | The LangGraph router, the specialist nodes, and the graph builder |
| `server/runtime_app.py` | The AgentCore entrypoint, run by `fleet-supervisor-server` |
| `client/invoke.py` | Cloud calls and load testing, run by `fleet-supervisor-invoke` |
| `client/queries.txt` | 20 test questions: 10 for maintenance and 10 for operations |
| `agent.sh` | The command wrapper for local runs and deployment |

## Environment variables

| Variable | Default |
|----------|---------|
| `MODEL_ID` | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `AWS_REGION` | `us-east-1` |

## Example questions

- **Maintenance:** "Which components have the most failures?", "Show hydraulic system issues", and "What is the reliability history of avionics?"
- **Operations:** "What are the most common delay causes?", "Compare on-time performance by airline", and "Which airports have the highest traffic?"
- **General:** "What is the database schema?" goes to the Operations Agent.

See `client/queries.txt` for all 20 questions.

## See also

- **System design:** [`docs/ARCHITECTURE.md`](../../../docs/ARCHITECTURE.md) describes the full system.
- **Single agent:** [`demos/aircraft-fleet/graphrag-agent/`](../graphrag-agent/) is the single-agent version. It connects to Neo4j directly.
