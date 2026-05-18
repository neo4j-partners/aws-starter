# Workshop Slides

Presentation-ready slides formatted for [Marp](https://marp.app/).

## Quick Start

Requires Node.js 22 LTS (`brew install node@22`) and a one-time `npm ci` in this directory.

```bash
cd docs/slides
npm ci
npm run serve
```

Opens at http://localhost:8080/ with the deck gallery.

## Deck Gallery

Build every deck in `aws-in-depth/` into `build/`:

```bash
npm run build:all
```

This creates a clickable gallery at `build/index.html` linking all six decks:

- `01-neo4j-for-agentic-ai-slides.html`
- `02-aircraft-data-model-slides.html`
- `03-graphrag-and-genai-slides.html`
- `04-graph-enriched-search-slides.html`
- `05-neo4j-aura-and-agents-slides.html`
- `06-neo4j-on-aws-slides.html`

The build script copies the `aws-in-depth/images/` assets into `build/images/` and writes `.nojekyll` so GitHub Pages serves the output as-is. The custom Marp themes in `themes/` (`finance`, `graph-lakehouse`) are registered during the build, so any deck can opt in through its frontmatter `theme:` field.

Build a single deck:

```bash
node scripts/build-theme-gallery.mjs 02-aircraft-data-model-slides.md
```

## Publishing

The GitHub Actions workflow `.github/workflows/deploy-aws-in-depth-slides.yml` runs on pushes to `main` that touch `docs/slides/**`. It runs `npm ci`, `npm audit`, and `npm run build:all`, then publishes `build/` to GitHub Pages. The full gallery is served at the Pages URL.

## Export to PDF or PPTX

```bash
cd docs/slides
npm run build:pdf
npm run build:pptx
```

These write to `dist/` using `marp --input-dir aws-in-depth`.

## Troubleshooting

**`require is not defined in ES module scope` error?**
- Marp CLI is incompatible with Node.js 25+. Install Node 22 LTS: `brew install node@22`

**Images not showing?**
- Run `npm run build:all`; the build script copies local image assets into `build/images/`.

## Slide Format

All slides use Marp markdown format with pagination, syntax-highlighted code blocks, tables, and two-column layouts. See any slide file for the frontmatter template.

## Additional Resources

- [Marp Documentation](https://marpit.marp.app/)
- [Marp CLI Usage](https://github.com/marp-team/marp-cli)
- [Marp Themes](https://github.com/marp-team/marp-core/tree/main/themes)
- [Creating Custom Themes](https://marpit.marp.app/theme-css)
