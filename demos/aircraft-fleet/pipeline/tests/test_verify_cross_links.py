"""verify's cross-link checks count the links each enrichment step writes."""

from __future__ import annotations

from typing import Any

from populate_aircraft_db import loader

FakeResult = tuple[list[dict[str, Any]], None, None]


class FakeDriver:
    """Answer the Sensor -> OperatingLimit count and record each query."""

    def __init__(self, sensor_limits: int) -> None:
        self.sensor_limits = sensor_limits
        self.queries: list[str] = []

    def execute_query(self, query: str, **kwargs: object) -> FakeResult:
        self.queries.append(query)
        return [{"count": self.sensor_limits}], None, None


def _rel_counts(**overrides: int) -> dict[str, int]:
    counts = dict.fromkeys(loader.RELATIONSHIP_TYPES, 1)
    counts.update(overrides)
    return counts


def _check(rel_counts: dict[str, int], sensor_limits: int) -> loader._VerifyResult:
    result = loader._VerifyResult(strict=True)
    loader._check_cross_links(rel_counts, sensor_limits, result)
    return result


def test_all_cross_links_present_pass() -> None:
    assert _check(_rel_counts(), sensor_limits=1).failures == []


def test_no_describes_component_links_fail() -> None:
    result = _check(_rel_counts(DESCRIBES_COMPONENT=0), sensor_limits=1)

    assert result.failures == ["ComponentReference -> Component has no links"]


def test_no_sensor_limits_fail_although_other_has_limit_edges_exist() -> None:
    # Extracted SystemReference and ComponentReference nodes carry HAS_LIMIT
    # edges of their own, so the HAS_LIMIT total is not 0.
    rel_counts = _rel_counts(HAS_LIMIT=258)
    driver = FakeDriver(sensor_limits=0)

    sensor_limits = loader._sensor_limit_count(driver, "db", rel_counts)  # type: ignore[arg-type]
    result = _check(rel_counts, sensor_limits)

    assert "(:Sensor)-[r:HAS_LIMIT]->(:OperatingLimit)" in driver.queries[0]
    assert result.failures == ["Sensor -> OperatingLimit has no links"]


def test_the_sensor_count_is_the_sensor_links_only() -> None:
    driver = FakeDriver(sensor_limits=40)

    count = loader._sensor_limit_count(driver, "db", _rel_counts(HAS_LIMIT=298))  # type: ignore[arg-type]

    assert count == 40


def test_the_sensor_count_skips_the_query_with_no_has_limit_edges() -> None:
    driver = FakeDriver(sensor_limits=5)

    count = loader._sensor_limit_count(driver, "db", _rel_counts(HAS_LIMIT=0))  # type: ignore[arg-type]

    assert count == 0
    assert driver.queries == []
