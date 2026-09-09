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
  "../../slides/neocarta-slides.md",
  "../../slides/aws-neo4j-grounded-enterprise-ai.md",
];

const assets = [
  "../../slides/aws-neo4j-layer-map.svg",
  "../../slides/dual-data-architecture-aws.svg",
  "../../slides/exec-knowledge-layer.svg",
  "../../slides/neocarta.svg",
  "../../slides/neo4j-agent-memory-diagram.svg",
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
