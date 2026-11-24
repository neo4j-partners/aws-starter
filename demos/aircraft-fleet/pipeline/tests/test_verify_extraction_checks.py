"""verify --strict checks the extracted EGT limits and System coverage."""

from __future__ import annotations

from typing import Any

import pytest

from generator.specs import ENGINE_SPECS
from populate_aircraft_db import loader
from populate_aircraft_db.pipeline import DOCUMENTS

FakeResult = tuple[list[dict[str, Any]], None, None]


def _limit_rows(overrides: dict[tuple[str, str], object] | None = None) -> list[dict[str, Any]]:
    """One EGT limit row per expected maximum, as the verify query returns it."""
    values: dict[tuple[str, str], object] = {
        key: f"{maximum:g}" for key, maximum in loader.expected_egt_maximums().items()
    }
    values.update(overrides or {})
    return [
        {
            "model": model,
            "regime": regime.lower(),
            "name": f"EGT {regime} - {model}",
            "maxValue": value,
        }
        for (model, regime), value in values.items()
        if value is not None
    ]


class FakeDriver:
    """Answer the EGT limit query and the data quality counts."""

    def __init__(self, limit_rows: list[dict[str, Any]], *, uncovered_systems: int = 0) -> None:
        self.limit_rows = limit_rows
        self.uncovered_systems = uncovered_systems

    def execute_query(self, query: str, **kwargs: object) -> FakeResult:
        if "OperatingLimit" in query:
            return self.limit_rows, None, None
        if "DESCRIBES_SYSTEM" in query:
            return [{"count": self.uncovered_systems}], None, None
        return [{"count": 0}], None, None


def _check_egt(rows: list[dict[str, Any]], *, strict: bool = True) -> loader._VerifyResult:
    result = loader._VerifyResult(strict=strict)
    loader._check_egt_limits(FakeDriver(rows), "db", {"OperatingLimit"}, result)  # type: ignore[arg-type]
    return result


def test_expected_maximums_come_from_the_engine_specs() -> None:
    expected = loader.expected_egt_maximums()

    for model, spec in ENGINE_SPECS.items():
        limits = spec.egt_limits
        assert expected[model, "Takeoff"] == limits.takeoff.maximum
        assert expected[model, "Max Continuous"] == limits.max_continuous.maximum
        assert expected.get((model, "Start")) == limits.start_max


def test_the_a320_has_no_start_maximum() -> None:
    assert ENGINE_SPECS["A320-200"].egt_limits.start_max is None
    assert ("A320-200", "Start") not in loader.expected_egt_maximums()


def test_every_enriched_manual_has_engine_specs() -> None:
    assert {document.aircraft_type for document in DOCUMENTS} == set(ENGINE_SPECS)


def test_matching_limits_pass(capsys: pytest.CaptureFixture[str]) -> None:
    result = _check_egt(_limit_rows())

    assert result.failures == [] and result.warnings == []
    assert "[FAIL]" not in capsys.readouterr().out


@pytest.mark.parametrize("value", ["< 890", "890°C", "890.0"])
def test_a_maximum_written_with_a_symbol_or_unit_still_matches(value: str) -> None:
    assert ENGINE_SPECS["A220-300"].egt_limits.takeoff.maximum == 890

    result = _check_egt(_limit_rows({("A220-300", "Takeoff"): value}))

    assert result.failures == []


def test_a_maximum_with_a_thousands_comma_matches() -> None:
    assert ENGINE_SPECS["A321neo"].egt_limits.takeoff.maximum == 1060

    result = _check_egt(_limit_rows({("A321neo", "Takeoff"): "1,060"}))

    assert result.failures == []


def test_a_wrong_column_maximum_fails() -> None:
    # The A220-300 graph held the Max Continuous value in its Takeoff row.
    result = _check_egt(_limit_rows({("A220-300", "Takeoff"): "855"}))

    assert result.failures == [
        "EGT Takeoff - A220-300 maxValue is '855', "
        "but the generator's Takeoff maximum for A220-300 is 890"
    ]


def test_a_mismatch_is_a_warning_without_strict() -> None:
    result = _check_egt(_limit_rows({("E190", "Start"): "700"}), strict=False)

    assert result.failures == []
    assert result.warnings == [
        "EGT Start - E190 maxValue is '700', but the generator's Start maximum for E190 is 730"
    ]


def test_a_missing_limit_fails() -> None:
    result = _check_egt(_limit_rows({("B737-800", "Max Continuous"): None}))

    assert result.failures == ["B737-800 has no EGT Max Continuous limit"]


def test_a_limit_with_no_max_value_fails() -> None:
    rows = _limit_rows()
    rows[0]["maxValue"] = None

    result = _check_egt(rows)

    assert len(result.failures) == 1
    assert "maxValue is None" in result.failures[0]


def test_a_second_limit_for_the_same_regime_is_checked_too() -> None:
    # A wrong-column read can add an "EGT - <type>" limit beside the right one.
    extra = {"model": "E190", "regime": "takeoff", "name": "EGT - E190", "maxValue": "870"}

    result = _check_egt([*_limit_rows(), extra])

    assert result.failures == [
        "EGT - E190 maxValue is '870', but the generator's Takeoff maximum for E190 is 900"
    ]


def test_an_a320_start_limit_fails_because_the_generator_has_none() -> None:
    extra = {
        "model": "A320-200",
        "regime": "start",
        "name": "EGT Start - A320-200",
        "maxValue": "635",
    }

    result = _check_egt([*_limit_rows(), extra])

    assert result.failures == [
        "EGT Start - A320-200 is an EGT Start limit, but the generator has none for A320-200"
    ]


def test_the_egt_check_is_skipped_without_operating_limits() -> None:
    result = loader._VerifyResult(strict=True)

    loader._check_egt_limits(FakeDriver([]), "db", {"Aircraft"}, result)  # type: ignore[arg-type]

    assert result.failures == []


def _check_quality(uncovered_systems: int, *, relationships: set[str]) -> loader._VerifyResult:
    result = loader._VerifyResult(strict=True)
    labels = {"Reading", "Sensor", "Flight", "Aircraft", "Component", "System"}
    labels |= {"Document", "Chunk", "SystemReference"}
    driver = FakeDriver([], uncovered_systems=uncovered_systems)
    loader._check_data_quality(driver, "db", labels, relationships, result)  # type: ignore[arg-type]
    return result


ALL_RELATIONSHIPS = {"HAS_READING", "OPERATES_FLIGHT", "HAS_COMPONENT", "FROM_DOCUMENT"}


def test_every_system_described_passes() -> None:
    result = _check_quality(0, relationships=ALL_RELATIONSHIPS | {"DESCRIBES_SYSTEM"})

    assert result.failures == []


def test_a_system_with_no_system_reference_fails() -> None:
    result = _check_quality(3, relationships=ALL_RELATIONSHIPS | {"DESCRIBES_SYSTEM"})

    assert result.failures == ["Systems without SystemReference: 3"]


def test_coverage_failures_are_enrichment_failures() -> None:
    result = loader._VerifyResult(strict=True, skip_enrichment=True)
    labels = {"System", "SystemReference"}
    driver = FakeDriver([], uncovered_systems=3)

    loader._check_data_quality(driver, "db", labels, {"DESCRIBES_SYSTEM"}, result)  # type: ignore[arg-type]

    assert result.failures == []
    assert "Systems without SystemReference: 3" in result.warnings


def test_the_count_check_still_reports_no_describes_system_links() -> None:
    result = loader._VerifyResult(strict=True)
    rel_counts = dict.fromkeys(loader.RELATIONSHIP_TYPES, 1)
    rel_counts["DESCRIBES_SYSTEM"] = 0

    loader._check_cross_links(rel_counts, 1, result)

    assert result.failures == ["SystemReference -> System has no links"]
