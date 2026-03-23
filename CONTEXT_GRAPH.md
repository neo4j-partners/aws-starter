# Context Graphs: The Missing Layer for AI

> **Source**: [Foundation Capital](https://foundationcapital.com/why-are-context-graphs-are-the-missing-layer-for-ai/) — January 16, 2026
> **By**: Ashu Garg (Foundation Capital), with Jamin Ball (Altimeter) and Animesh Koratana (PlayerZero)

---

## The Core Problem

The bottleneck for AI agents moving into production isn't intelligence — models are already "good enough" for most use cases. The bottleneck is **context**. Agents can read data and take action, but they don't capture the *reasoning behind decisions*. Why was an incident escalated? Why did a customer get an exception? Why was one fix prioritized over another?

That reasoning — what Foundation Capital calls **decision traces** — is scattered across Slack, email, support tickets, and other tools, or never recorded at all. It almost never makes it into a system of record.

---

## What Is a Context Graph?

A context graph is a structured representation of decision traces captured from real workflows. It records not just *what* happened, but *why* it happened and *how entities relate to each other*. The thesis is that companies that capture these decision traces and structure them into context graphs will own the most valuable layer in enterprise AI.

---

## Key Arguments

### 1. Systems of Record Aren't Dying — The Bar Is Rising

Agents aren't replacing Salesforce or ServiceNow, but they're raising what a good system of record looks like. The analogy: Amadeus (the travel GDS) didn't go to zero when Booking.com emerged — it's still a $30B company — but the OTAs built on top became a hundreds-of-billions-dollar opportunity. The same dynamic is playing out with AI agents sitting atop traditional SaaS.

### 2. Decisions Are Cross-Functional, but Systems of Record Are Siloed

Systems of record grew up owned by individual functions (sales, SRE, support), but decisions cut across functions and chains of command. A support ticket escalation might touch the ticketing system, observability tools, and the codebase. No single system captures the full decision trail.

### 3. Implicit Capture Beats Explicit Training

Getting humans to explicitly train agents or enter decision rationale is as hard as getting salespeople to keep CRM data clean. The winning approach is *implicit* capture — delivering enough value in the product that decision traces are captured as a byproduct of using it, creating a flywheel.

### 4. Context Graphs Create Durable Moats

Point solutions that don't externalize learning into context graphs will be displaced. The durable part of enterprise AI comes from using point solutions as a wedge to build a compounding data asset. The early movers who capture decision traces and translate them into a context graph will create a flywheel that becomes the moat.

### 5. Verticalized, Not Universal

Context graphs will likely be verticalized by workflow domain (production engineering, go-to-market, etc.) rather than universal like a data warehouse. You need to be embedded in a specific workflow's UX to capture the decision traces that feed the graph. The best context graph companies will be verticalized because to build one, you need to be embedded in a specific workflow.

---

## The Trust and Authority Problem

Enterprise buyers need observability before they'll grant autonomy. People want to know: why did the agent do this? When did it fail? Where did it fail? We're currently in a trust-building phase where AI drafts but humans review. Context graphs help build that trust by making decision reasoning transparent and auditable.

The ROI of agents is "painfully obvious" — companies like Cursor scale quickly because value is visible in minutes, not months. But authority remains the bottleneck. 2026 is expected to be the year this changes.

---

## The Bear Case

Context graphs could fail the same way **semantic layers** in data warehouses did — great in theory but stalled by human disagreement on definitions and the fact that truth is dynamic, not static.

What gives confidence is that unlike semantic layers (which required explicit, top-down definition workshops with 50 people spending weeks agreeing on terms), context graphs are *implicitly* created by delivering value to customers. The graphs are a byproduct of useful work, not an upfront modeling exercise.

The other risk: even when two people agree on a definition, that agreement is out of date minutes later. Truth isn't static — it's dynamic. Time and organizational context are important dimensions that any context graph must account for.

---

## The Data Infrastructure Question

Snowflake and Databricks are moving toward transactional systems (Lakebase/Neon, Crunchy Data acquisition). The panel sees data infrastructure companies as better positioned than traditional systems-of-record companies because of cost economics and architecture.

However, data warehouses aren't oriented around the write path, making it harder for them to be the storage layer for context graphs. The "front door" of CRMs may collapse into data warehouses, but the ergonomics of capturing judgment — the context graph itself — will likely live in verticalized applications.

The primitives required to represent context graphs come down to probabilistic data structures like embeddings, with an interesting connection to continual learning where some learning is externalized into the context graph and some is internalized into model weights.

---

## 2026 Predictions from the Panel

- **Jamin Ball**: At least one very large AI IPO (a major lab like OpenAI/Anthropic or an application company like Cursor)
- **Animesh Koratana**: World models beyond physics will be the most slept-on AI opportunity; many AI point solutions that don't build context graph flywheels will die
- **Ashu Garg**: Massive wave of enterprise agent adoption benefiting incumbents and startups alike

---

## Key Takeaways

1. The bottleneck for production AI agents is context, not intelligence
2. Decision traces — the reasoning behind decisions — are the most valuable data that organizations aren't capturing today
3. Context graphs structure these decision traces into a queryable, connected representation
4. The companies that capture decision traces implicitly (as a byproduct of value delivery) will build compounding flywheels
5. Context graphs will be verticalized by workflow domain, not universal
6. Traditional systems of record won't die, but their relative profit pool will decline as new layers capture more value on top

---

## References

- [Why context graphs are the missing layer for AI — Foundation Capital](https://foundationcapital.com/why-are-context-graphs-are-the-missing-layer-for-ai/)
- [AI's trillion-dollar opportunity: Context graphs — Foundation Capital](https://foundationcapital.com/context-graphs-ais-trillion-dollar-opportunity/)
- [Long Live Systems of Record — Jamin Ball (Clouded Judgement)](https://cloudedjudgement.substack.com/p/clouded-judgement-121225-long-live)
