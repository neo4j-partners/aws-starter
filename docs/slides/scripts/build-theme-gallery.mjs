import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { readdirSync } from "node:fs";
import { join } from "node:path";

const SLIDE_DIR = "aws-in-depth";
const DECK_PATTERN = /^(\d+)-(.+)-slides\.md$/;

const descriptions = {
  "01-aircraft-data-model-slides.md":
    "Aircraft digital-twin property graph and the data model.",
  "02-dual-data-architecture-slides.md":
    "Dual data architecture pairing operational and graph stores.",
  "03-graphrag-and-genai-slides.md":
    "GraphRAG patterns and generative AI grounding.",
  "04-graph-enriched-search-slides.md":
    "Graph-enriched search beyond keyword retrieval.",
  "05-neo4j-aura-and-agents-slides.md":
    "Neo4j Aura and agent integration patterns.",
  "06-neo4j-mcp-server-slides.md":
    "Neo4j MCP server on Bedrock AgentCore.",
  "07-aws-agentcore-architecture-slides.md":
    "AWS AgentCore runtime and gateway architecture.",
};

const decks = readdirSync(SLIDE_DIR)
  .filter((name) => DECK_PATTERN.test(name))
  .sort()
  .map((file) => {
    const [, order, slug] = file.match(DECK_PATTERN);
    const title = slug
      .split("-")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");

    return {
      file,
      order,
      title,
      output: file.replace(/\.md$/, ".html"),
      description: descriptions[file] ?? `${title} slide deck.`,
    };
  });

const requested = process.argv[2] ?? "all";
const selected =
  requested === "all"
    ? decks
    : decks.filter((deck) => deck.file === requested || deck.output === requested);

if (selected.length === 0) {
  console.error(`Unknown deck: ${requested}`);
  console.error(
    `Available decks: ${decks.map((deck) => deck.file).join(", ")}, all`,
  );
  process.exit(1);
}

rmSync("build", { force: true, recursive: true });
mkdirSync("build", { recursive: true });

for (const deck of selected) {
  execFileSync(
    "marp",
    [
      join(SLIDE_DIR, deck.file),
      "-o",
      join("build", deck.output),
      "--html",
      "--allow-local-files",
      "--theme-set",
      "themes/finance.css",
      "--theme-set",
      "themes/graph-lakehouse.css",
    ],
    { stdio: "inherit" },
  );
}

const imagesDir = join(SLIDE_DIR, "images");
if (existsSync(imagesDir)) {
  cpSync(imagesDir, join("build", "images"), { recursive: true });
}

writeFileSync(join("build", ".nojekyll"), "");

if (requested === "all") {
  copyFileSync(
    join("build", decks[0].output),
    join("build", "slides.html"),
  );
  writeFileSync(join("build", "index.html"), renderIndex());
}

function renderIndex() {
  const cards = decks
    .map(
      (deck) => `        <a class="deck-card" href="./${deck.output}">
          <span class="deck-order">${deck.order}</span>
          <strong>${escapeHtml(deck.title)}</strong>
          <span class="deck-desc">${escapeHtml(deck.description)}</span>
        </a>`,
    )
    .join("\n");

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>AWS + Neo4j In Depth</title>
    <style>
      :root {
        color-scheme: light;
        --ink: #172033;
        --muted: #5b6678;
        --line: #d9e0ea;
        --accent: #0f766e;
        --accent-2: #2563eb;
        --surface: #ffffff;
        --bg: #f8fafc;
      }

      * {
        box-sizing: border-box;
      }

      body {
        background:
          linear-gradient(90deg, var(--accent) 0 10px, transparent 10px),
          var(--bg);
        color: var(--ink);
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0;
      }

      main {
        margin: 0 auto;
        max-width: 1080px;
        padding: 72px 24px 64px 42px;
      }

      h1 {
        font-size: clamp(36px, 6vw, 64px);
        line-height: 1;
        margin: 0 0 16px;
      }

      p {
        color: var(--muted);
        font-size: 19px;
        line-height: 1.5;
        margin: 0;
        max-width: 760px;
      }

      .eyebrow {
        color: var(--accent);
        font-size: 14px;
        font-weight: 800;
        letter-spacing: 0.08em;
        margin-bottom: 14px;
        text-transform: uppercase;
      }

      .decks {
        display: grid;
        gap: 16px;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        margin: 40px 0 0;
      }

      .deck-card {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 8px;
        color: inherit;
        display: block;
        padding: 20px;
        text-decoration: none;
        transition: border-color 120ms ease, transform 120ms ease;
      }

      .deck-card:hover {
        border-color: var(--accent-2);
        transform: translateY(-2px);
      }

      .deck-order {
        color: var(--accent);
        font-size: 13px;
        font-weight: 800;
        letter-spacing: 0.1em;
      }

      .deck-card strong {
        color: var(--ink);
        display: block;
        font-size: 19px;
        margin: 6px 0 8px;
      }

      .deck-desc {
        color: var(--muted);
        display: block;
        font-size: 15px;
        line-height: 1.45;
      }

      .actions {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin: 32px 0 0;
      }

      .button {
        align-items: center;
        background: var(--ink);
        border-radius: 6px;
        color: white;
        display: inline-flex;
        font-weight: 700;
        min-height: 44px;
        padding: 0 16px;
        text-decoration: none;
      }
    </style>
  </head>
  <body>
    <main>
      <div class="eyebrow">AWS + Neo4j In Depth</div>
      <h1>Neo4j MCP server on Amazon Bedrock AgentCore</h1>
      <p>A seven-part presentation covering the aircraft graph data model, dual data architecture, GraphRAG, graph-enriched search, Neo4j Aura and agents, the Neo4j MCP server, and the AWS AgentCore architecture.</p>
      <section class="decks" aria-label="Slide decks">
${cards}
      </section>
      <div class="actions">
        <a class="button" href="https://github.com/neo4j-partners/aws-starter">View project on GitHub</a>
      </div>
    </main>
  </body>
</html>
`;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
