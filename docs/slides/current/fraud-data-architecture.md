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
  font-size: 58px;
}

h2 {
  color: #0f172a;
  font-size: 37px;
  margin-bottom: 18px;
}

code {
  font-size: 21px;
}

section.lead {
  background: linear-gradient(135deg, #f8fafc 0%, #ecfeff 100%);
}

section.lead h1 {
  max-width: 1050px;
}

section.lead h2 {
  color: #0f766e;
  font-size: 29px;
  font-weight: 500;
  max-width: 980px;
}

.callout {
  background: #ecfeff;
  border-left: 6px solid #14b8a6;
  margin-top: 18px;
  padding: 12px 18px;
}

section.data-sources-overview {
  padding: 24px 64px;
}

section.data-sources-overview h2 {
  margin: 0 0 8px;
}

section.data-sources-overview p {
  margin: 0;
  text-align: center;
}

section.data-sources-overview .callout {
  font-size: 22px;
  margin-top: 8px;
  padding: 8px 18px;
}

section.fraud-overview {
  padding: 24px 48px;
}

section.fraud-overview h2 {
  margin: 0 0 8px;
}

section.fraud-overview p {
  margin: 0;
  text-align: center;
}

li {
  opacity: 1 !important;
  visibility: visible !important;
}
</style>

<!-- _class: lead -->

# Fraud Data Architecture

## What data lives where across AWS and Neo4j

---

## A fraud ring shows why an investigation needs both views

One transfer can look ordinary. Its connections can reveal coordinated activity.

```text
Customer A → Account A → Device X ← Account B ← Customer B

Account A → Account B → Account C → Account A
```

- **Shared identity signal:** Two customers use the same device.
- **Circular movement:** Funds return to the starting account.
- **Corroborating evidence:** Phone numbers, addresses, merchants, and timing strengthen or weaken the case.

<div class="callout"><strong>Investigation question:</strong> Which accounts form a circular payment chain, and what AWS activity makes that chain unusual?</div>

---

## Why a knowledge graph fits fraud investigations

- **Entities become nodes:** Customers, accounts, devices, addresses, merchants, alerts, and cases.
- **Connections become relationships:** Owns, uses, transferred to, paid, registered at, and triggered.
- **The model mirrors the investigation:** Connections are explicit instead of hidden behind foreign keys and join tables.
- **New context layers in:** Add signals, typologies, policies, and entity types without redesigning the whole model.
- **One pattern supports many risks:** Apply the same approach to fraud, AML, cyber investigations, and supply-chain risk.

<div class="callout"><strong>Connected domains fit graphs:</strong> The data model follows the network an investigator needs to explore.</div>

---

<!-- _class: fraud-overview -->

## The fraud ring as a property graph

![h:600](./fraud-ring-property-graph-detailed.svg)

---

## What the graph enables for investigators

| Investigation question | How the graph helps |
| --- | --- |
| **Which accounts share a device or address?** | Traverse identity relationships across customers and accounts. |
| **Does money return to its starting point?** | Detect circular transfer paths. |
| **What is exposed through a compromised account?** | Follow downstream accounts, merchants, and counterparties. |
| **Which prior cases resemble this pattern?** | Connect findings to typologies, policies, evidence, and outcomes. |

<div class="callout"><strong>Graph advantage:</strong> Relationship questions become traversals instead of expanding join chains.</div>

---

<!-- _class: workload-comparison -->

## AWS analyzes activity; Neo4j reveals connections

<div class="cols">
<div>

### Amazon Athena: transaction activity over time

- **Aggregation:** Totals, averages, ranges, and standard deviation for amounts and risk scores.
- **Time-series trends:** Hourly, daily, and monthly rollups by account, merchant, or channel.
- **Filtering and ranking:** Transactions above P95 and accounts generating the most alerts.
- **Key-based joins:** Connect transactions to accounts, customers, and merchants.
- **Dashboards:** Transaction volume, alerts, exposure, losses, and case throughput.

</div>
<div>

### Neo4j Cypher: how the fraud network is connected

- **Multi-hop traversal:** Follow funds across accounts, devices, addresses, and merchants.
- **Pattern search:** Identify circular transfers and shared identity signals.
- **Path and reachability:** Find everything downstream of a compromised account.
- **Variable depth:** Investigate chains whose length is unknown in advance.
- **GraphRAG:** Link entities to KYC documents, typologies, policies, and prior cases.

</div>
</div>

---

<!-- _class: data-sources-overview -->

## A dual data architecture puts each workload in the right place

![w:940](./dual-data-architecture-aws.svg)

<div class="callout"><strong>Two query paths:</strong> Athena retrieves AWS transactions; Cypher traverses connected context in Neo4j.</div>

---

## One investigation uses both data paths

1. **Detect in AWS:** Athena identifies unusual transactions, accounts, or merchants in governed S3 data.
2. **Expand in Neo4j:** The investigation starts from those identifiers and traverses the connected network.
3. **Find the pattern:** Cypher detects shared identities, circular transfers, and exposed entities.
4. **Explain the finding:** Policies, fraud typologies, KYC documents, and prior cases establish significance.
5. **Return the result:** Graph findings flow back to AWS for analytics, reporting, and case workflows.

<div class="callout"><strong>Combined outcome:</strong> AWS supplies authoritative activity; Neo4j supplies the connected context needed to investigate it.</div>
