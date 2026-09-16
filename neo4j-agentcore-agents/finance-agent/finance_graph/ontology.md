# Informal finance-crime ontology

## Decision

This project should add a small graph-native business-meaning layer beside the
finance instance graph. It is deliberately an **informal ontology**: ordinary
Neo4j nodes and relationships that define the business vocabulary, rules,
metrics, policies, and thresholds used by the finance agent.

It is not RDF, RDFS, OWL, SHACL, or TTL. No generic reasoner will infer results
from it. The definitions are explicit, versionable, queryable, and traceable in
the same database as the facts, while Cypher queries and analytics jobs remain
responsible for evaluating the rules.

This lets an analyst ask both of these questions:

```text
Which accounts are in a circular transfer pattern?
What does “circular transfer pattern” mean, which rule found it, and what
evidence does that rule inspect?
```

The first traverses instance data; the second traverses the informal ontology.
The agent must distinguish an investigative lead from a finding of criminal
activity.

## Current graph and its semantic gap

The loader currently materializes these instance objects:

| Graph element | Business meaning |
|---|---|
| `:Customer` | Party identified through the KYC feed. |
| `:Account` | Financial account that holds a balance and participates in money movement. |
| `:Merchant` | Merchant payee, classified by category and region. |
| `:Phone`, `:Address` | Customer contact and address identifiers. |
| `(:Customer)-[:OWNS]->(:Account)` | Customer-to-account ownership. |
| `(:Customer)-[:HAS_PHONE]->(:Phone)` and `[:HAS_ADDRESS]` | KYC identity details. |
| `(:Account)-[:TRANSACTED_WITH]->(:Merchant)` | Dated merchant-payment event, stored as a relationship with amount and time. |
| `(:Account)-[:TRANSFERRED_TO]->(:Account)` | Dated account-transfer event, stored as a relationship with amount and time. |
| `:SIMILAR_TO` and account metric properties | Outputs of optional GDS enrichment. |

Storage labels alone do not say how an analyst should interpret a signal. For
example, current `risk_score` is PageRank on an *undirected* transfer-network
projection. It is a transfer-network influence score, not a probability of
fraud or proof of fraud. `community_id` is a run-specific Louvain cluster ID;
`:SIMILAR_TO` is Jaccard similarity of merchant-neighbour sets. Those meanings
must be explicit rather than inferred from property names.

## Core business domain objects

These are the durable business objects the vocabulary should define. Merchant
payments and transfers need not be reified as nodes: their current
relationship-based representation is appropriate for this demo.

| Domain object | Meaning | Existing representation | Notes |
|---|---|---|---|
| Party / Customer | Person or organization holding an account with KYC details. | `:Customer` | `Party` is the broader business term; retain `Customer` as the physical label. |
| Account | Store of value through which money moves. | `:Account` | Distinct from the customer that owns it. |
| Merchant | Counterparty accepting a merchant payment. | `:Merchant` | Category and region support pattern analysis. |
| Merchant payment | Dated monetary payment from an account to a merchant. | `:TRANSACTED_WITH` | A business event represented technically as a relationship. |
| Account transfer | Dated monetary movement between accounts. | `:TRANSFERRED_TO` | Direction identifies the source and destination. |
| Identity attribute | Reusable KYC identifier that can link customers. | `:Phone`, `:Address` | A shared value is a review signal, not proof of common control. |
| Transfer network | Directed network induced by account transfers. | Derived from `:TRANSFERRED_TO` | Supports chain, cycle, community, and intermediary analysis. |
| Merchant-behaviour profile | Set of merchants used by an account. | Derived from `:TRANSACTED_WITH` | Basis of current account similarity. |
| Investigative signal | Evidence that merits review. | Derived metric or rule result | Never equivalent to confirmed fraud. |
| Investigation / case | Analyst-owned review, disposition, and evidence. | Future object | Add only when work items or decisions are persisted. |

Account, Customer, Merchant, merchant payment, and account transfer are the
minimum viable domain. Identity attributes and network signals make the graph
useful for financial-crime investigation. A case is an operational workflow
object, so it is intentionally deferred.

## Proposed informal ontology subgraph

Add the following labels as a small governance subgraph. They describe the
domain and do not replace or duplicate instance data.

| Label | Required properties | Purpose |
|---|---|---|
| `:DomainEntity` | `id`, `name`, `definition`, `representation` | Defines Account, Merchant Payment, or Account Transfer and how each is represented in the graph. |
| `:BusinessTerm` | `id`, `name`, `definition`, `status` | Named analyst-facing concept, such as Circular Transfer Pattern. |
| `:BusinessRule` | `id`, `name`, `expression`, `description`, `evaluation_type`, `version` | Explicit rule behind a term. `expression` is readable pseudo-Cypher or business logic, not OWL. |
| `:GraphMetric` | `id`, `name`, `algorithm`, `scope`, `output_property`, `description` | Documents a GDS output and its interpretation. |
| `:Threshold` | `id`, `name`, `value`, `unit`, `basis`, `status` | Governed rule parameter; `basis` says whether it comes from policy, a percentile, or calibration. |
| `:Policy` | `id`, `name`, `purpose`, `owner`, `status` | Groups governed rules. |
| `:DataSource` | `id`, `name`, `system`, `location`, `refresh_cadence` | Records provenance for synthetic and later production feeds. |

Use stable IDs such as `ENT-ACCOUNT`, `TERM-CIRCULAR-TRANSFER`,
`RULE-CIRCULAR-TRANSFER`, and `METRIC-TRANSFER-PAGERANK`. `status` should
distinguish `draft`, `approved`, `deprecated`, and `experimental`; an
experimental metric must not be presented as an approved fraud rule.

```text
(:DomainEntity)-[:REPRESENTED_BY]->(:DataSource)
(:BusinessTerm)-[:DEFINED_BY]->(:BusinessRule)
(:BusinessRule)-[:EVALUATES]->(:DomainEntity)
(:BusinessRule)-[:USES_THRESHOLD]->(:Threshold)
(:BusinessTerm)-[:SCORED_BY]->(:GraphMetric)
(:Policy)-[:GOVERNS]->(:BusinessRule)
(:Policy)-[:CONSTRAINS]->(:DomainEntity)
(:GraphMetric)-[:DERIVED_FROM]->(:DomainEntity)
```

`representation` is plain text such as `:Account {account_id}` or
`:TRANSFERRED_TO {link_id, amount, transfer_timestamp}`. This documents the
model; it does not claim that `:DomainEntity` is a formal superclass of physical
labels.

## Initial vocabulary and rules

Seed a small, honest vocabulary before adding sophisticated classifications.
Each term has a rule node even where the current graph exposes evidence rather
than a materialized result.

| Business term | Definition and governing rule | Reads |
|---|---|---|
| Transfer Network Influence | Account PageRank on the undirected transfer projection. Higher means structurally influential in that projection, not more likely fraudulent. | Account, Account Transfer; `METRIC-TRANSFER-PAGERANK` |
| Transfer Community | Group assigned by Louvain on the undirected transfer projection. The numeric ID is meaningful only for that enrichment run. | Account, Account Transfer; `METRIC-TRANSFER-LOUVAIN` |
| Money-Flow Intermediary | Account whose sampled transfer-network betweenness exceeds a governed threshold. It is a candidate intermediary, not evidence of illicit activity. | Account, Account Transfer; `METRIC-TRANSFER-BETWEENNESS` |
| Behaviourally Similar Account | Pair of accounts with a recorded Jaccard similarity of merchant-neighbour sets. It does not imply common ownership, equal spend, or temporal similarity. | Account, Merchant, Merchant Payment; `METRIC-MERCHANT-JACCARD` |
| Identity Linkage Candidate | Two or more customers share a phone number or address. This is a KYC review lead; shared household, office, or stale data are alternatives. | Customer, Phone, Address |
| Circular Transfer Pattern | Directed transfer path returning to its start, with at least three distinct accounts and approved time-window and amount-consistency thresholds. Without those thresholds it is only a graph motif. | Account Transfer, Account; cycle thresholds |
| Concentrated Transfer Community | Transfer community with high internal transfer volume or count and low merchant-payment activity during the same period, measured against approved thresholds. It is a screening signal. | Account, Account Transfer, Merchant Payment, Transfer Community |
| Potential Fraud Ring | Investigation candidate supported by a circular transfer pattern plus an identity linkage, concentrated community, or behavioural similarity. Never synonymous with `is_fraud`. | Component terms and evidence |

`account_labels.csv` and `ground_truth.json` are test fixtures. They can
validate detectors offline but must not become a production-style `Fraud` label
or cause the agent to treat a signal as confirmed wrongdoing.

## Required graph-metric definitions

The enrichment job should seed or update these `:GraphMetric` nodes whenever it
writes the corresponding result. This prevents the agent from inventing a
meaning from a property name.

| Metric ID | Current implementation | Output | Required interpretation |
|---|---|---|---|
| `METRIC-TRANSFER-PAGERANK` | GDS PageRank on undirected `TRANSFERRED_TO` | `Account.risk_score` | Display as Transfer Network Influence. Retain the physical property for compatibility, or later rename it to `transfer_network_influence`. |
| `METRIC-TRANSFER-LOUVAIN` | GDS Louvain on the same projection | `Account.community_id` | Cluster membership, not a fraud segment. Record enrichment-run time and settings. |
| `METRIC-TRANSFER-BETWEENNESS` | GDS sampled betweenness on the same projection | `Account.betweenness_centrality` | Intermediary signal dependent on sampling. Record `samplingSize` and `samplingSeed`. |
| `METRIC-MERCHANT-JACCARD` | GDS Jaccard similarity through Account–Merchant payments | `SIMILAR_TO.similarity_score`, `Account.similarity_score` | Similarity of merchant-neighbour sets only. Record `topK` and `degreeCutoff`. |

Record an `AnalyticsRun` ID and timestamp on metric definitions or result
properties. This is essential for `community_id`, whose arbitrary numeric value
can change when the algorithm is rerun.

## Loading and agent changes

The update can be incremental and does not require changing the instance model.

1. Add version-controlled CSVs under `finance_graph/data/` for domain entities,
   terms, rules, metrics, thresholds, policies, sources, and their relationship
   tables. Keep definitions in data files, not only in the agent prompt.
2. Extend `load_neo4j.py` with uniqueness constraints on ontology-node `id`s,
   then idempotent `MERGE` statements for the nodes and relationships. Load this
   subgraph after the instance data.
3. Have `enrich_gds.py` update metric provenance and algorithm parameters after
   every successful run. Do not treat PageRank output as a fraud classification.
4. Update `core/config.py`: when explaining a signal, retrieve the relevant
   term and rule, state whether it is a fact, metric, or screening lead, and
   cite its instance evidence separately. The agent should use `get-schema`
   when uncertain.
5. Add tests proving every term resolves to a rule, evaluated entities, and any
   required metric or threshold; reject orphaned rules and unknown metric-output
   properties.

An explanation traversal for the agent can be read-only:

```cypher
MATCH (term:BusinessTerm {id: $term_id})-[:DEFINED_BY]->(rule:BusinessRule)
OPTIONAL MATCH (rule)-[:EVALUATES]->(entity:DomainEntity)
OPTIONAL MATCH (rule)-[:USES_THRESHOLD]->(threshold:Threshold)
OPTIONAL MATCH (term)-[:SCORED_BY]->(metric:GraphMetric)
OPTIONAL MATCH (policy:Policy)-[:GOVERNS]->(rule)
RETURN term, rule, collect(DISTINCT entity) AS entities,
       collect(DISTINCT threshold) AS thresholds,
       collect(DISTINCT metric) AS metrics, collect(DISTINCT policy) AS policies;
```

## Guardrails

- The ontology is explanatory and governed, not self-executing. Each rule needs
  a maintained Cypher query, GDS pipeline, or analyst-review procedure.
- Preserve the difference between an observed fact, analytics metric, screening
  signal, and confirmed case disposition.
- Do not infer shared ownership from a shared identifier, or fraud from
  centrality, similarity, a cluster, or a cycle alone.
- Keep thresholds in `:Threshold` nodes, not prompts, so changes are reviewable
  and consistently applied.
- Maintain provenance and data-quality metadata before reusing this pattern
  with real financial data.

This gives `finance-agent` a governed vocabulary for grounded answers while
leaving `finance_graph` a conventional Neo4j property graph. A formal ontology
can be added later if portable RDF semantics, SHACL validation, or generic
reasoner execution become requirements.
