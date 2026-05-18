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

    request_tokens: int | None = None
    response_tokens: int | None = None
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

        The Aura Agent API response structure uses a content array:
        {
            "content": [
                {"type": "thinking", "thinking": "..."},
                {"type": "text", "text": "..."},
                {"type": "tool_use", ...}
            ],
            "status": "SUCCESS",
            "usage": {...}
        }
        """
        text = None
        thinking = None
        tool_uses = []

        # Parse the content array
        content = data.get("content", [])
        for item in content:
            item_type = item.get("type")
            if item_type == "text":
                text = item.get("text")
            elif item_type == "thinking":
                thinking = item.get("thinking")
            elif item_type == "tool_use":
                tool_uses.append(
                    ToolUse(
                        tool_use_id=item.get("id"),
                        type=item.get("name"),
                        output=item.get("input"),
                    )
                )
            elif item_type == "tool_result":
                tool_uses.append(
                    ToolUse(
                        tool_use_id=item.get("tool_use_id"),
                        type="tool_result",
                        output=item.get("content"),
                    )
                )

        # Fallback for legacy response format
        if not text and "text" in data:
            text = data.get("text")
        if not thinking and "thinking" in data:
            thinking = data.get("thinking")

        usage = None
        if "usage" in data:
            usage = AgentUsage(**data["usage"])

        return cls(
            text=text,
            thinking=thinking,
            tool_uses=tool_uses if tool_uses else None,
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
