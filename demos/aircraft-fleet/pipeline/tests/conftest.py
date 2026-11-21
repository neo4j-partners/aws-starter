"""Shared generator fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from generator.main import generate


@pytest.fixture(scope="session")
def year_dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """30 aircraft over 365 days: about 4 removals per aircraft from the base rate alone."""
    output = tmp_path_factory.mktemp("year")
    generate(aircraft=30, airports=40, days=365, seed=42, output=output)
    return output
