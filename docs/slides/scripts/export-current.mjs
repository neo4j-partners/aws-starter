import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, rmSync } from "node:fs";
import { basename, join } from "node:path";

const format = process.argv[2];
const supportedFormats = new Set(["html", "pdf", "pptx"]);

if (!supportedFormats.has(format)) {
  console.error("Usage: node scripts/export-current.mjs <html|pdf|pptx>");
  process.exit(1);
}

const decks = [
  "current/neocarta-slides.md",
  "current/aws-neo4j-grounded-enterprise-ai.md",
];

const assets = [
  "current/aws-neo4j-layer-map.svg",
  "current/dual-data-architecture-aws.svg",
  "current/exec-knowledge-layer.svg",
  "current/fraud-ring-property-graph-detailed.svg",
  "current/neocarta.svg",
  "current/neo4j-agent-memory-diagram.svg",
];

rmSync("dist", { force: true, recursive: true });
mkdirSync("dist", { recursive: true });

for (const source of decks) {
  const output = join("dist", basename(source, ".md") + `.${format}`);
  execFileSync(
    "marp",
    [source, "-o", output, `--${format}`, "--allow-local-files"],
    { stdio: "inherit" },
  );
}

if (format === "html") {
  for (const asset of assets) {
    copyFileSync(asset, join("dist", basename(asset)));
  }
}
