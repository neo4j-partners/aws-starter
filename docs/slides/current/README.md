# Current AWS + Neo4j Slides

This folder holds the current AWS and Neo4j presentations. Each deck is a
[Marp](https://marp.app/) Markdown file.

## Overview

- **Gallery decks:** The published gallery shows `hyperscaler-overview.md`, `aws-neo4j-finance-overview.md`, `fraud-data-architecture.md`, `neocarta-slides-v2.md`, `neosemantics.md`, and `enterprise-knowledge-layer.md`.
- **Other decks:** The folder also holds `neocarta-aws-appendix.md` and `neocarta-slides.md`.
- **`neocarta-slides-v2.md`:** This deck revises the order and titles of `neocarta-slides.md`. It has 14 main slides and five appendix slides.
- **`neocarta-outline.md`:** This file is the Neocarta outline. It is plain Markdown, not a Marp deck.
- **Images:** Each deck loads local SVG and PNG files from `images/<deck-name>/`.
- **Build and publish:** The build and publishing steps are in [`docs/slides/README.md`](../README.md).

## Quick start

Use Node.js 22 LTS. Marp does not support Node.js 25 or later. Run these
commands from the repo root:

```bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"   # only if Node 22 came from Homebrew
cd docs/slides
npm run preview
```

Open <http://localhost:8080/aws-neo4j-finance-overview.md> in your
browser. Marp reloads the deck each time you save the file. Press <kbd>P</kbd>
in the browser to open presenter view.

## Build standalone HTML files

Run this command from `docs/slides/`:

```bash
npm run build:html
```

- **Output:** The command writes HTML files to `docs/slides/dist/`. It builds `aws-neo4j-finance-overview.md`, `fraud-data-architecture.md`, `neocarta-slides.md`, `neocarta-slides-v2.md`, and `neosemantics.md`.
- **Local files:** Keep `--allow-local-files` in the preview and build commands. Marp needs this flag to load the images in `images/<deck-name>/`.

## AWS technical review

The decks were last checked on 2026-09-09 against current AWS documentation
for these services:

- **AgentCore:** The review covered [Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html) and [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html).
- **Tables and query:** The review covered [Amazon S3 Tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables.html), [AWS Glue Data Catalog integration](https://docs.aws.amazon.com/glue/latest/dg/enable-s3-tables-catalog-integration.html), and [Amazon Athena access](https://docs.aws.amazon.com/athena/latest/ug/gdc-register-s3-table-bucket-cat.html).
- **SageMaker:** The review covered the naming of [Amazon SageMaker Lakehouse](https://docs.aws.amazon.com/sagemaker-unified-studio/latest/userguide/lakehouse-how.html), [Amazon SageMaker Catalog](https://docs.aws.amazon.com/sagemaker-unified-studio/latest/userguide/working-with-business-catalog.html), and [Amazon SageMaker AI](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html).
- **Quick Sight:** The review covered [Amazon Quick Sight](https://docs.aws.amazon.com/quick/latest/userguide/what-is.html) naming and dashboard features.

Slides marked **Planned** describe Neo4j or project integrations that are
intended for the future. AWS does not support them as native features today.
