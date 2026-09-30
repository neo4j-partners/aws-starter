import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { basename, dirname, join } from "node:path";

const format = process.argv[2];
const supportedFormats = new Set(["html", "pdf", "pptx"]);

if (!supportedFormats.has(format)) {
  console.error("Usage: node scripts/export-current.mjs <html|pdf|pptx>");
  process.exit(1);
}

const decks = [
  "current/aws-neo4j-finance-overview.md",
  "current/fraud-data-architecture.md",
  "current/neocarta-slides.md",
  "current/neocarta-slides-v2.md",
  "current/neosemantics.md",
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
  for (const source of decks) {
    for (const asset of localImageAssets(source)) {
      const destination = join("dist", asset.href);
      mkdirSync(dirname(destination), { recursive: true });
      copyFileSync(asset.source, destination);
    }
  }
}

function localImageAssets(source) {
  const sourceDirectory = dirname(source);
  const markdown = readFileSync(source, "utf8");
  const assets = new Map();
  const imagePattern = /!\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)/g;

  for (const match of markdown.matchAll(imagePattern)) {
    const href = match[1].replace(/[?#].*$/, "");

    if (!href || /^(?:[a-z][a-z\d+.-]*:|\/\/|\/|#)/i.test(href)) {
      continue;
    }

    const asset = join(sourceDirectory, href);
    if (!existsSync(asset)) {
      throw new Error(`Image referenced by ${source} was not found: ${href}`);
    }
    assets.set(href, { href, source: asset });
  }

  return assets.values();
}
