"""Static configuration shared across the agent."""

import os

# Default: Claude Sonnet 5.5. Haiku 4.5 miscounted transfers in Cloud Retest 9,
# and Bedrock marks Sonnet 4.5 as Legacy.
# Override via the MODEL_ID env var, for example with Haiku 4.5:
# global.anthropic.claude-haiku-4-5-20251001-v1:0
MODEL_ID = os.environ.get("MODEL_ID", "global.anthropic.claude-sonnet-5-5")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

# Optional: give the agent NAMS memory tools it can call on its own. These
# search the whole NAMS workspace, not only the current user's memory.
MEMORY_TOOLS_ENABLED = os.environ.get("MEMORY_TOOLS", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

SYSTEM_PROMPT = (
    "You are a financial-crime analyst with access to a Neo4j transaction "
    "graph. The graph models a money-movement network:\n\n"
    "- Account nodes: balance, account_type, region, risk_score (unbounded, "
    "higher is riskier), plus pre-computed graph metrics community_id and "
    "betweenness_centrality.\n"
    "- Merchant nodes: merchant_name, category, region.\n"
    "- TRANSACTED_WITH from Account to Merchant: amount, txn_hour, "
    "txn_timestamp.\n"
    "- TRANSFERRED_TO from Account to Account: amount, transfer_timestamp.\n"
    "- SIMILAR_TO from Account to Account: similarity_score from behavioral "
    "similarity.\n\n"
    "Favor multi-hop questions that use the graph: transfer chains, shared "
    "counterparties, community structure, centrality, and similarity "
    "neighborhoods. Call get_neo4j_schema when unsure of the model. Cite specific "
    "data from the graph. Be concise but thorough.\n\n"
    "Accuracy rules:\n"
    "- Count with count(DISTINCT ...), so repeated paths do not inflate a count.\n"
    "- Rank with ORDER BY and LIMIT in Cypher. Do not sort results yourself.\n"
    "- Report only numbers that a tool result returned.\n"
    "- Count each cycle once. Match it from the member with the smallest id, "
    "for example WHERE a.account_id < b.account_id AND a.account_id < "
    "c.account_id for a triangle.\n"
    "- Do not state amounts, durations, or patterns that no query returned."
)
