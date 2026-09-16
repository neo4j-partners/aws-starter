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
section.appendix { background: linear-gradient(135deg, #0f172a 0%, #134e4a 100%); }
section.appendix h1 { color: #f8fafc; font-size: 48px; max-width: 980px; }
section.appendix h2 { color: #5eead4; font-size: 27px; font-weight: 500; max-width: 940px; }
section.examples table { font-size: 18px; }
section.examples td, section.examples th { padding: 6px 9px; }
section.examples code { font-size: 17px; }
section.code-pair pre { padding: 14px 18px; margin: 8px 0 14px; }
section.code-pair pre code { font-size: 18px; line-height: 1.35; }
.example-label { color: #0f766e; font-size: 20px; font-weight: 700; margin: 8px 0; }
.graph-code { background: #ffffff; border: 1px solid #b9d8d5; border-left: 5px solid #0d9488; font-family: monospace; font-size: 19px; margin: 12px 0; padding: 13px 16px; }
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

---

<!-- footer: 'Neosemantics · Technical appendix' -->
<!-- _class: appendix -->

# Appendix: What the Semantic Choices Look Like in the Graph

## Concrete examples of configuration, URI linking, vocabulary mapping, and SHACL validation

<!--
The main deck explains the lifecycle. This appendix makes four parts of
that lifecycle concrete by showing simplified RDF inputs, Neo4j graph
representations, and validation output.

The examples follow Neosemantics 4.0 behavior. Names can vary when a graph
uses different namespace prefixes or mapping definitions.
-->

---

<!-- _class: examples -->

## URI Handling Changes the Names Stored in the Graph

<div class="question"><code>ex:alice a ex:Person ; ex:given-name "Alice" .</code></div>

| `handleVocabUris` | Label and property in Neo4j | What it preserves |
| --- | --- | --- |
| **KEEP** | ``:`http://example.org/vocab#Person` ``<br>``n.`http://example.org/vocab#given-name` `` | Complete vocabulary URIs |
| **SHORTEN** | `:ex__Person`<br>`n.ex__given-name` | Namespace meaning through a prefix |
| **IGNORE** | `:Person`<br>`n.given-name` | Only each URI's local name |
| **MAP** | `:Person`<br>`n.givenName` | Explicit application-friendly names |

<div class="callout"><strong>Same RDF, different graph vocabulary:</strong> The configuration sets the balance between semantic fidelity and readable Cypher.</div>

<!--
KEEP retains the full vocabulary URI in labels, relationship types, and
property names. SHORTEN replaces namespaces with registered prefixes.
IGNORE keeps only local names. MAP applies explicit one-to-one mappings.

The example names are simplified and use an ex prefix registered for
http://example.org/vocab#.

Source: https://neo4j.com/labs/neosemantics/4.0/config/
-->

---

<!-- _class: examples -->

## Value and Type Settings Change Properties and Relationships

| RDF pattern | Setting | Resulting graph representation |
| --- | --- | --- |
| `ex:alice ex:altName "Al", "Ace"` | Default single value | `(:Resource {altName: "Ace"})` |
| Same repeated property | `handleMultival: "ARRAY"` | `(:Resource {altName: ["Al", "Ace"]})` |
| `ex:alice rdf:type ex:Person` | `typesToLabels: true` | `(:Resource:Person {uri: "...alice"})` |
| Same type statement | `typesToLabels: false` | `(:Resource {uri: "...alice"})-[:rdf__type]->(:Resource {uri: "...Person"})` |

<div class="callout"><strong>Structural choice:</strong> Labels make type checks concise. Type nodes make the RDF statement explicit and allow direct links to an ontology.</div>

<!--
Neosemantics keeps one literal value by default when an RDF property occurs
multiple times. ARRAY preserves every value in a Neo4j list.

RDF types become labels by default. Setting typesToLabels to false keeps the
type as a relationship between URI-identified resources. The displayed
rdf__type relationship assumes shortened namespace handling.

Source: https://neo4j.com/labs/neosemantics/4.0/import/
-->

---

<!-- _class: code-pair -->

## The Same URI Connects Instance Data to Its Ontology Class

<div class="example-label">1. Ontology import creates class nodes and hierarchy links</div>

```text
(:Class {name: "Employee", uri: "...#Employee"})
    -[:SCO]->
(:Class {name: "Person", uri: "...#Person"})
```

<div class="example-label">2. Instance import keeps <code>rdf:type</code> as a relationship</div>

```text
(:Resource {name: "Alice", uri: ".../alice"})
    -[:rdf__type]->
(:Class {name: "Employee", uri: "...#Employee"})
```

<div class="callout"><strong>URI identity does the linking:</strong> The instance points to the existing class node because both imports use the same <code>...#Employee</code> identifier.</div>

<!--
The ontology loader stores named classes as Class nodes with URI and name
properties. It stores rdfs:subClassOf as SCO relationships by default.

When instance data is imported with typesToLabels false, the rdf:type object
is resolved by URI. If the ontology class already has that URI, the instance
connects to the existing class node rather than creating a disconnected copy.

Sources:
https://neo4j.com/labs/neosemantics/4.0/importing-ontologies/
https://neo4j.com/labs/neosemantics/4.0/import/
-->

---

<!-- _class: code-pair -->

## One Mapping Gives RDF and Neo4j Different Names for the Same Link

```cypher
CALL n10s.nsprefixes.add(
  "skos", "http://www.w3.org/2004/02/skos/core#"
);
CALL n10s.mapping.add(
  "http://www.w3.org/2004/02/skos/core#narrower",
  "CHILD_CATEGORY"
);
```

<div class="flow">
  <div class="step"><strong>External RDF</strong><code>categoryA skos:narrower categoryB</code></div>
  <div class="arrow">↔</div>
  <div class="step"><strong>Mapping</strong><code>skos:narrower</code><br>is equivalent to<br><code>CHILD_CATEGORY</code></div>
  <div class="arrow">↔</div>
  <div class="step"><strong>Neo4j graph</strong><code>(categoryA)-[:CHILD_CATEGORY]->(categoryB)</code></div>
</div>

<!--
This is the mapping example from the Neosemantics guide. A relationship
named CHILD_CATEGORY in Neo4j is equivalent to skos:narrower in RDF.

Mappings are one-to-one pairs of equivalent vocabulary elements. The same
definition is used on import and export, so internal Cypher conventions do
not have to become the external semantic contract.

Source: https://neo4j.com/labs/neosemantics/4.0/mapping/
-->

---

<!-- _class: code-pair -->

## A SHACL Shape Makes the Expected Person Model Explicit

<div class="cols">
<div>

### Shape

```turtle
neo4j:PersonShape
  a sh:NodeShape ;
  sh:targetClass neo4j:Person ;
  sh:property [
    sh:path neo4j:name ;
    sh:datatype xsd:string ;
    sh:maxCount 1
  ] .
```

</div>
<div>

### Graph data

```text
(:Person {
  name: 42
})
```

- The node targets the `Person` shape.
- `name` exists, but its value is not a string.
- Validation reports the node and offending value.

</div>
</div>

<div class="callout"><strong>The shape is executable documentation:</strong> It states the rule in a standard form and gives validation a precise test.</div>

<!--
This simplified shape is based on the Person example in the guide. It says
that a Person name must be a string and may appear no more than once.

The example graph violates the datatype constraint because its name value
is numeric. Neosemantics loads SHACL from a URL or inline Turtle.

Source: https://neo4j.com/labs/neosemantics/4.0/validation/
-->

---

<!-- _class: examples -->

## Validation Returns a Specific Violation and Can Enforce It Three Ways

| focus node | node type | failed constraint | offending value | path | severity |
| --- | --- | --- | --- | --- | --- |
| `17` | `Person` | `DatatypeConstraintComponent` | `42` | `name` | `Violation` |

<div class="flow">
  <div class="step"><strong>Whole graph</strong>Find every violation in the current database.</div>
  <div class="arrow">·</div>
  <div class="step"><strong>Selected nodes</strong>Check only the resources involved in a workflow.</div>
  <div class="arrow">·</div>
  <div class="step"><strong>Transaction</strong>Reject a write when it introduces a violation.</div>
</div>

<div class="graph-code">CALL n10s.validation.shacl.validate()</div>

<!--
The validation report identifies the failing node, its type, the constraint
component, the offending value, the property path, and severity.

Neosemantics 4.0 supports validation of the whole graph, a selected node set,
or changes inside a transaction. The guide notes that version 4 implements a
significant portion of SHACL, but not the entire language.

Source: https://neo4j.com/labs/neosemantics/4.0/validation/
-->
