import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";

const ARCHIVE_DIR = "archive/aws-in-depth";
const ARCHIVE_DECK_PATTERN = /^(\d+)-(.+)-slides\.md$/;

const activeDecks = [
  {
    file: "neocarta-slides.md",
    source: "current/neocarta-slides.md",
    order: "01",
    title: "Neocarta: A Semantic Map for Enterprise Data",
    output: "neocarta-slides.html",
    description:
      "How Neocarta builds and serves a semantic map in Neo4j, plus an architectural comparison with Rosetta SDL.",
    assets: ["current/neocarta.svg"],
  },
  {
    file: "aws-neo4j-grounded-enterprise-ai.md",
    source: "current/aws-neo4j-grounded-enterprise-ai.md",
    order: "02",
    title: "AWS + Neo4j: Connected Context for Grounded Enterprise AI",
    output: "aws-neo4j-grounded-enterprise-ai.html",
    description:
      "How AWS and Neo4j combine governed data, connected context, semantic discovery, and agent memory for grounded enterprise AI.",
    assets: [
      "current/aws-neo4j-layer-map.svg",
      "current/dual-data-architecture-aws.svg",
      "current/exec-knowledge-layer.svg",
      "current/neocarta.svg",
      "current/neo4j-agent-memory-diagram.svg",
    ],
  },
];

const archiveDescriptions = {
  "01-neo4j-for-agentic-ai-slides.md":
    "Neo4j for agentic AI: managed graph database, GraphRAG retrieval, and the path from retrievers to agents.",
  "02-aircraft-data-model-slides.md":
    "Aircraft digital-twin property graph and a dual analytics-and-graph data architecture.",
  "03-graphrag-and-retrievers-slides.md":
    "GraphRAG retrieval patterns, vector search, vector Cypher retrieval, and text-to-Cypher.",
  "04-neo4j-on-aws-slides.md":
    "Neo4j on Amazon Bedrock AgentCore, including the MCP server, Gateway, and runtime architecture.",
};

const archiveTitles = {
  "01-neo4j-for-agentic-ai-slides.md": "Neo4j for Agentic AI",
  "02-aircraft-data-model-slides.md": "The Aircraft Data Model",
  "03-graphrag-and-retrievers-slides.md": "GraphRAG and Retrievers",
  "04-neo4j-on-aws-slides.md": "Neo4j on AWS Bedrock AgentCore",
};

const archiveDecks = readdirSync(ARCHIVE_DIR)
  .filter((name) => ARCHIVE_DECK_PATTERN.test(name))
  .sort()
  .map((file) => {
    const [, order, slug] = file.match(ARCHIVE_DECK_PATTERN);
    const fallbackTitle = slug
      .split("-")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
    const title = archiveTitles[file] ?? fallbackTitle;

    return {
      file,
      source: join(ARCHIVE_DIR, file),
      order,
      title,
      output: join("archive", file.replace(/\.md$/, ".html")),
      description: archiveDescriptions[file] ?? `${title} slide deck.`,
    };
  });

const decks = [...activeDecks, ...archiveDecks];
const requested = process.argv[2] ?? "all";
const selected =
  requested === "all"
    ? decks
    : decks.filter(
        (deck) => deck.file === requested || deck.output === requested,
      );

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
  const output = join("build", deck.output);
  mkdirSync(dirname(output), { recursive: true });
  execFileSync(
    "marp",
    [
      deck.source,
      "-o",
      output,
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

for (const deck of selected) {
  for (const asset of deck.assets ?? []) {
    copyFileSync(asset, join("build", asset.split("/").at(-1)));
  }
}

const archiveImagesDir = join(ARCHIVE_DIR, "images");
if (
  archiveDecks.some((deck) => selected.includes(deck)) &&
  existsSync(archiveImagesDir)
) {
  cpSync(archiveImagesDir, join("build", "archive", "images"), {
    recursive: true,
  });
}

writeFileSync(join("build", ".nojekyll"), "");

if (requested === "all") {
  copyFileSync(
    join("build", activeDecks[0].output),
    join("build", "slides.html"),
  );
  writeFileSync(join("build", "index.html"), renderIndex());
}

function renderIndex() {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>AWS + Neo4j Presentations</title>
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

      * { box-sizing: border-box; }

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

      h2 {
        font-size: 26px;
        margin: 52px 0 8px;
      }

      p {
        color: var(--muted);
        font-size: 19px;
        line-height: 1.5;
        margin: 0;
        max-width: 760px;
      }

      .section-intro { font-size: 16px; }

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
        margin: 24px 0 0;
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
        text-transform: uppercase;
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
        margin: 40px 0 0;
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
      <div class="eyebrow">AWS + Neo4j</div>
      <h1>Presentations</h1>
      <p>Current presentations on semantic data discovery and grounded enterprise AI with AWS and Neo4j.</p>

      <section aria-labelledby="current-presentations">
        <h2 id="current-presentations">Current presentations</h2>
        <div class="decks">
${renderCards(activeDecks, "Deck")}
        </div>
      </section>

      <section aria-labelledby="archived-presentations">
        <h2 id="archived-presentations">Archive</h2>
        <p class="section-intro">Earlier AWS + Neo4j in-depth presentation decks.</p>
        <div class="decks">
${renderCards(archiveDecks, "Archive")}
        </div>
      </section>

      <div class="actions">
        <a class="button" href="https://github.com/neo4j-partners/aws-starter">View project on GitHub</a>
      </div>
    </main>
  </body>
</html>
`;
}

function renderCards(sectionDecks, label) {
  return sectionDecks
    .map(
      (deck) => `          <a class="deck-card" href="./${deck.output}">
            <span class="deck-order">${label} ${deck.order}</span>
            <strong>${escapeHtml(deck.title)}</strong>
            <span class="deck-desc">${escapeHtml(deck.description)}</span>
          </a>`,
    )
    .join("\n");
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
