# Enterprise Knowledge Layer with NeoCarta

## Purpose

An enterprise knowledge layer is an abstraction between AI agents and enterprise data sources. It gives agents a traversable, queryable map of where information lives, how it is structured, which business concepts it represents, and how to retrieve it.

Supported sources can include relational databases, data warehouses, search systems, document repositories, object stores, collaboration platforms, and API-based services.

The layer supports two complementary goals:

- Ground agent responses in enterprise data and business context.
- Persist and improve reusable execution paths, rather than requiring every agent run to rediscover the same information and process.

## Reference Architecture

```text
                         Business documentation, data dictionary,
                         query logs, process and audit records
                                          |
                                          v
Source-system schemas ---> Schema graph <--- Business ontology
  APIs, databases,              |                 |
  warehouses, documents         +--------+--------+
                                    semantic links
                                          |
                                          v
                              Enterprise knowledge graph
                                          |
                    +---------------------+---------------------+
                    |                                           |
                    v                                           v
            Agent context and routing                 Execution history,
            source and API instructions               evaluations, and weights
                    |                                           |
                    +---------------------+---------------------+
                                          |
                                          v
                           Native source queries or API calls
```

The knowledge graph stores metadata, business semantics, process knowledge, and agent traces. It does not inherently copy instance-level source data.

## Building the Knowledge Layer

### 1. Discover and graph source schemas

Ingest metadata from each source system using connectors. Common paths are:

- Query a source system's schema-reporting API.
- Ingest a schema export.
- Analyze query logs to infer frequently used entities, fields, and relationships when a schema export is unavailable.

Represent the result as a schema graph, for example:

```text
Database -> Table -> Column
Source system -> API -> Operation -> Parameter
Repository -> Collection -> Document
```

Annotate graph elements with clear, agent-readable descriptions so that technical names and abbreviations can be interpreted correctly. This is a metadata-only, zero-copy operation.

### 2. Build or ingest the business ontology

The ontology captures business terms, their relationships, and the processes they participate in. It can be:

- Ingested from an existing business ontology or data dictionary.
- Extracted from process documentation, collaboration content, query logs, and audit records.
- Curated by domain experts where source material lacks an authoritative association.

Schema discovery and ontology creation can proceed independently. The critical step is linking business concepts to the technical entities and retrieval mechanisms that represent them.

```text
Business term -> Business process -> Source system -> Table/API/document
```

For example, a business concept can link to a profile table, transactional history, a policy document, and the process that governs how those sources are used.

### 3. Supply focused context to agents

On a new request, an agent can:

1. Identify relevant business concepts.
2. Traverse to associated processes, data sources, schema elements, documents, APIs, and known query patterns.
3. Retrieve only the context required for the current decision.
4. Execute a native query or API call against the selected source.
5. Construct a grounded response.

This avoids placing every rule and every source schema into every prompt. Context is supplied at the decision point where it is needed, reducing token use and improving relevance.

## Shared Agent Memory and Process Optimization

For a novel request, an agent may explore multiple retrieval and execution options. Persist the resulting trace as a traversable process graph:

```text
Question
  -> selected business concepts
  -> source selection
  -> query or API invocation
  -> retrieved evidence
  -> response
  -> evaluation and performance metrics
```

Capture attributes such as:

- The decisions and actions taken at each step.
- Queries, API calls, and returned evidence.
- Latency, resource consumption, and other execution metrics.
- User feedback and evaluator results.
- The outcome and rationale for accepting, rejecting, or revising a path.

Later agents can use semantic similarity to find comparable questions and reuse high-confidence paths. They can skip proven steps, avoid previously unsuccessful ones, or improve a path when performance or quality is insufficient.

Each relationship in the process graph can carry a weight representing its observed quality and suitability. The graph becomes a persistent, shared memory of optimized business processes rather than a collection of isolated agent interactions.

## Evaluation and Governance

Use three feedback channels together. No single signal is sufficient to establish correctness.

| Channel | Role |
| --- | --- |
| Agent as judge | Evaluates complete traces, source use, quality, and performance, then adjusts the weight of decisions or paths. |
| User feedback | Captures explicit signals such as approval or rejection, plus implicit sentiment from user responses. |
| Expert review | Lets business or data stewards validate, annotate, suppress, or redirect paths according to policy and domain truth. |

An evaluator with access to the full trace can identify an earlier decision that caused a poor result and reduce the probability that future agents select that edge. Domain experts should be able to record the reason for a rejected path and the preferred alternative. Retaining the rejected path with a low weight and an explanation can prevent agents from recreating a known-bad decision.

Aggregate user feedback can identify broad patterns, but it may reinforce a plausible but incorrect answer. Expert governance and trace-based evaluation provide the authoritative correction mechanism, particularly for high-risk decisions.

## NeoCarta and Virtual Graphs

Both approaches can use a graph representation of source schemas and both can operate without inherently materializing source data. Their query execution models differ.

| Capability | Virtual graph | NeoCarta knowledge layer |
| --- | --- | --- |
| Graph role | Maps source schemas and provides a unified graph query interface. | Maps schemas, business concepts, retrieval instructions, and reusable agent process knowledge. |
| Query model | Cypher is translated at runtime into the native query language of the target source. | An agent uses graph context to issue native SQL, API calls, or other source-specific operations directly. |
| Primary value | Federated querying through a graph interface. | Agent grounding, routing, shared memory, trace persistence, and path optimization. |

The approaches are complementary. A virtual graph can support federated retrieval while a knowledge layer provides the business context and agent orchestration needed to decide what to retrieve and how to use the result.

## Data Placement and Performance

Start with a zero-copy approach: retain source data in its systems of record and use the graph for metadata, semantic links, process paths, and execution history.

Over time, observed query traces can identify targeted cases for graph materialization. Consider copying data into a graph when a workload:

- Requires low-latency, repeated reads that federated access cannot meet.
- Requires multi-hop relationship analysis that is inefficient or impractical in a tabular source.
- Benefits from native graph algorithms or graph-native traversal.

Materialization is a selective, data-driven optimization. It is not an inherent requirement of either NeoCarta or a virtual graph.

## Simulation and Graph Analytics

Operational simulations should be modeled as a dedicated graph analytics workload, separate from the semantic layer itself.

For example, load a network schedule into a graph, create in-memory graph projections for proposed scenarios, and run graph algorithms to assess downstream effects. The simulation can alter the projection without changing the persisted operational graph.

```text
Persisted operational graph
           |
           v
In-memory projection for scenario A / B / C
           |
           v
Graph algorithms and impact analysis
           |
           v
Ranked mitigation options and reasoning
```

The knowledge layer can treat the simulation graph as another source system. An agent can discover the appropriate simulation capability, invoke a tested suite of queries or procedures, and reuse validated simulation workflows from its shared process memory.

## Implementation Sequence

1. Inventory data sources, APIs, documentation, query logs, and existing business terminology.
2. Create the metadata-only schema graph through connectors, schema exports, or log analysis.
3. Ingest or extract the ontology, then validate high-value business-to-technical links with domain experts.
4. Implement a narrow agent workflow that retrieves context, invokes sources, and records complete traces.
5. Add evaluation gates: automated trace evaluation, user feedback capture, and expert review queues.
6. Reuse and weight successful paths; annotate and suppress invalid paths.
7. Measure latency and capability gaps, then selectively materialize graph-native workloads where justified.
8. Expose specialized graph analytics and simulations as discoverable, governed capabilities of the knowledge layer.
