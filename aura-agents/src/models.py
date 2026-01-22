"""Pydantic models for Neo4j Aura Agents API responses."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    """OAuth2 token response from Neo4j Aura API."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class AgentUsage(BaseModel):
    """Token usage metrics from agent invocation."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ToolUse(BaseModel):
    """Details about a tool used by the agent."""

    tool_use_id: str | None = None
    type: str | None = None
    output: Any | None = None


class AgentResponse(BaseModel):
    """Response from invoking an Aura Agent."""

    text: str | None = Field(default=None, description="Formatted response text")
    thinking: str | list[str] | None = Field(
        default=None, description="Agent reasoning steps"
    )
    tool_uses: list[ToolUse] | None = Field(
        default=None, description="Tools used during invocation"
    )
    status: str | None = Field(default=None, description="Request status (SUCCESS)")
    usage: AgentUsage | None = Field(default=None, description="Token usage metrics")
    raw_response: dict[str, Any] | None = Field(
        default=None, description="Raw JSON response for debugging"
    )

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "AgentResponse":
        """Parse API response into AgentResponse model.

        The Aura Agent API response structure can vary, so this handles
        different formats gracefully.
        """
        tool_uses = None
        if "tool_uses" in data:
            tool_uses = [ToolUse(**tu) for tu in data.get("tool_uses", [])]
        elif "tool_use_id" in data:
            # Single tool use at top level
            tool_uses = [
                ToolUse(
                    tool_use_id=data.get("tool_use_id"),
                    type=data.get("type"),
                    output=data.get("output"),
                )
            ]

        usage = None
        if "usage" in data:
            usage = AgentUsage(**data["usage"])

        return cls(
            text=data.get("text"),
            thinking=data.get("thinking"),
            tool_uses=tool_uses,
            status=data.get("status"),
            usage=usage,
            raw_response=data,
        )


class CachedToken(BaseModel):
    """Cached OAuth2 token with expiration tracking."""

    access_token: str
    expires_at: datetime

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """Check if token is expired or about to expire."""
        from datetime import timezone

        return datetime.now(timezone.utc) >= self.expires_at.replace(
            tzinfo=timezone.utc
        ) - __import__("datetime").timedelta(seconds=buffer_seconds)
