# AWS + Neo4j Presentation Site

This folder builds the Marp slide gallery. GitHub Pages publishes the gallery.

## Overview

- **Current decks:** The editable deck sources live in [`docs/slides/current/`](./current/).
- **Images:** Each deck keeps its images in `docs/slides/current/images/<deck-name>/`. Marp preview and the gallery build both find images through these relative paths.
- **Planning notes:** Outlines and supporting notes live in [`docs/slides/planning/`](./planning/).
- **Archive:** Older decks and images live in [`docs/slides/archive/`](./archive/).
- **Publishing:** A GitHub Actions workflow builds the gallery and deploys it to GitHub Pages.

## Quick start

You need Node.js 22 LTS and Python 3. Run these commands from the repo root:

```bash
cd docs/slides
npm ci                 # one-time dependency install
npm run serve          # build the gallery and serve it
npm run preview        # live Marp preview of the current decks
```

Open <http://localhost:8080/> to view the gallery. The `serve` command builds
the gallery first, then serves `docs/slides/build/` with Python on port 8080.

## Current decks

The gallery page lists these decks from `docs/slides/current/`:

- **`hyperscaler-overview.md`:** This deck compares how AWS, Databricks, Google Cloud, IBM, and Microsoft build the same data and AI stack. It shows where they differ and where a customer-owned graph fits.
- **`aws-neo4j-finance-overview.md`:** This deck gives a fraud-investigation overview of Neo4j on AWS. It covers connected context, Virtual Graph, Amazon Quick over MCP, GraphRAG agents, and agent memory.
- **`fraud-data-architecture.md`:** This deck shows how AWS transaction data and Neo4j work together to expose a fraud ring.
- **`neocarta-slides-v2.md`:** This deck is the revised Neocarta deck. It has new slide order and titles, with 14 main slides and five appendix slides.
- **`neosemantics.md`:** This deck gives a Neosemantics 4.0 overview. Its technical appendix shows graph representations, URI linking, mappings, and SHACL validation.
- **`enterprise-knowledge-layer.md`:** This deck shows how a shared, governed Knowledge Layer gives every agent the same business meaning, source routing, policy, and decision traces.

The export commands build `aws-neo4j-finance-overview.md`,
`fraud-data-architecture.md`, `neocarta-slides-v2.md`, `neosemantics.md`, and
`neocarta-slides.md`. The folder also holds `neocarta-aws-appendix.md`. Neither
the gallery nor the exports build it.

## Resources section

The gallery page also has an **AWS + Neo4j Resources** section below the decks.
The `resources` array in [`scripts/build-theme-gallery.mjs`](./scripts/build-theme-gallery.mjs)
defines its cards:

- **Starter kit:** This card gives an overview of the aws-starter repo. It links to the `demos/`, `integrations/`, and `patterns/` folders on GitHub, with a short summary of each.
- **Workshop:** This card links to the GraphRAG with Neo4j on AWS workshop and its source repo. Tags show the module count, the region, and the estimated cost.

To add a resource, add an entry to the `resources` array. Each entry needs a
`label`, `title`, `description`, and `actions`. The `links` and `tags` fields
are optional.

## Archived decks

- **`docs/slides/archive/aws-in-depth/`:** This folder holds the earlier AWS + Neo4j in-depth deck series. The build publishes these decks under `/archive/`, but the gallery page does not list them.
- **`docs/slides/archive/drafts/`:** This folder holds earlier working drafts.
- **`docs/slides/archive/superseded-images/`:** This folder holds images that a newer version replaced. No current deck uses them.

## Build commands

Run these commands from `docs/slides/`.

```bash
npm run build:all                                      # full gallery, including the archive
node scripts/build-theme-gallery.mjs neocarta-slides-v2.md   # one deck by source filename
npm run build:pdf                                      # export decks to PDF
npm run build:html                                     # export decks to standalone HTML
npm run build:pptx                                     # export decks to PowerPoint
```

- **Gallery build:** The gallery commands write to `docs/slides/build/`. Each run deletes that folder first. A single-deck build accepts any gallery or archive deck filename.
- **Exports:** The export commands write to `docs/slides/dist/`. Each run deletes that folder first.
- **Git:** Git ignores both output folders.

## Publishing

The workflow [`.github/workflows/deploy-aws-in-depth-slides.yml`](../../.github/workflows/deploy-aws-in-depth-slides.yml)
runs on pushes to `main` that change `docs/slides/**` or the workflow file. You
can also start it by hand. The workflow runs these steps:

1. It installs dependencies with `npm ci`.
2. It audits dependencies with `npm audit --audit-level=high`.
3. It builds the gallery with `npm run build:all`.
4. It deploys `docs/slides/build/` to GitHub Pages.
