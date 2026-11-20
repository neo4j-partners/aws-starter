"""Static configuration for the supervisor agent.

Values come from the environment at import time, so a local ``.env`` or a
runtime environment variable set at deploy time can override the defaults
without code changes.
"""

import os

MODEL_ID = os.getenv("MODEL_ID", "global.anthropic.claude-sonnet-5-5")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Explicit output cap for every model call. Streaming is on, so a large cap
# does not risk an HTTP timeout.
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "16000"))

# Sonnet 5.5 runs adaptive thinking by default and cannot turn it off fully.
# ``high`` is the Sonnet 5.5 default, set here explicitly.
MODEL_EFFORT = os.getenv("MODEL_EFFORT", "high")

# Local development port. AgentCore Runtime always uses 8080.
LOCAL_PORT = int(os.getenv("AGENT_PORT", "7071"))
