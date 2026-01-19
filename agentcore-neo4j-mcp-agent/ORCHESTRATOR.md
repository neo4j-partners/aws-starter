# Multi-Agent Orchestrator Architecture

## Overview

This document describes the multi-agent orchestrator system for the Neo4j MCP aviation fleet database. The single `aircraft-agent.py` is evolved into three coordinated agents using LangGraph's Supervisor pattern.

## Why Multi-Agent?

| Single Agent | Multi-Agent |
|--------------|-------------|
| One trace span | Multiple spans showing routing |
| Generic metrics | Per-domain metrics |
| Hidden routing logic | Explicit classification decisions |
| Hard to debug | Clear agent attribution |

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

### Orchestrator Agent (Supervisor)

**Role**: Receives all queries, classifies intent, routes to specialist, returns response.

**System Prompt Focus**:
- You are a query router for an aviation fleet system
- Classify queries as maintenance OR operations
- Delegate to the appropriate specialist
- For cross-domain queries, invoke both agents and synthesize

### Maintenance Agent (Worker)

**Role**: Expert for aircraft health, reliability, and technical queries.

**Domain**: MaintenanceEvent, Component, Sensor, Reading, System, Fault codes

**Example Queries**:
- "What are the most common maintenance faults?"
- "Which components have the most failures?"
- "Show hydraulic system issues"
- "Analyze engine sensor readings"

### Operations Agent (Worker)

**Role**: Expert for flight operations, scheduling, and delays.

**Domain**: Flight, Delay, Airport, Route, Operator

**Example Queries**:
- "What are the most common delay causes?"
- "Which routes have the most delays?"
- "Find flights departing from JFK"
- "Compare on-time performance by airline"

## Routing Decision Logic

| Query Contains | Routes To |
|----------------|-----------|
| maintenance, fault, repair, failure | Maintenance |
| component, sensor, reading, reliability | Maintenance |
| flight, delay, schedule, on-time | Operations |
| airport, route, departure, arrival | Operations |
| Both domains | Both → Synthesize |
| Ambiguous | Operations (default) |

## LangGraph Supervisor Pattern

**How It Works**:
1. User query enters the StateGraph
2. Orchestrator node classifies the query
3. Conditional edge routes to appropriate worker
4. Worker executes MCP tools and returns response
5. Orchestrator synthesizes and returns to user

**State Flow**:
- Shared state contains messages and routing decisions
- Workers operate as compiled subgraphs
- Handoff preserves context between agents

## Observability Benefits

**What Traces Will Show**:

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

**Dashboard Insights**:
- Routing distribution (% maintenance vs operations)
- Per-agent latency and error rates
- Tool usage patterns by domain
- Session traces spanning multiple agents

## Example Trace: Cross-Domain Query

**Query**: "How do maintenance issues affect flight delays?"

```
[Orchestrator] Multi-domain query detected
  │
  ├── [Maintenance Agent] Find maintenance issues
  │     └── 5 hydraulic failures on 3 aircraft
  │
  ├── [Operations Agent] Find delays for those aircraft
  │     └── 8 delays correlated with maintenance
  │
  └── [Orchestrator] Synthesized response
        └── "Found 3 aircraft with hydraulic failures causing 8 delays..."
```

## Files

| File | Purpose |
|------|---------|
| `orchestrator-agent.py` | Supervisor - routes queries to specialists |
| `maintenance-agent.py` | Worker - handles reliability/faults/components |
| `operations-agent.py` | Worker - handles flights/delays/routes |

## Summary

The multi-agent orchestrator provides:
- **Clear separation** between maintenance and operations
- **Explicit routing** visible in traces
- **Enhanced observability** with per-agent metrics
- **Scalability** for adding future specialists
- **Demo-friendly** architecture showing AI coordination
