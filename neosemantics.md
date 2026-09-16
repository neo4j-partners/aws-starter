---
marp: true
theme: default
paginate: true
title: 'Neosemantics: Bringing RDF Semantics Into Neo4j'
description: 'A brief overview of RDF import, mapping, validation, reasoning, and export with Neosemantics 4.0.'
footer: 'Neosemantics · RDF and Neo4j'
---

<style>
section {
  --marp-auto-scaling-code: false;
  background: #f8fafc;
  color: #0f172a;
  font-size: 26px;
  line-height: 1.4;
  padding: 44px 64px 58px;
}
h1 { color: #0f172a; font-size: 56px; line-height: 1.15; }
h2 { color: #0f172a; font-size: 38px; line-height: 1.18; margin: 0 0 24px; }
h3 { color: #0f766e; font-size: 25px; margin: 0 0 12px; }
strong { color: #0f766e; }
li { margin: 10px 0; opacity: 1 !important; visibility: visible !important; }
ul, ol { margin: 8px 0; }
p { margin: 12px 0; }
code { font-size: 22px; }
pre { background: #eaf0f5; border: 1px solid #dbe4ed; padding: 20px 24px; }
pre code { line-height: 1.5; }
table { font-size: 22px; width: 100%; margin: 10px 0; }
th { background: #e2e8f0; }
td, th { border-color: #cbd5e1; padding: 9px 12px; }
footer { color: #64748b; font-size: 15px; left: 64px; bottom: 20px; }
section::after { color: #64748b; font-size: 16px; }
.callout { background: #e0f2f1; border-left: 5px solid #0d9488; margin-top: 22px; padding: 14px 18px; font-size: 23px; }
.note { color: #475569; font-size: 20px; margin-top: 18px; }
.cols { display: grid; gap: 32px; grid-template-columns: 1fr 1fr; }
.cols > div { min-width: 0; }
.flow { display: flex; align-items: stretch; gap: 12px; margin: 24px 0; }
.flow .step { background: #ffffff; border: 1px solid #b9d8d5; border-top: 5px solid #0d9488; border-radius: 6px; flex: 1; padding: 18px 16px; font-size: 22px; }
.flow .step strong { display: block; font-size: 24px; margin-bottom: 8px; }
.flow .arrow { align-self: center; color: #0f766e; font-size: 30px; }
.label { color: #0f766e; font-size: 20px; font-weight: 700; letter-spacing: 1px; margin-bottom: 18px; }
.question { border-left: 5px solid #0d9488; padding: 10px 20px; font-size: 27px; background: #ecfeff; }
section.lead { background: linear-gradient(135deg, #f8fafc 0%, #dff5f2 100%); }
section.lead h1 { max-width: 1050px; }
section.lead .subtitle { color: #0f766e; font-size: 32px; max-width: 1000px; margin-top: 26px; }
section.lead .note { margin-top: 60px; }
section.config table { font-size: 20px; }
section.config td, section.config th { padding: 7px 10px; }
section.close { background: linear-gradient(135deg, #f8fafc 0%, #dff5f2 100%); }
</style>

<!-- _class: lead -->

<div class="label">SEMANTIC INTEROPERABILITY FOR NEO4J</div>

# Neosemantics: Bringing RDF Semantics Into Neo4j

<div class="subtitle">Import, explore, validate, reason over, and export semantic data with the Neo4j property graph model.</div>

<div class="note">A brief overview based on the Neosemantics 4.0 user guide.</div>

<!--
Neosemantics, also called n10s, is a Neo4j plugin for working with RDF.
It connects standards-based semantic data with the Neo4j property graph
and Cypher query model.

This overview follows the lifecycle of semantic data through Neo4j:
configuration, import, graph use, validation, reasoning, and export.
-->

---

## RDF and Property Graphs Need an Interoperability Layer

<div class="cols">
<div>

### RDF brings shared meaning

- Global identifiers through URIs
- Shared vocabularies and ontologies
- A W3C standard for data interchange

</div>
<div>

### Neo4j brings graph application strengths

- A direct property graph model
- Cypher for exploration and analysis
- A mature graph application platform

</div>
</div>

<div class="callout"><strong>The gap:</strong> Teams need to use semantic standards and Neo4j graph capabilities without maintaining disconnected copies or translation logic.</div>

<!--
RDF and the property graph model emphasize different strengths.
RDF provides stable identifiers, shared vocabularies, and a standard
exchange model. Neo4j provides a direct graph model and Cypher.

The practical challenge is moving between them while retaining the
semantic details that make the data understandable and reusable.
-->

---

## Neosemantics Connects Standards and Graph Applications

<div class="flow">
  <div class="step"><strong>RDF sources</strong>Files, linked data, APIs, and SPARQL endpoints.</div>
  <div class="arrow">→</div>
  <div class="step"><strong>Neosemantics</strong>Parses, configures, maps, and validates semantic data.</div>
  <div class="arrow">→</div>
  <div class="step"><strong>Neo4j</strong>Stores the data as a property graph for Cypher and applications.</div>
  <div class="arrow">↔</div>
  <div class="step"><strong>RDF consumers</strong>Receive RDF generated from selected graph data.</div>
</div>

- Import RDF into Neo4j.
- Export imported RDF or native property graph data as RDF.
- Add model mapping, SHACL validation, and inferencing.

<div class="callout"><strong>Round trip:</strong> Imported RDF can be exported without losing triples when the required namespace information is retained.</div>

<!--
Neosemantics sits at the boundary between the RDF ecosystem and Neo4j.
It handles RDF parsing and graph representation on the way in, then can
generate RDF again on the way out.

The round-trip guarantee depends on preserving the semantic identifiers
needed to reconstruct the original triples. Configuration therefore comes
before import, not after it.
-->

---

<!-- _class: config -->

## Configuration Decides What the Neo4j Graph Will Look Like

| Decision | Options | Why it matters |
| --- | --- | --- |
| **Vocabulary URIs** | Keep, shorten, ignore, or map | Balances RDF fidelity with readable Cypher names |
| **Multiple values** | Keep one value or use arrays | Controls how repeated RDF properties are stored |
| **Language tags** | Preserve or filter | Supports multilingual literals and selective imports |
| **Custom data types** | Retain or simplify | Determines how specialized literal types survive |
| **RDF types** | Labels or connected nodes | Changes how instances relate to ontology concepts |

<div class="callout"><strong>Required first:</strong> Create a uniqueness constraint on <code>:Resource(uri)</code> and initialize the graph configuration before importing RDF.</div>

<!--
The graph configuration defines the translation between the RDF model
and the property graph model. It affects names, values, types, and the
ability to export the graph as RDF later.

Neosemantics also requires a uniqueness constraint on Resource URI values.
The configuration should be treated as an architectural decision because
changing it after data has been loaded requires clearing the imported graph.
-->

---

## RDF Statements Become Familiar Graph Elements

| RDF statement | Neo4j representation |
| --- | --- |
| `ex:alice rdf:type ex:Person` | `Person` label on the Alice node |
| `ex:alice ex:name "Alice"` | `name` property on the Alice node |
| `ex:alice ex:knows ex:bob` | `KNOWS` relationship from Alice to Bob |
| Resource identifier | `uri` property on a `Resource` node |

<div class="callout"><strong>The result:</strong> Semantic data becomes a property graph that can be explored with Cypher while retaining its RDF identity.</div>

<!--
This slide shows the core transformation. Literal values become node
properties. Links between resources become graph relationships. RDF types
become labels by default, and the source URI remains on the resource node.

The exact labels, relationship types, and property names depend on how
vocabulary URIs are configured.
-->

---

## Preview and Filter RDF Before It Reaches the Graph

- **Stream first:** Parse RDF and inspect triples without persisting them.
- **Check structure:** Review subjects, predicates, objects, literal values, and data types.
- **Limit scope:** Exclude predicates or select a language during import.
- **Customize:** Use Cypher to decide how streamed triples become graph structures.

<div class="callout"><strong>Why preview:</strong> A small inspection step exposes naming, density, and modeling issues before they become part of the stored graph.</div>

<!--
Neosemantics can stream parsed RDF as records before anything is written.
This gives teams a chance to inspect the source and apply their own Cypher
logic when the standard import transformation is not the desired model.

Import parameters can also narrow the data by predicate or language tag.
That is useful when only part of a large semantic dataset is relevant.
-->

---

## One Procedure Loads Common RDF Sources and Formats

```cypher
CALL n10s.rdf.import.fetch(
  "https://example.org/data.ttl",
  "Turtle"
);
```

<div class="cols">
<div>

### Sources

- Local or remote files
- HTTP services that return RDF
- RDF generated by SPARQL endpoints

</div>
<div>

### Serializations

- Turtle and N-Triples
- JSON-LD and RDF/XML
- TriG and N-Quads

</div>
</div>

<!--
The main import procedure accepts a source URL, the RDF serialization,
and optional parameters. A source can be a static file or a service that
produces RDF dynamically.

Advanced request settings support headers and POST payloads, which makes
it possible to submit a query to an RDF-producing endpoint and import the
result directly.
-->

---

## Ontologies Bring Shared Vocabulary Into the Same Graph

- Import classes and properties from an ontology.
- Load instance data using the same URI identifiers.
- Connect instances to ontology concepts when RDF types are modeled as nodes.
- Explore class hierarchies and instance relationships with Cypher.

<div class="callout"><strong>URI identity does the linking:</strong> Consistent identifiers allow ontology elements and instance data to meet in the same graph.</div>

<!--
Ontology import gives the graph an explicit semantic model. Because RDF
resources use URIs, ontology elements and instance data can connect when
they refer to the same identifiers.

The choice between representing RDF types as labels or nodes matters here.
Type nodes make the link between instances and ontology classes explicit,
while labels provide a simpler property graph representation.
-->

---

## Mappings Keep External Semantics and Internal Names Aligned

<div class="flow">
  <div class="step"><strong>External vocabulary</strong>Stable RDF URIs and published semantic terms.</div>
  <div class="arrow">↔</div>
  <div class="step"><strong>n10s mapping</strong>One-to-one mappings applied during import or export.</div>
  <div class="arrow">↔</div>
  <div class="step"><strong>Neo4j vocabulary</strong>Readable labels, relationship types, and property names.</div>
</div>

- Keep standards-based identifiers at the boundary.
- Use application-friendly names inside the graph.
- Apply the same mapping definitions in both directions.

<div class="callout"><strong>Practical result:</strong> Interoperability does not require awkward names in everyday Cypher queries.</div>

<!--
Mapping separates the external semantic contract from the internal graph
vocabulary. For example, an RDF property with a long or inconvenient name
can map to a concise property name in Neo4j.

Mappings are one-to-one and can be used during both import and export.
That keeps the transformation explicit and reversible.
-->

---

## SHACL Turns Semantic Expectations Into Validation Checks

<div class="question">Does the graph conform to the structures and values the domain expects?</div>

- Load SHACL shapes that describe expected graph constraints.
- Validate Neo4j data against those shapes.
- Identify resources and properties that violate the rules.
- Review or correct issues before downstream use.

<div class="callout"><strong>Quality gate:</strong> Shared vocabulary becomes more reliable when the graph can also be checked against shared rules.</div>

<!--
RDF vocabularies describe meaning. SHACL adds machine-readable expectations
about graph structure and values.

Neosemantics can validate Neo4j graph data against SHACL shapes and return
the violations. This creates a clear quality checkpoint between ingestion
and application use.
-->

---

## Inference Exposes Knowledge That Was Only Implicit

<div class="flow">
  <div class="step"><strong>Asserted fact</strong>A resource belongs to a specific class.</div>
  <div class="arrow">+</div>
  <div class="step"><strong>Ontology</strong>The class belongs to a broader class hierarchy.</div>
  <div class="arrow">→</div>
  <div class="step"><strong>Inferred context</strong>The broader classification becomes available to queries.</div>
</div>

- Reason over class and property relationships.
- Use ontology structure without manually storing every implied statement.
- Combine explicit graph facts with semantic context in application queries.

<!--
Semantic models often contain knowledge that is implied rather than written
as a direct statement. A class hierarchy is a simple example: membership in
a specific class can imply membership in a broader class.

Neosemantics exposes reasoning functions that let queries use this ontology
structure without copying every possible implied relationship into the graph.
-->

---

## Export Keeps Neo4j Connected to the RDF Ecosystem

- Generate RDF on demand from selected Neo4j data.
- Recreate RDF triples from imported data when semantic identifiers were preserved.
- Publish native property graph data through RDF serializations.
- Apply mappings and control how much graph context is included.

<div class="callout"><strong>Open boundary:</strong> Neo4j can serve graph applications and still exchange data with standards-based semantic systems.</div>

<!--
Export completes the interoperability story. Neosemantics can generate RDF
from a graph created through RDF import and from a native property graph.

The export can target selected nodes or Cypher results and can use model
mappings. If an imported graph discarded namespace information, an exact
round trip is no longer possible, which reinforces the importance of the
initial configuration.
-->

---

<!-- _class: close -->

## Prove the Round Trip With One Small Use Case

1. **Choose:** Select one RDF dataset or ontology with a clear purpose.
2. **Configure:** Decide which identifiers and semantic details must survive.
3. **Preview:** Inspect the triples and confirm the intended graph shape.
4. **Import:** Load the data and test representative Cypher queries.
5. **Check:** Validate the graph and apply reasoning where it adds value.
6. **Export:** Generate RDF and confirm that the required semantics remain intact.

<div class="callout"><strong>Success:</strong> The same semantic data works naturally in Neo4j and remains usable across the RDF ecosystem.</div>

<div class="note">Sources: Neo4j Labs Neosemantics 4.0 User Guide, Introduction, and Importing RDF Data.</div>

<!--
Close with a small, testable adoption path. One dataset is enough to prove
the decisions that matter: graph configuration, Cypher usability, semantic
validation, reasoning value, and RDF export fidelity.

Sources used for this deck:
https://neo4j.com/labs/neosemantics/4.0/
https://neo4j.com/labs/neosemantics/4.0/introduction/
https://neo4j.com/labs/neosemantics/4.0/import/
-->
