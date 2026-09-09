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

## AWS Technical Review

Last reviewed on 2026-09-09 against current AWS documentation for:

- [Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html) and [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
- [Amazon S3 Tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables.html), [AWS Glue Data Catalog integration](https://docs.aws.amazon.com/glue/latest/dg/enable-s3-tables-catalog-integration.html), and [Amazon Athena access](https://docs.aws.amazon.com/athena/latest/ug/gdc-register-s3-table-bucket-cat.html)
- [Amazon SageMaker Lakehouse](https://docs.aws.amazon.com/sagemaker-unified-studio/latest/userguide/lakehouse-how.html), [Amazon SageMaker Catalog](https://docs.aws.amazon.com/sagemaker-unified-studio/latest/userguide/working-with-business-catalog.html), and [Amazon SageMaker AI](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html) naming
- [Amazon Quick Sight](https://docs.aws.amazon.com/quick/latest/userguide/what-is.html) naming and dashboard capabilities

Capabilities labeled **Planned** describe intended Neo4j or project integrations, not currently supported AWS-native features.
