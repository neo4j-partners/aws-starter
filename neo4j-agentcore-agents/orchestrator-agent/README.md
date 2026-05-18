# Multi-Agent Orchestrator

A supervisor agent that classifies an incoming query and routes it to a
specialized worker, using LangGraph's Supervisor pattern. Workers query the
aviation fleet graph through the same Neo4j MCP Gateway path as the other
agents. This agent is the reference for multi-agent routing and observability.

## Architecture

```
                        User query
                            |
                  Orchestrator (Supervisor)
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

## Unique Features

- **Intent routing.** The supervisor classifies each query and dispatches to
  one worker, or to both for cross-domain questions, then synthesizes a single
  answer.
- **Domain specialists.** The Maintenance Agent handles faults, components,
  sensors, and reliability. The Operations Agent handles flights, delays,
  routes, and airports. Each is a focused ReAct agent over the same MCP tools.
- **Multi-agent traces.** With three agents, CloudWatch traces show the
  routing decision, the chosen worker, its tool calls, and the synthesized
  response in one session.

### Routing

| Query mentions | Routes to |
|----------------|-----------|
| maintenance, fault, repair, failure, component, sensor, reliability | Maintenance Agent |
| flight, delay, schedule, on-time, airport, route, departure, arrival | Operations Agent |
| Both domains | Both workers, then synthesize |

## Layout

| File | Purpose |
|------|---------|
| `orchestrator_agent.py` | Supervisor entrypoint that classifies and routes |
| `maintenance_agent.py` | Worker for faults, components, sensors, reliability |
| `operations_agent.py` | Worker for flights, delays, routes, airports |
| `invoke_agent.py` | Cloud invocation and load testing |
| `queries.txt` | 20 test queries, 10 maintenance and 10 operations |
| `agent.sh` | CLI wrapper for all operations |

## Prerequisites

1. Python 3.10+ and the `uv` package manager.
2. AWS CLI configured, with Bedrock model access enabled.
3. A deployed Neo4j MCP server with an AgentCore Gateway.

## Quick Start: Local

```bash
uv sync
../sync-credentials.sh             # or: cp ../basic-agent/.mcp-credentials.json .

./agent.sh start                   # serves http://localhost:8080
./agent.sh test-maintenance        # query that routes to Maintenance
./agent.sh test-operations         # query that routes to Operations
```

## Quick Start: Cloud

```bash
./agent.sh configure
./agent.sh deploy                  # takes several minutes
./agent.sh invoke-cloud "What are the most common maintenance faults?"
./agent.sh invoke-cloud "Which routes have the most delays?"
```

## Local Docker Testing

From the parent `neo4j-agentcore-agents/` directory:

```bash
uv run local-test all orchestrator-agent
```

## Commands

| Command | Description |
|---------|-------------|
| `./agent.sh start` / `stop` | Run or stop locally on port 8080 |
| `./agent.sh test` | General query |
| `./agent.sh test-maintenance` | Query that routes to the Maintenance Agent |
| `./agent.sh test-operations` | Query that routes to the Operations Agent |
| `./agent.sh configure` | Generate AWS deployment config |
| `./agent.sh deploy` / `destroy` | Deploy to or remove from AgentCore |
| `./agent.sh status` | Check deployment status |
| `./agent.sh invoke-cloud "prompt"` | Invoke the deployed agent |
| `./agent.sh load-test [N]` | Continuous cloud test, N-second interval |

## Environment Variables

| Variable | Default |
|----------|---------|
| `MODEL_ID` | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` |

## Example Queries

**Maintenance:** "Which components have the most failures?",
"Show hydraulic system issues", "What is the reliability history of avionics?"

**Operations:** "What are the most common delay causes?",
"Compare on-time performance by airline", "Which airports have the highest traffic?"

**Cross-domain:** "How do maintenance issues affect flight delays?"

See `queries.txt` for the full set of 20.

## See Also

- [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) for the full system design
- [../basic-agent/](../basic-agent/) for the single-agent version
