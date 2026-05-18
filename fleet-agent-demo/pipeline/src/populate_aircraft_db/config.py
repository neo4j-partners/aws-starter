"""Configuration: load Neo4j credentials from .env and resolve data directory."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import DirectoryPath, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolved once at import time — stable regardless of cwd.
_PKG_DIR = Path(__file__).resolve().parent
_LAB_SETUP_DIR = _PKG_DIR.parent.parent.parent
# Shared fleet-agent-demo-root .env, read by both pipeline/ and agent/.
_ENV_FILE = _LAB_SETUP_DIR / ".env"
_DATA_DIR = _LAB_SETUP_DIR / "aircraft_digital_twin_data_v2"
_DOCUMENT_DIR = _LAB_SETUP_DIR / "aircraft_digital_twin_data"


class Settings(BaseSettings):
    """Neo4j connection settings loaded from .env."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        # The fleet-agent-demo-root .env is shared with setup.sh and the
        # agent; setup.sh owns bash-only knobs
        # (LOAD_FULL_DATASET, GEN_*, DATA_DIR/DOCUMENT_DIR). Ignore env keys
        # this model doesn't declare instead of rejecting them.
        extra="ignore",
    )

    neo4j_uri: str
    neo4j_username: str = "neo4j"
    neo4j_password: SecretStr

    data_dir: DirectoryPath = _DATA_DIR  # type: ignore[assignment]
    document_dir: DirectoryPath = _DOCUMENT_DIR  # type: ignore[assignment]

    # OpenAI embeddings — required for the `setup` command.
    openai_api_key: SecretStr | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536

    # OpenAI chat model — used by the `setup` command for entity extraction.
    openai_extraction_model: str = "gpt-5-mini"
    openai_extraction_max_completion_tokens: int = 8000

    # LLM provider selection — "bedrock" (default), "openai", or "anthropic".
    # Controls BOTH entity extraction and chunk embeddings.
    llm_provider: Literal["bedrock", "openai", "anthropic"] = "bedrock"

    # Anthropic — only required when llm_provider is "anthropic".
    anthropic_api_key: SecretStr | None = None
    anthropic_extraction_model: str = "claude-sonnet-4-6"
    anthropic_extraction_max_tokens: int = 8000

    # Amazon Bedrock — used when llm_provider is "bedrock". Credentials come
    # from the standard AWS chain (env vars / ~/.aws), not from this file.
    # Region is the shared AWS_REGION (also read by the agent); defaults to
    # us-east-1, this repo's AgentCore region. Override via AWS_REGION.
    aws_region: str = "us-east-1"
    # Claude Sonnet 4.6 via the cross-region "global" inference profile.
    bedrock_llm_model: str = "global.anthropic.claude-sonnet-4-6"
    bedrock_llm_max_tokens: int = 8000
    bedrock_embedding_model: str = "amazon.titan-embed-text-v2:0"
    bedrock_embedding_dimensions: int = 1024

    # Chunking settings for the `setup` command.
    chunk_size: int = 800
    chunk_overlap: int = 100

    # Limit chunks processed per document during setup (0 = no limit).
    enrich_sample_size: int = 0

    # Number of rows to show per section in the `samples` command.
    sample_size: int = 10

    @model_validator(mode="after")
    def _check_uri_scheme(self) -> Settings:
        if not self.neo4j_uri.startswith(("neo4j://", "neo4j+s://", "neo4j+ssc://", "bolt://", "bolt+s://", "bolt+ssc://")):
            raise ValueError(
                f"NEO4J_URI must start with a valid scheme (neo4j+s://, bolt+s://, etc.), got: {self.neo4j_uri}"
            )
        return self
