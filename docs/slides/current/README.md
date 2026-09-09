# Current AWS + Neo4j Slides

This folder contains the current AWS and Neo4j presentations in [Marp](https://marp.app/) format:

- `aws-neo4j-grounded-enterprise-ai.md`
- `fraud-data-architecture.md`
- `neocarta-slides.md`

## Quick Start

Use Node.js 22 LTS. Marp does not support Node.js 25 or later.

If you installed Node 22 with Homebrew, activate it for this terminal:

```bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
```

From `docs/slides`, run:

```bash
npm run preview
```

Open [http://localhost:8080/aws-neo4j-grounded-enterprise-ai.md](http://localhost:8080/aws-neo4j-grounded-enterprise-ai.md) in your browser. Marp reloads the slide deck when you save `aws-neo4j-grounded-enterprise-ai.md`.

Press <kbd>P</kbd> in the browser to open presenter view.

## Build a Standalone HTML File

Run this command from `docs/slides`:

```bash
npm run build:html
```

The deck uses local SVG and PNG files in this folder. Keep `--allow-local-files` in preview and build commands so Marp can load them.
