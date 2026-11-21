"""Each delay cause keeps its weight and minute range with it."""

from __future__ import annotations

import dataclasses
import random

import pytest

from generator import specs
from generator.config import GeneratorConfig
from generator.fleet import generate_fleet
from generator.operations import generate_operations
from generator.specs import DELAY_CAUSE_SPECS, DELAY_CAUSES, EVENT_SEVERITIES, DelayCauseSpec


def test_vocabulary_constants_are_immutable() -> None:
    assert isinstance(DELAY_CAUSE_SPECS, tuple)
    assert isinstance(DELAY_CAUSES, tuple)
    assert isinstance(EVENT_SEVERITIES, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        DELAY_CAUSE_SPECS[0].weight = 0.5  # type: ignore[misc]


@pytest.mark.parametrize(
    ("weight", "min_minutes", "max_minutes", "message"),
    [
        pytest.param(-0.1, 10, 60, "weight -0.1 is negative", id="negative-weight"),
        pytest.param(float("nan"), 10, 60, "weight nan is not finite", id="nan-weight"),
        pytest.param(float("inf"), 10, 60, "weight inf is not finite", id="inf-weight"),
        pytest.param(0.2, -5, 60, "minutes -5 to 60 include a negative", id="negative-minutes"),
        pytest.param(0.2, 60, 30, "min_minutes 60 is above max_minutes 30", id="min-above-max"),
    ],
)
def test_an_invalid_spec_raises_value_error(
    weight: float, min_minutes: int, max_minutes: int, message: str
) -> None:
    with pytest.raises(ValueError, match=f"^delay cause 'Test': {message}$"):
        DelayCauseSpec("Test", weight, min_minutes, max_minutes)


def test_a_zero_weight_and_a_single_minute_value_are_valid() -> None:
    spec = DelayCauseSpec("Test", 0.0, 0, 0)
    assert (spec.weight, spec.min_minutes, spec.max_minutes) == (0.0, 0, 0)


@pytest.mark.parametrize(
    "weights", [pytest.param((), id="empty"), pytest.param((0.0, 0.0), id="all-zero")]
)
def test_delay_cause_weights_must_sum_above_zero(weights: tuple[float, ...]) -> None:
    causes = tuple(DelayCauseSpec(f"C{n}", w, 0, 0) for n, w in enumerate(weights))
    with pytest.raises(ValueError, match="^delay cause weights sum to 0"):
        specs._positive_weight_sum(causes)


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
