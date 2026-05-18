"""Static configuration shared by both framework variants."""

import os

# Default: latest Claude Haiku (Haiku 4.5, 2025-10-01). Override via MODEL_ID env.
# Alternative: latest Sonnet on Bedrock (Sonnet 4.5, 2025-09-29) — uncomment to use.
# MODEL_ID = os.environ.get(
#     "MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
# )
MODEL_ID = os.environ.get(
    "MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0"
)
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

SYSTEM_PROMPT = (
    "You are a financial analysis assistant with access to a Neo4j knowledge "
    "graph containing SEC filing data, company information, risk factors, and "
    "institutional ownership.\n\n"
    "Use the available tools to answer questions. Cite specific data from the "
    "graph. Be concise but thorough."
)
