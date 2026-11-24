"""verify checks that every OperatingLimit has a FROM_CHUNK link to a Chunk."""

from __future__ import annotations

from typing import Any

import pytest

from populate_aircraft_db import loader

FakeResult = tuple[list[dict[str, Any]], None, None]
LABELS = {"OperatingLimit", "Chunk"}


class FakeDriver:
    """Answer the limit chunk query with fixed unlinked counts by aircraft type."""

    def __init__(self, unlinked: dict[str | None, int]) -> None:
        self.unlinked = unlinked
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute_query(self, query: str, **kwargs: object) -> FakeResult:
        self.calls.append((query, kwargs))
        rows = [{"aircraftType": t, "count": n} for t, n in self.unlinked.items()]
        return rows, None, None


def _check(
    driver: FakeDriver,
    *,
    labels: set[str] = LABELS,
    skip_enrichment: bool = False,
) -> loader._VerifyResult:
    result = loader._VerifyResult(strict=True, skip_enrichment=skip_enrichment)
    loader._check_limit_chunks(driver, "db", labels, result)  # type: ignore[arg-type]
    return result


def test_every_limit_linked_passes() -> None:
    driver = FakeDriver({})

    assert _check(driver).failures == []
    [(query, _)] = driver.calls
    assert "NOT (ol)-[:FROM_CHUNK]->(:Chunk)" in query


def test_unlinked_limits_fail_with_their_count_by_type(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _check(FakeDriver({"A220-300": 3, "E190": 1}))

    assert result.failures == ["OperatingLimits without Chunk: 4 (A220-300 3, E190 1)"]
    out = capsys.readouterr().out
    assert "A220-300: 3" in out and "E190: 1" in out


def test_empty_and_missing_types_add_into_one_label() -> None:
    result = _check(FakeDriver({"": 1, None: 2}))

    assert result.failures == ["OperatingLimits without Chunk: 3 ((no aircraftType) 3)"]


def test_skip_enrichment_keeps_unlinked_limits_a_warning() -> None:
    result = _check(FakeDriver({"E190": 2}), skip_enrichment=True)

    assert result.failures == []
    assert result.warnings == ["OperatingLimits without Chunk: 2 (E190 2)"]


@pytest.mark.parametrize("missing", sorted(LABELS))
def test_the_check_is_skipped_without_limits_or_chunks(missing: str) -> None:
    driver = FakeDriver({"E190": 2})

    result = _check(driver, labels=LABELS - {missing})

    assert result.failures == [] and result.warnings == []
    assert driver.calls == []
