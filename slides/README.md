# AWS and Neo4j Grounded Enterprise AI Slides

This folder contains the AWS and Neo4j grounded enterprise AI deck in [Marp](https://marp.app/) format. The main deck is `aws-neo4j-grounded-enterprise-ai.md`.

## Quick Start

Use Node.js 22 LTS. Marp does not support Node.js 25 or later.

If you installed Node 22 with Homebrew, activate it for this terminal:

```bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
```

From the repository root, run:

```bash
npx --yes @marp-team/marp-cli@4.4.0 --input-dir slides --server --allow-local-files
```

Open [http://localhost:8080/aws-neo4j-grounded-enterprise-ai.md](http://localhost:8080/aws-neo4j-grounded-enterprise-ai.md) in your browser. Marp reloads the slide deck when you save `aws-neo4j-grounded-enterprise-ai.md`.

Press <kbd>P</kbd> in the browser to open presenter view.

## Build a Standalone HTML File

Run this command from the repository root:

```bash
npx --yes @marp-team/marp-cli@4.4.0 slides/aws-neo4j-grounded-enterprise-ai.md --html --allow-local-files --output slides/aws-neo4j-grounded-enterprise-ai.html
```

The deck uses local SVG and PNG files in this folder. Keep `--allow-local-files` in preview and build commands so Marp can load them.
