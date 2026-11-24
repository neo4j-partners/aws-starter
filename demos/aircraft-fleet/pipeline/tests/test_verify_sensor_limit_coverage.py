"""verify checks that every Sensor except AirDataDisagree has an OperatingLimit."""

from __future__ import annotations

from typing import Any

import pytest

from populate_aircraft_db import loader

FakeResult = tuple[list[dict[str, Any]], None, None]
LABELS = {"Sensor", "OperatingLimit"}


class FakeDriver:
    """Answer the coverage query with fixed unlinked counts by type."""

    def __init__(self, unlinked: dict[str | None, int]) -> None:
        self.unlinked = unlinked
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute_query(self, query: str, **kwargs: object) -> FakeResult:
        self.calls.append((query, kwargs))
        rows = [{"type": sensor_type, "count": n} for sensor_type, n in self.unlinked.items()]
        return rows, None, None


def _check(
    driver: FakeDriver,
    *,
    labels: set[str] = LABELS,
    skip_enrichment: bool = False,
) -> loader._VerifyResult:
    result = loader._VerifyResult(strict=True, skip_enrichment=skip_enrichment)
    loader._check_sensor_limit_coverage(driver, "db", labels, result)  # type: ignore[arg-type]
    return result


def test_every_sensor_linked_passes() -> None:
    assert _check(FakeDriver({})).failures == []


def test_the_query_exempts_air_data_disagree_sensors() -> None:
    driver = FakeDriver({})

    _check(driver)

    [(query, kwargs)] = driver.calls
    assert "NOT (s)-[:HAS_LIMIT]->(:OperatingLimit)" in query
    assert "NOT coalesce(s.type IN $exempt, false)" in query
    assert kwargs["exempt"] == ["AirDataDisagree"]


def test_unlinked_sensors_fail_with_their_count_by_type(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _check(FakeDriver({"EGT": 2, "Vibration": 30}))

    assert result.failures == ["Sensors without OperatingLimit: 32 (EGT 2, Vibration 30)"]
    out = capsys.readouterr().out
    assert "EGT: 2" in out and "Vibration: 30" in out


def test_sensors_with_no_type_are_labeled_no_type(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _check(FakeDriver({"EGT": 1, None: 2}))

    assert result.failures == ["Sensors without OperatingLimit: 3 (EGT 1, (no type) 2)"]
    assert "(no type): 2" in capsys.readouterr().out


def test_empty_and_missing_types_add_into_one_label() -> None:
    result = _check(FakeDriver({"": 1, None: 2}))

    assert result.failures == ["Sensors without OperatingLimit: 3 ((no type) 3)"]


def test_skip_enrichment_still_fails_unlinked_sensors() -> None:
    # The load makes the HAS_LIMIT links, so a graph with no enrichment
    # must have them too.
    result = _check(FakeDriver({"EGT": 2}), skip_enrichment=True)

    assert result.failures == ["Sensors without OperatingLimit: 2 (EGT 2)"]
    assert result.warnings == []


@pytest.mark.parametrize("missing", sorted(LABELS))
def test_the_check_is_skipped_without_sensors_or_limits(missing: str) -> None:
    driver = FakeDriver({"EGT": 2})

    result = _check(driver, labels=LABELS - {missing})

    assert result.failures == [] and result.warnings == []
    assert driver.calls == []
