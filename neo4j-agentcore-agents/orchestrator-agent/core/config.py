"""Static configuration for the orchestrator agent.

Read from the environment at import time so a local ``.env`` (loaded by the
server before this module is imported) or an ``agentcore deploy --env`` value
can override the defaults without code changes.
"""

import os

MODEL_ID = os.getenv("MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
