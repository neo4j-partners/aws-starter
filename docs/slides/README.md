# AWS + Neo4j Presentation Site

This directory builds the Marp presentation gallery published through GitHub Pages.

## Current decks

The gallery builds these editable sources from `docs/slides/current/`:

- `docs/slides/current/aws-neo4j-grounded-enterprise-ai.md`
- `docs/slides/current/fraud-data-architecture.md`
- `docs/slides/current/neocarta-slides.md`

The supporting SVG files remain beside the Markdown sources so local Marp preview continues to work. Presentation outlines and supporting notes live in `docs/slides/planning/`.

## Archived decks

The earlier AWS + Neo4j in-depth deck series is retained under `docs/slides/archive/aws-in-depth/`, while earlier working drafts live in `docs/slides/archive/drafts/`. The build publishes the in-depth decks under `/archive/`, but they are not listed on the gallery page.

## Quick start

Requires Node.js 22 LTS and a one-time dependency install in this directory.

```bash
cd docs/slides
npm ci
npm run serve
```

Open <http://localhost:8080/> to view the gallery.

For a live Marp preview of the current source decks:

```bash
npm run preview
```

## Build commands

Build the complete gallery, including the archive:

```bash
npm run build:all
```

Build one deck by source filename:

```bash
node scripts/build-theme-gallery.mjs neocarta-slides.md
```

Export the current decks to standalone formats:

```bash
npm run build:pdf
npm run build:html
npm run build:pptx
```

Build output is written to `docs/slides/build/` or `docs/slides/dist/`; both directories are ignored by Git.

## Publishing

The workflow `.github/workflows/deploy-aws-in-depth-slides.yml` runs when `docs/slides/**` or the workflow itself changes on `main`. It installs dependencies, audits them, builds the gallery, and deploys `docs/slides/build/` to GitHub Pages.
