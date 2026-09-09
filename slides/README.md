# Financial Fraud Knowledge Layer Slides

This folder contains the financial fraud investigation knowledge-layer deck in [Marp](https://marp.app/) format. The main deck is `semantic-slides.md`.

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

Open [http://localhost:8080/semantic-slides.md](http://localhost:8080/semantic-slides.md) in your browser. Marp reloads the slide deck when you save `semantic-slides.md`.

Press <kbd>P</kbd> in the browser to open presenter view.

## Build a Standalone HTML File

Run this command from the repository root:

```bash
npx --yes @marp-team/marp-cli@4.4.0 slides/semantic-slides.md --html --allow-local-files --output slides/semantic-slides.html
```

The deck uses local SVG and PNG files in this folder. Keep `--allow-local-files` in preview and build commands so Marp can load them.
