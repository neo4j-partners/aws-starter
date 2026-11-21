"""Each delay cause keeps its weight and minute range with it."""

from __future__ import annotations

import random

from generator.config import GeneratorConfig
from generator.fleet import generate_fleet
from generator.operations import generate_operations
from generator.specs import DELAY_CAUSE_SPECS, DELAY_CAUSES, EVENT_SEVERITIES


def test_vocabulary_constants_are_immutable() -> None:
    assert isinstance(DELAY_CAUSE_SPECS, tuple)
    assert isinstance(DELAY_CAUSES, tuple)
    assert isinstance(EVENT_SEVERITIES, tuple)


def test_delay_causes_are_the_spec_causes_in_order() -> None:
    assert tuple(spec.cause for spec in DELAY_CAUSE_SPECS) == DELAY_CAUSES
    assert len(set(DELAY_CAUSES)) == len(DELAY_CAUSES)


def test_generated_delays_fall_in_their_cause_minute_range() -> None:
    config = GeneratorConfig(n_aircraft=10, n_airports=40, n_days=30, seed=3)
    _, _, delays, *_ = generate_operations(
        generate_fleet(config), config, random.Random(config.seed)
    )
    ranges = {spec.cause: (spec.min_minutes, spec.max_minutes) for spec in DELAY_CAUSE_SPECS}

    assert {delay["cause"] for delay in delays} == set(DELAY_CAUSES)
    for delay in delays:
        low, high = ranges[delay["cause"]]
        assert low <= delay["minutes"] <= high
