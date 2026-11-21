"""Removal records need enough airframe hours before the data window."""

from __future__ import annotations

import random
from datetime import datetime

import pytest

from generator.config import GeneratorConfig
from generator.fleet import generate_fleet
from generator.removals import generate_removals


def test_start_date_too_soon_after_entry_into_service_is_rejected() -> None:
    # The latest A220-300 enters service on 2023-05-31. A window that opens
    # a month later leaves fewer airframe hours than the install minimum.
    config = GeneratorConfig(n_aircraft=6, n_days=5, start_date=datetime(2023, 7, 1))
    fleet = generate_fleet(GeneratorConfig(n_aircraft=6))

    with pytest.raises(ValueError, match="start_date"):
        generate_removals(fleet, [], config, random.Random(0))


def test_default_start_date_is_accepted() -> None:
    config = GeneratorConfig(n_aircraft=6, n_days=5)

    removals, _, _ = generate_removals(generate_fleet(config), [], config, random.Random(0))

    assert removals
