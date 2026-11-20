"""Shared test helpers. Tests run offline: no Bedrock, Gateway, or Neo4j."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any


def collect(stream: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drain an async generator into a list."""

    async def _drain() -> list[dict[str, Any]]:
        return [event async for event in stream]

    return asyncio.run(_drain())
