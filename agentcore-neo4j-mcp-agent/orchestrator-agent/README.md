# Multi-Agent Orchestrator - AgentCore Runtime

A supervisor agent that routes queries to specialized workers using LangGraph's Supervisor pattern.

## Architecture

```
                         User Query
                              │
                              ▼
                ┌─────────────────────────┐
                │   Orchestrator Agent    │
                │      (Supervisor)       │
                │                         │
                │  Classifies → Routes    │
                └───────────┬─────────────┘
                            │
               ┌────────────┴────────────┐
               │                         │
               ▼                         ▼
    ┌───────────────────┐     ┌───────────────────┐
    │ Maintenance Agent │     │ Operations Agent  │
    │     (Worker)      │     │     (Worker)      │
    │                   │     │                   │
    │ • Faults          │     │ • Flights         │
    │ • Components      │     │ • Delays          │
    │ • Sensors         │     │ • Routes          │
    │ • Reliability     │     │ • Airports        │
    └─────────┬─────────┘     └─────────┬─────────┘
              │                         │
              └───────────┬─────────────┘
                          ▼
                  Neo4j MCP Server
```

## Agent Responsibilities

### Orchestrator (Supervisor)

Routes queries based on intent classification:

| Query Contains | Routes To |
|----------------|-----------|
| maintenance, fault, repair, failure | Maintenance Agent |
| component, sensor, reading, reliability | Maintenance Agent |
| flight, delay, schedule, on-time | Operations Agent |
| airport, route, departure, arrival | Operations Agent |
| Both domains | Both → Synthesize |

### Maintenance Agent (Worker)

Expert for aircraft health and reliability:
- Fault analysis and patterns
- Component failures
- Sensor readings
- System diagnostics

### Operations Agent (Worker)

Expert for flight operations:
- Delay analysis
- Route performance
- Operator metrics
- Airport traffic

## Quick Start

```bash
# 1. Install dependencies
./agent.sh setup

# 2. Copy credentials from basic-agent
cp ../basic-agent/.mcp-credentials.json .

# 3. Start locally
./agent.sh start

# 4. Test routing to different agents
./agent.sh test-maintenance   # Routes to Maintenance Agent
./agent.sh test-operations    # Routes to Operations Agent
```

## Commands

| Command | Description |
|---------|-------------|
| `./agent.sh setup` | Install dependencies |
| `./agent.sh start` | Start orchestrator locally (port 8080) |
| `./agent.sh stop` | Stop local orchestrator |
| `./agent.sh test` | Test with general query |
| `./agent.sh test-maintenance` | Test Maintenance Agent routing |
| `./agent.sh test-operations` | Test Operations Agent routing |
| `./agent.sh configure` | Configure for AWS deployment |
| `./agent.sh deploy` | Deploy to AgentCore Runtime |
| `./agent.sh status` | Check deployment status |
| `./agent.sh invoke-cloud "prompt"` | Invoke deployed orchestrator |
| `./agent.sh destroy` | Remove from AgentCore |

## Files

| File | Purpose |
|------|---------|
| `orchestrator_agent.py` | Main entry point - supervisor that routes queries |
| `maintenance_agent.py` | Worker for reliability/faults/components |
| `operations_agent.py` | Worker for flights/delays/routes |
| `pyproject.toml` | Dependencies including langgraph-supervisor |
| `agent.sh` | CLI wrapper for all operations |

## Observability Benefits

With 3 agents, CloudWatch traces show:

```
[Orchestrator] Query received: "aircraft with hydraulic failures"
  │
  ├── Classification: Maintenance domain
  ├── Decision: Route to Maintenance Agent
  │
  └── [Maintenance Agent] Processing query
        │
        ├── Tool: execute-query (Cypher)
        ├── Results: 5 failures found
        │
        └── Response returned

[Orchestrator] Final response delivered
```

**Dashboard Insights:**
- Routing distribution (% maintenance vs operations)
- Per-agent latency and error rates
- Tool usage patterns by domain
- Session traces spanning multiple agents

## Example Queries

**Maintenance Agent:**
```bash
./agent.sh invoke-cloud "What are the most common maintenance faults?"
./agent.sh invoke-cloud "Which components have the most failures?"
./agent.sh invoke-cloud "Show hydraulic system issues"
```

**Operations Agent:**
```bash
./agent.sh invoke-cloud "What are the most common delay causes?"
./agent.sh invoke-cloud "Which routes have the most delays?"
./agent.sh invoke-cloud "Compare on-time performance by airline"
```

**Cross-Domain (Both Agents):**
```bash
./agent.sh invoke-cloud "How do maintenance issues affect flight delays?"
```

## Key Technologies

- **LangGraph Supervisor** - Multi-agent orchestration pattern
- **Amazon Bedrock AgentCore** - Managed runtime for AI agents
- **Claude Sonnet 4** - LLM powering all agents
- **Neo4j MCP Server** - Graph database via Model Context Protocol

## See Also

- [../ORCHESTRATOR.md](../ORCHESTRATOR.md) - Detailed architecture design
- [../basic-agent/](../basic-agent/) - Single-agent version
