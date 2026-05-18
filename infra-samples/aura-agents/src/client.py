"""Neo4j Aura Agents API Client.

This client provides a Python interface to call external Neo4j Aura Agents
that have been deployed with external API access enabled.

Usage:
    from src import AuraAgentClient

    client = AuraAgentClient(
        client_id="your-client-id",
        client_secret="your-client-secret",
        endpoint_url="https://api.neo4j.io/v2beta1/projects/.../agents/.../invoke"
    )

    response = client.invoke("What contracts mention Motorola?")
    print(response.text)
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from .models import AgentResponse, CachedToken, TokenResponse

logger = logging.getLogger(__name__)


class AuraAgentError(Exception):
    """Base exception for Aura Agent errors."""

    pass


class AuthenticationError(AuraAgentError):
    """Raised when authentication fails."""

    pass


class InvocationError(AuraAgentError):
    """Raised when agent invocation fails."""

    pass


class AuraAgentClient:
    """Client for invoking Neo4j Aura Agents via REST API.

    This client handles:
    - OAuth2 authentication with client credentials
    - Automatic token caching and refresh
    - Both synchronous and asynchronous invocation

    Attributes:
        client_id: Neo4j Aura API client ID
        client_secret: Neo4j Aura API client secret
        endpoint_url: Full URL to the agent invoke endpoint
        token_url: OAuth2 token endpoint (default: https://api.neo4j.io/oauth/token)
        timeout: Request timeout in seconds (default: 60)
    """

    DEFAULT_TOKEN_URL = "https://api.neo4j.io/oauth/token"
    DEFAULT_TIMEOUT = 60

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        endpoint_url: str,
        token_url: str | None = None,
        timeout: int | None = None,
    ):
        """Initialize the Aura Agent client.

        Args:
            client_id: Neo4j Aura API client ID from your user profile
            client_secret: Neo4j Aura API client secret from your user profile
            endpoint_url: Full URL to the agent invoke endpoint
                Format: https://api.neo4j.io/v2beta1/projects/{project_id}/agents/{agent_id}/invoke
            token_url: Optional custom OAuth2 token URL
            timeout: Optional request timeout in seconds
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.endpoint_url = endpoint_url
        self.token_url = token_url or self.DEFAULT_TOKEN_URL
        self.timeout = timeout or self.DEFAULT_TIMEOUT

        self._cached_token: CachedToken | None = None
        self._validate_endpoint_url()

    def _validate_endpoint_url(self) -> None:
        """Validate the endpoint URL format."""
        parsed = urlparse(self.endpoint_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid endpoint URL: {self.endpoint_url}")
        if not self.endpoint_url.endswith("/invoke"):
            logger.warning(
                "Endpoint URL should end with '/invoke'. "
                f"Got: {self.endpoint_url}"
            )

    def _get_auth_header(self) -> tuple[str, str]:
        """Get HTTP Basic auth credentials for token request."""
        return (self.client_id, self.client_secret)

    def _parse_token_response(self, data: dict[str, Any]) -> CachedToken:
        """Parse OAuth2 token response and create cached token."""
        token = TokenResponse(**data)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token.expires_in)
        return CachedToken(access_token=token.access_token, expires_at=expires_at)

    def _get_token_sync(self, client: httpx.Client) -> str:
        """Get a valid access token, refreshing if necessary (sync)."""
        if self._cached_token and not self._cached_token.is_expired():
            return self._cached_token.access_token

        logger.debug("Requesting new OAuth2 token")
        response = client.post(
            self.token_url,
            auth=self._get_auth_header(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
        )

        if response.status_code != 200:
            raise AuthenticationError(
                f"Failed to obtain access token: {response.status_code} - {response.text}"
            )

        self._cached_token = self._parse_token_response(response.json())
        logger.debug("Successfully obtained new token")
        return self._cached_token.access_token

    async def _get_token_async(self, client: httpx.AsyncClient) -> str:
        """Get a valid access token, refreshing if necessary (async)."""
        if self._cached_token and not self._cached_token.is_expired():
            return self._cached_token.access_token

        logger.debug("Requesting new OAuth2 token (async)")
        response = await client.post(
            self.token_url,
            auth=self._get_auth_header(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
        )

        if response.status_code != 200:
            raise AuthenticationError(
                f"Failed to obtain access token: {response.status_code} - {response.text}"
            )

        self._cached_token = self._parse_token_response(response.json())
        logger.debug("Successfully obtained new token (async)")
        return self._cached_token.access_token

    def invoke(self, question: str) -> AgentResponse:
        """Invoke the Aura Agent with a question (synchronous).

        Args:
            question: Natural language question to ask the agent

        Returns:
            AgentResponse containing the agent's answer and metadata

        Raises:
            AuthenticationError: If OAuth2 authentication fails
            InvocationError: If the agent invocation fails
        """
        with httpx.Client(timeout=self.timeout) as client:
            token = self._get_token_sync(client)

            logger.debug(f"Invoking agent with question: {question[:50]}...")
            response = client.post(
                self.endpoint_url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                json={"input": question},
            )

            if response.status_code != 200:
                # Try token refresh on 401
                if response.status_code == 401:
                    logger.debug("Token expired, refreshing...")
                    self._cached_token = None
                    token = self._get_token_sync(client)
                    response = client.post(
                        self.endpoint_url,
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                            "Authorization": f"Bearer {token}",
                        },
                        json={"input": question},
                    )

                if response.status_code != 200:
                    raise InvocationError(
                        f"Agent invocation failed: {response.status_code} - {response.text}"
                    )

            return AgentResponse.from_api_response(response.json())

    async def invoke_async(self, question: str) -> AgentResponse:
        """Invoke the Aura Agent with a question (asynchronous).

        Args:
            question: Natural language question to ask the agent

        Returns:
            AgentResponse containing the agent's answer and metadata

        Raises:
            AuthenticationError: If OAuth2 authentication fails
            InvocationError: If the agent invocation fails
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            token = await self._get_token_async(client)

            logger.debug(f"Invoking agent (async) with question: {question[:50]}...")
            response = await client.post(
                self.endpoint_url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                json={"input": question},
            )

            if response.status_code != 200:
                # Try token refresh on 401
                if response.status_code == 401:
                    logger.debug("Token expired, refreshing (async)...")
                    self._cached_token = None
                    token = await self._get_token_async(client)
                    response = await client.post(
                        self.endpoint_url,
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                            "Authorization": f"Bearer {token}",
                        },
                        json={"input": question},
                    )

                if response.status_code != 200:
                    raise InvocationError(
                        f"Agent invocation failed: {response.status_code} - {response.text}"
                    )

            return AgentResponse.from_api_response(response.json())

    def clear_token_cache(self) -> None:
        """Clear the cached OAuth2 token, forcing a refresh on next request."""
        self._cached_token = None
        logger.debug("Token cache cleared")

    @classmethod
    def from_env(cls) -> "AuraAgentClient":
        """Create a client from environment variables.

        Required environment variables:
            NEO4J_CLIENT_ID: Aura API client ID
            NEO4J_CLIENT_SECRET: Aura API client secret
            NEO4J_AGENT_ENDPOINT: Agent invoke endpoint URL

        Optional environment variables:
            NEO4J_TOKEN_URL: Custom OAuth2 token URL
            NEO4J_TIMEOUT: Request timeout in seconds

        Returns:
            Configured AuraAgentClient instance

        Raises:
            ValueError: If required environment variables are missing
        """
        import os

        from dotenv import load_dotenv

        load_dotenv()

        client_id = os.getenv("NEO4J_CLIENT_ID")
        client_secret = os.getenv("NEO4J_CLIENT_SECRET")
        endpoint_url = os.getenv("NEO4J_AGENT_ENDPOINT")

        if not client_id:
            raise ValueError("NEO4J_CLIENT_ID environment variable is required")
        if not client_secret:
            raise ValueError("NEO4J_CLIENT_SECRET environment variable is required")
        if not endpoint_url:
            raise ValueError("NEO4J_AGENT_ENDPOINT environment variable is required")

        token_url = os.getenv("NEO4J_TOKEN_URL")
        timeout = os.getenv("NEO4J_TIMEOUT")

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            endpoint_url=endpoint_url,
            token_url=token_url,
            timeout=int(timeout) if timeout else None,
        )

    def __repr__(self) -> str:
        """Return string representation of client."""
        return (
            f"AuraAgentClient(endpoint_url='{self.endpoint_url}', "
            f"token_cached={self._cached_token is not None})"
        )
