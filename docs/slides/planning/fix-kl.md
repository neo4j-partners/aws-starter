# Knowledge Layer Section Revision

## Objective

Revise the Enterprise Knowledge Layer section in
`docs/slides/current/aws-neo4j-grounded-enterprise-ai.md` so it:

- follows Neo4j's official Knowledge Layer framing;
- explains the problem, the capability, and the operating model in a clear sequence;
- separates ontology, enterprise data, memory, and decision traces correctly;
- shows that data materialization and memory are independent extensions;
- creates a natural transition into Neo4j Agent Memory; and
- uses short, presentation-ready language.

Primary source:
`/Users/ryanknight/projects/cloud-integration/knowledge-layer/reference/knowledge-layer-official.md`

## Recommended Narrative

Use eight content slides between the existing **Enterprise Knowledge Layer** and
**Neo4j Agent Memory** section dividers.

The story should answer these questions in order:

1. Why is a shared Knowledge Layer needed?
2. How does a shared layer make connected context reusable?
3. What is it?
4. What are its three components?
5. What knowledge does the ontology contain?
6. How does the layer ground a request?
7. How can an organization build it incrementally?
8. How does today's decision become useful experience?

This sequence gives the reusable-context concept its own slide while keeping its
role distinct from the formal definition that follows. The useful material from
the previous outline is incorporated below, so the separate old outline and old
slide details are no longer needed.

## Final Slide Outline

### 1. Ten agents should not create ten versions of the business

**Purpose:** Establish semantic duplication and definition drift as the problem.

**Overview:** Put shared enterprise meaning in one governed substrate instead of
copying definitions, rules, and source mappings into every agent.

**Content:**

- **Private definitions drift:** Prompts, tools, and retrieval pipelines create
  separate interpretations of terms such as "active customer" or "exposure."
- **Inconsistency is hard to detect:** Each agent can sound correct while using a
  different definition, source, or rule.
- **Shared knowledge scales:** Agents query one current, governed source of meaning
  as they work.
- **Lighter agents, smarter substrate:** Business knowledge stays reusable across
  agents, applications, and tools.

**Visual:** Contrast several agents carrying private definitions with agents using
one shared source of enterprise meaning. This sets up the existing lighter-agents
visual on the next slide without repeating its full message.

### 2. A shared Knowledge Layer makes connected context reusable

**Purpose:** Introduce the shared-layer solution and preserve the important
lighter-agents concept from the current deck.

**Overview:** Keep meaning in one governed layer so every agent uses consistent
definitions, relationships, and rules.

**Content:**

- **One shared layer:** Enterprise knowledge is maintained once and reused across
  agents, applications, and tools.
- **Connected context:** Business concepts link to data, policies, owners, and
  processes.
- **Current by design:** Agents query the layer while they work instead of copying
  its contents into prompts or local tools.
- **Lighter agents:** Consumers focus on their tasks while the shared layer provides
  the meaning and context they need.

**Visual:** Reuse `knowledge-layer-lighter-agents-compact.svg`. Preserve its central
message: a smarter shared substrate supports multiple lighter agents.

### 3. The Knowledge Layer makes enterprise knowledge queryable and actionable

**Purpose:** Define the Knowledge Layer before describing its internal parts.

**Overview:** The Knowledge Layer is shared, governed, and executable software
between enterprise systems and the agents, applications, and tools that use them.

**Content:**

- **Shared:** Business meaning and operating knowledge are reusable across
  consumers.
- **Governed:** Sources, policies, ownership, and accountability remain explicit.
- **Queryable:** Consumers retrieve the exact context required for each request.
- **Actionable:** The layer maps intent to authoritative sources, permitted tools,
  and executable queries.
- **Current:** Consumers query the layer continuously instead of carrying a copied,
  incomplete, or stale version in their context.

**Visual:** Use a revised `exec-knowledge-layer.svg` to show apps, agents, and tools
querying the Knowledge Layer. The artwork must use the official three component
names: **Knowledge Layer ontology**, **enterprise data**, and **memory**. Remove the
current Enterprise Knowledge Graph caption because it changes the subject and
weakens the definition.

### 4. Three components ground every request

**Purpose:** Define the three peer components and their distinct roles.

**Overview:** Combine a governed model of the business, authoritative facts, and
experience from previous work.

**Content:**

- **Knowledge Layer ontology:** Holds what things mean, how they connect, where
  their data lives, what rules apply, and who is accountable. It defines what is
  possible and permitted.
- **Enterprise data:** Supplies authoritative facts about what is true now. Data
  may remain external, be queried through a virtual graph, or be materialized in
  Neo4j.
- **Memory:** Captures previous actions, decisions, outcomes, and reasoning. It
  preserves what experience has shown to be useful.

**Callout:** The ontology holds what is possible; memory holds what is proven.

**Visual:** Update `knowledge-layer-three-parts-compact.svg`. Keep decision traces
inside **Memory**, not as a fourth peer component.

### 5. The ontology connects meaning to systems and accountability

**Purpose:** Make the scope of the Knowledge Layer ontology concrete.

**Overview:** Five connected sub-ontologies describe how the business operates.

**Content:**

- **Domain:** Business concepts and relationships.
- **Technical:** Systems, sources, data assets, and mappings.
- **Process:** Tasks, decisions, workflows, and actions.
- **Policy:** Access rules, conditions, constraints, and permitted actions.
- **Organization:** Roles, ownership, responsibilities, and accountability.

**Visual:** Show the five parts as a connected graph, not as separate layers. Make
the domain and technical connection explicit:

```text
Business concept ↔ data-product mapping ↔ authoritative data asset
```

This is the most important definition missing from the current deck. Keep detailed
RDF, OWL, schema, and ontology-engineering material out of the main presentation.

### 6. The Knowledge Layer turns each request into a governed action plan

**Purpose:** Show how the layer works at runtime.

**Example request:** *What is our exposure to this customer?*

**Overview:** The Knowledge Layer grounds the request. The agent or application
executes the resulting plan.

**Content:**

1. **Interpret intent:** Resolve what "exposure" and "this customer" mean in this
   business context.
2. **Assemble context:** Select authoritative sources and the relationships needed
   to answer the request.
3. **Route queries and tools:** Translate business concepts into calls against AWS
   systems or query data held in the layer.
4. **Enforce policy:** Apply access and action rules before returning data or
   allowing an action.
5. **Explain and learn:** Return evidence and lineage, capture the decision trace,
   and retain useful outcomes in memory.

**Visual:** Update `knowledge-layer-request-flow-compact.svg` around the customer
exposure example. Keep policy enforcement within request resolution rather than
showing it as a final approval step.

### 7. Start with the core; extend it where the use case benefits

**Purpose:** Explain incremental adoption without implying a required maturity
sequence.

**Overview:** Begin with shared meaning, source mappings, policy, and tools. Keep
AWS data in its authoritative systems and query it in place. Add connected data,
memory, or both when the use case justifies them.

**Core:**

- **Ontology-Based Semantic Layer:** Ontology, reference data, source mappings,
  policy, and tools.
- **Query in place:** Route queries to authoritative AWS systems without copying
  all source data.

**Independent extensions:**

- **Connected data:** Virtualize or materialize selected domain graphs when graph
  reasoning, repeated queries, or latency justify it.
- **Memory:** Capture decisions, outcomes, reasoning, and feedback so future work
  can reuse proven experience.

**Visual:** Replace the current staircase with a foundation and two branches:

```text
                 Ontology-Based Semantic Layer
            meaning + mappings + policy + tools
                              |
                  query AWS data in place
                              |
               +--------------+--------------+
               |                             |
     Virtualize or materialize       Capture decisions and
     selected domain graphs               add memory
               |                             |
               +--------------+--------------+
                              |
                 Broader Knowledge Layer
```

Either branch can be added first. Neither is a prerequisite for the other.

### 8. Every governed action leaves an inspectable decision trace

**Purpose:** Explain trust for the current result and create the transition into
Agent Memory.

**Overview:** A decision trace links the result to the context that produced it.

**Trace contents:**

- **Meaning:** The business concepts resolved for the request.
- **Sources:** The authoritative systems, queries, and lineage used.
- **Policy:** The access and action checks applied.
- **Evidence:** The facts supporting the current result.
- **Precedent:** Relevant prior decisions, only when they influenced the result.
- **Outcome:** The result or action, its observed outcome, and feedback.

**Visual:** Show these as linked contributors to the result, not as a single chain.
Current evidence, policy checks, and optional precedent have different roles and
should remain visually distinct.

**Transition:** Decision traces explain the current result. Agent Memory makes
useful traces available to future requests.

## Transition to Neo4j Agent Memory

Keep the existing **Neo4j Agent Memory** section divider after slide 8. The first
Agent Memory slide can then focus on storage and retrieval of conversations,
durable knowledge, reasoning, and provenance without redefining why memory matters.

## Content and Asset Changes

| Current item | Action | Reason |
| --- | --- | --- |
| `A shared Knowledge Layer makes connected context reusable` | Keep as slide 2 and refine its copy | The visual clearly communicates the shared substrate and lighter-agents concept. |
| `exec-knowledge-layer.svg` | Revise and use on slide 3 | The current column labels and Enterprise Knowledge Graph caption do not match the official three-component framing closely enough. |
| `Three parts ground every answer` | Rename and revise as slide 4 | "Components" matches the source, and "request" supports both answers and actions. |
| Five-part ontology visual | Add as slide 5 | The current deck does not define the full scope of the Knowledge Layer ontology. |
| Request-flow slide | Keep and refine as slide 6 | The operating model is sound; the customer-exposure example makes it concrete. |
| `Start with meaning, then add data and memory` | Replace with slide 7 | The current staircase incorrectly implies that materialized data must precede memory. |
| `Policy and prior decisions make each result explainable` | Replace with slide 8 | The current chain conflates policy, evidence, and optional precedent. |

## Terminology Decisions

- Use **Knowledge Layer** as the umbrella term.
- Use **Knowledge Layer ontology**, **enterprise data**, and **memory** for the three
  components.
- Use **Ontology-Based Semantic Layer** once it is defined as the usual starting
  core. Do not shorten it to "semantic layer" because that term is commonly used
  for BI metric and query layers.
- Use **decision trace** as an output of an interaction and an element captured in
  memory, not as a fourth Knowledge Layer component.
- Keep BI semantic-layer, Context Graph, RDF, OWL, and progressive-schema
  distinctions out of the main flow. Add them only to an appendix if the audience
  needs them.

## Completion Check

Before finalizing the deck:

- Confirm that the slide titles alone tell a coherent problem-to-outcome story.
- Confirm that the definition slide says shared, governed, queryable, and
  actionable.
- Confirm that the three components use the official names and decision traces sit
  within memory.
- Confirm that all five ontology parts are legible at presentation distance.
- Confirm that domain concepts visibly map to authoritative technical assets.
- Confirm that query-in-place, virtualization, materialization, and memory are
  represented accurately.
- Confirm that the adoption slide shows independent extensions instead of required
  stages.
- Confirm that policy, evidence, and precedent are distinct in the decision trace.
- Render all affected slides and inspect them for clipping, crowded text, and weak
  contrast.
