---
marp: true
theme: default
paginate: true
---

<style>
section {
  --marp-auto-scaling-code: false;
  color: #0f172a;
  font-size: 26px;
  padding: 48px 64px;
}

h1 {
  color: #0f172a;
  font-size: 52px;
}

h2 {
  color: #0f172a;
  font-size: 37px;
  margin-bottom: 18px;
}

h3 {
  color: #0f766e;
  font-size: 26px;
}

table {
  font-size: 21px;
  width: 100%;
}

th {
  background: #e2e8f0;
}

td, th {
  padding: 9px 13px;
}

code {
  font-size: 21px;
}

small {
  color: #64748b;
  font-size: 13px;
}

section.lead {
  background: linear-gradient(135deg, #f8fafc 0%, #ecfeff 100%);
}

section.lead h1 {
  font-size: 58px;
  max-width: 1050px;
}

section.lead h2 {
  color: #0f766e;
  font-size: 29px;
  font-weight: 500;
  max-width: 980px;
}

.promise {
  color: #475569;
  font-size: 21px;
  margin-top: 72px;
}

.callout {
  background: #ecfeff;
  border-left: 6px solid #14b8a6;
  margin-top: 18px;
  padding: 12px 18px;
}

.status-now {
  color: #047857;
  font-weight: 700;
}

.status-preview {
  color: #a16207;
  font-weight: 700;
}

.status-roadmap {
  color: #7c3aed;
  font-weight: 700;
}

.cols {
  display: grid;
  gap: 30px;
  grid-template-columns: 1fr 1fr;
}

.center {
  text-align: center;
}

.tight li {
  margin: 6px 0;
}

li {
  opacity: 1 !important;
  visibility: visible !important;
}

section.section {
  background: linear-gradient(135deg, #0f172a 0%, #134e4a 100%);
}

section.section h1 {
  color: #f8fafc;
  font-size: 44px;
  max-width: 980px;
}

section.section h2 {
  color: #5eead4;
  font-size: 25px;
  font-weight: 500;
  max-width: 940px;
}

</style>

<!-- _class: lead -->

# Neo4j on AWS

## Rosetta SDL today, then Neocarta's planned AWS extension

<div class="promise">A focused AWS companion to the Neocarta overview</div>

<!--
This deck covers two ways to use Neo4j for semantic data access on AWS.

Rosetta SDL is an AWS reference application available today. Neocarta is a
cross-platform project with a planned AWS connector. The next slides explain
Rosetta SDL first, then show how Neocarta will extend to AWS.
-->

---

## Rosetta SDL Provides an End-to-End AWS Path

Rosetta SDL is an AWS reference application for finding and querying governed data.

- **Semantic map:** Links business language to AWS Glue and Athena metadata in Neo4j
- **Agent access:** Serves discovery tools to agents through MCP
- **Search:** Combines graph traversal, full-text search, and embeddings
- **Query execution:** Plans, checks, and runs Athena queries
- **Deployment:** Includes an API, admin interface, authentication, and an AWS CDK stack

<div class="callout"><strong>Data boundary:</strong> Source data stays in AWS. The graph stores metadata and relationships.</div>

<!--
Rosetta SDL provides a complete AWS path from business question to query
result.

It maps AWS Glue and Athena metadata into Neo4j and links that metadata to
business language. Agents use MCP tools to find the right data. Rosetta SDL
then plans, validates, and runs the Athena query.

It also includes the application and deployment pieces needed to operate
the workflow on AWS.
-->

---

## Rosetta SDL and Neocarta Share the Same Core Pattern

Both projects use Neo4j to connect technical metadata with business meaning.

- **Semantic map:** Links tables, columns, joins, metrics, and business terms
- **Catalog discovery:** Helps agents browse and search for the right assets
- **MCP access:** Gives agents focused retrieval tools
- **Hybrid retrieval:** Combines graph relationships, text search, and vectors
- **Metadata only:** Keeps source data in its original platform

<!--
The shared pattern is simple. Both projects build a semantic map in Neo4j,
use several retrieval methods, and serve context to agents through MCP.

The source data stays in place. Neo4j stores the metadata and relationships
that help the agent understand what to query.
-->

---

## Rosetta SDL Goes Deep on AWS; Neocarta Spans Platforms

- **Rosetta SDL:** A complete AWS application built around Glue, Athena, S3 Vectors, and Amazon Bedrock
- **Neocarta:** A library, graph model, CLI, and MCP server for thirteen source connectors
- **Query execution:** Rosetta SDL runs Athena queries. Neocarta supplies context to a separate query tool
- **Safety controls:** Rosetta SDL checks SQL in the execution path. Neocarta leaves execution controls to the query tool
- **Metrics:** Rosetta SDL compiles approved metrics to SQL. Neocarta retrieves metric definitions for the agent

<div class="callout"><strong>Choose by scope:</strong> Use Rosetta SDL for a complete AWS application. Use Neocarta to bring several platforms into one agent workflow.</div>

<!--
The main difference is scope.

Rosetta SDL is a complete application that goes deep on AWS. Neocarta is a
cross-platform context layer that works with an agent and a separate query
tool.

This boundary also explains the safety model. Rosetta SDL can check SQL
because it runs the query. Neocarta does not run the query, so the query tool
must enforce those controls.
-->

---

## Neocarta Will Extend to AWS Through Glue Data Catalog

The planned connector will bring AWS metadata into the same graph used for other platforms.

- **Connect:** Read S3 Tables metadata through the Glue federated catalog
- **Normalize:** Map AWS databases, tables, columns, and metadata into the shared model
- **Enrich:** Link AWS assets to business terms, joins, and usage history
- **Serve:** Use the same MCP retrieval tools as other platforms
- **Validate:** Run governed Athena queries over S3 Tables

<div class="callout"><strong>Planned boundary:</strong> S3 Tables remains the source of record. Athena runs the query. Neocarta supplies the context.</div>

<!--
The planned AWS extension starts with a Glue Data Catalog connector.

The connector will read S3 Tables metadata through the Glue federated
catalog and map it into Neocarta's shared graph model. Existing retrieval
tools can then serve that metadata to agents.

The system boundary stays clear. S3 Tables owns the data, Athena runs the
query, and Neocarta supplies semantic context.
-->

<!-- AWS sources: https://docs.aws.amazon.com/glue/latest/dg/enable-s3-tables-catalog-integration.html and https://docs.aws.amazon.com/athena/latest/ug/gdc-register-s3-table-bucket-cat.html -->
