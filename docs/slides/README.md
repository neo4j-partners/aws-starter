# AWS + Neo4j Presentation Site

This directory builds the Marp presentation gallery published through GitHub Pages.

## Current decks

The gallery builds these editable sources from the repository-level `slides/` directory:

- `slides/neocarta-slides.md`
- `slides/aws-neo4j-grounded-enterprise-ai.md`

The supporting SVG files remain beside the Markdown sources in `slides/` so local Marp preview continues to work.

## Archived decks

The earlier AWS + Neo4j in-depth deck series is retained under `docs/slides/archive/aws-in-depth/`. The build publishes those decks under `/archive/` and lists them in a separate Archive section on the gallery page.

## Quick start

Requires Node.js 22 LTS and a one-time dependency install in this directory.

```bash
cd docs/slides
npm ci
npm run serve
```

Open <http://localhost:8080/> to view the gallery.

For a live Marp preview of the two current source decks:

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

The workflow `.github/workflows/deploy-aws-in-depth-slides.yml` runs when `docs/slides/**`, `slides/**`, or the workflow itself changes on `main`. It installs dependencies, audits them, builds the gallery, and deploys `docs/slides/build/` to GitHub Pages.
