# Workshop Slides

Presentation-ready slides formatted for [Marp](https://marp.app/).

## Quick Start

Requires Node.js 22 LTS (`brew install node@22`) and a one-time `npm install` in this directory.

```bash
cd slides
/opt/homebrew/opt/node@22/bin/node ./node_modules/.bin/marp overview-databricks-neo4j --server
```

Opens at http://localhost:8080/. Replace `overview-databricks-neo4j` with any slide deck directory name.

## Export All Presentations

```bash
cd slides
for dir in overview-*/ databricks-*/; do
  /opt/homebrew/opt/node@22/bin/node ./node_modules/.bin/marp "$dir" --pdf --allow-local-files
done
```

## Troubleshooting

**`require is not defined in ES module scope` error?**
- Marp CLI is incompatible with Node.js 25+. Install Node 22 LTS: `brew install node@22`

**Images not showing?**
- Use `--allow-local-files` flag with Marp CLI

---

## Slide Format

All slides use Marp markdown format with pagination, syntax-highlighted code blocks, tables, and two-column layouts. See any slide file for the frontmatter template.

## Additional Resources

- [Marp Documentation](https://marpit.marp.app/)
- [Marp CLI Usage](https://github.com/marp-team/marp-cli)
- [Marp Themes](https://github.com/marp-team/marp-core/tree/main/themes)
- [Creating Custom Themes](https://marpit.marp.app/theme-css)
