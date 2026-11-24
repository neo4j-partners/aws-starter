"""The operating limits the maintenance manuals state, one row per limit.

Each limit comes from the same cells and sentences the manual renderer
writes, so a value is the one the manual prints, rounded as printed. Each
row names the generated block that states it and the exact line or
sentence that states it, so a test can find every limit in the manual.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import manuals
from .specs import (
    ENGINE_SPECS,
    HYDRAULIC_FLUID_TEMPERATURES,
    HYDRAULIC_WATER_CONTENT_MAX,
    VIBRATION_LEVELS,
    EngineSpec,
)

LIMITS_FILE = "operating_limits.csv"


@dataclass(frozen=True)
class OperatingLimit:
    """One limit a manual states, with the block and text that state it."""

    parameter_name: str
    regime: str
    aircraft_type: str
    unit: str
    min_value: float | None
    max_value: float | None
    source_block: str
    source_text: str
    # The name's leading words, when they differ from the parameter name.
    name_prefix: str | None = None

    @property
    def name(self) -> str:
        """The limit's graph name: the parameter, the regime, and the model."""
        prefix = self.name_prefix or self.parameter_name
        return f"{prefix} {self.regime} - {self.aircraft_type}"

    def csv_row(self) -> dict[str, str]:
        """The row for operating_limits.csv. An empty value cell means null."""
        return {
            "name": self.name,
            "parameterName": self.parameter_name,
            "regime": self.regime,
            "aircraftType": self.aircraft_type,
            "unit": self.unit,
            "minValue": format_value(self.min_value),
            "maxValue": format_value(self.max_value),
            "sourceBlock": self.source_block,
            "sourceText": self.source_text,
        }


def format_value(value: float | None) -> str:
    """A plain decimal with no thousands separator, or "" for no value."""
    if value is None:
        return ""
    return str(int(value)) if value.is_integer() else repr(value)


_NUMBER = r"-?[\d,]+(?:\.\d+)?"
_SUFFIX = r"(?:°C| ips)?"
_RANGE = re.compile(rf"({_NUMBER})-({_NUMBER}){_SUFFIX}")
_BOUND = re.compile(rf"([<≤≥]) ?({_NUMBER}){_SUFFIX}")
_LONE = re.compile(rf"({_NUMBER}){_SUFFIX}")
_CRUISE = re.compile(rf"{_NUMBER} \((.+)\)")


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def parse_cell(cell: str) -> tuple[float | None, float | None]:
    """A table cell's minimum and maximum, as the cell prints them.

    "a-b" gives both. "< x", "≤ x", and a lone "x" give a maximum, and
    "≥ x" gives a minimum. A cruise cell such as "85 (83-87)" gives the
    range in its parentheses.

    Raises:
        ValueError: If the cell states no limit, such as "—".
    """
    if cruise := _CRUISE.fullmatch(cell):
        return parse_cell(cruise.group(1))
    if match := _RANGE.fullmatch(cell):
        return _number(match.group(1)), _number(match.group(2))
    if match := _BOUND.fullmatch(cell):
        value = _number(match.group(2))
        return (value, None) if match.group(1) == "≥" else (None, value)
    if match := _LONE.fullmatch(cell):
        return None, _number(match.group(1))
    raise ValueError(f"cell {cell!r} states no limit")


def _split_label(label: str) -> tuple[str, str]:
    """A table row label's parameter and unit: "EGT (°C)" gives ("EGT", "°C")."""
    parameter, _, unit = label.rpartition(" (")
    return parameter, unit.removesuffix(")")


_PHASE_REGIMES = (
    "Ground Idle Normal",
    "Flight Idle Normal",
    "Cruise Normal",
    "Max Continuous Normal",
    "Takeoff Normal",
)
# Normal Operating Parameters rows whose label is not the parameter name.
_PHASE_PARAMETERS = {"Vibration N1": "Vibration"}


def _phase_limits(model: str, engine: EngineSpec) -> list[OperatingLimit]:
    limits = []
    for row in manuals.phase_rows(engine):
        label, *cells = row
        prefix, unit = _split_label(label)
        parameter = _PHASE_PARAMETERS.get(prefix, prefix)
        for regime, cell in zip(_PHASE_REGIMES, cells, strict=True):
            if cell == "—":
                continue
            low, high = parse_cell(cell)
            limits.append(
                OperatingLimit(
                    parameter,
                    regime,
                    model,
                    unit,
                    low,
                    high,
                    "normal-parameters",
                    manuals.table_row(row),
                    name_prefix=prefix if prefix != parameter else None,
                )
            )
    return limits


_EGT_LIMIT_REGIMES = {
    "EGT (Takeoff, 5 min)": "Takeoff",
    "EGT (Max Continuous)": "Max Continuous",
    "EGT (Start)": "Start",
}


def _egt_limits(model: str, engine: EngineSpec) -> list[OperatingLimit]:
    limits = []
    for row in manuals.egt_limit_rows(engine):
        _, maximum = parse_cell(row[-1])
        limits.append(
            OperatingLimit(
                "EGT",
                _EGT_LIMIT_REGIMES[row[0]],
                model,
                "°C",
                None,
                maximum,
                "egt-limits",
                manuals.table_row(row),
            )
        )
    return limits


def _egt_trend_limits(model: str, engine: EngineSpec) -> list[OperatingLimit]:
    _, *thresholds = manuals.egt_trend_thresholds(engine)
    sentence = manuals.egt_trend_sentence(engine)
    return [
        OperatingLimit(
            "EGT",
            f"Trend {level}",
            model,
            "°C",
            _number(threshold),
            None,
            "egt-trend-note",
            sentence,
        )
        for level, threshold in zip(VIBRATION_LEVELS[1:], thresholds, strict=True)
    ]


def _vibration_limits(model: str, engine: EngineSpec) -> list[OperatingLimit]:
    limits = []
    for row in manuals.vibration_rows(model, engine):
        level, band, *_ = row
        if level == "Normal":
            continue
        low, high = parse_cell(band)
        limits.append(
            OperatingLimit(
                "Vibration",
                level,
                model,
                "ips",
                low,
                high,
                "vibration-bands",
                manuals.table_row(row),
                name_prefix="Vibration N1",
            )
        )
    return limits


# The band tables' level columns, after Parameter, Nominal, and Normal.
_BAND_LEVELS = manuals.BAND_HEADER[3:]
_BAND_BLOCKS = {"Hydraulics": "quick-ref-hydraulics", "Avionics": "quick-ref-avionics"}


def _band_limits(model: str) -> list[OperatingLimit]:
    limits = []
    for system, block in _BAND_BLOCKS.items():
        for spec in manuals.band_sensors(system, model):
            row = manuals.low_band_row(spec)
            for level, cell in zip(_BAND_LEVELS, row[3:], strict=True):
                low, high = parse_cell(cell)
                limits.append(
                    OperatingLimit(
                        spec.type,
                        level,
                        model,
                        spec.unit,
                        low,
                        high,
                        block,
                        manuals.table_row(row),
                    )
                )
    return limits


def _gearbox_limits(model: str, engine: EngineSpec) -> list[OperatingLimit]:
    gearbox = engine.gearbox_oil_temperature
    if gearbox is None:
        return []
    row = manuals.table_row(manuals.gearbox_oil_temperature_row(gearbox))
    parameter = "Gearbox Oil Temperature"
    return [
        OperatingLimit(
            parameter, "All", model, "°C", None, gearbox.limit, "gearbox-oil-temperature", row
        ),
        OperatingLimit(
            parameter, "Caution", model, "°C", *gearbox.caution, "gearbox-oil-temperature", row
        ),
        OperatingLimit(
            "Gearbox Oil Outlet Temperature",
            "All",
            model,
            "°C",
            None,
            gearbox.limit,
            "gearbox-temperature-monitoring",
            manuals.gearbox_dispatch_sentence(gearbox),
        ),
    ]


def _hydraulic_fluid_limits(model: str) -> list[OperatingLimit]:
    temperature = HYDRAULIC_FLUID_TEMPERATURES[model]
    operating, warning = manuals.fluid_temperature_sentences(model)
    parameter = "Hydraulic Fluid Temperature"
    block = "hydraulic-fluid-temperature"
    limits = [
        OperatingLimit(
            parameter, "All", model, "°C", temperature.low, temperature.high, block, operating
        )
    ]
    if warning is not None:
        limits.append(
            OperatingLimit(
                parameter, "Warning", model, "°C", temperature.warning_above, None, block, warning
            )
        )
    return limits


def _water_content_limits(model: str) -> list[OperatingLimit]:
    if model not in HYDRAULIC_WATER_CONTENT_MAX:
        return []
    return [
        OperatingLimit(
            "Water Content",
            "All",
            model,
            "% by volume",
            None,
            HYDRAULIC_WATER_CONTENT_MAX[model],
            "hydraulic-water-content",
            manuals.water_content_line(model),
        )
    ]


def model_limits(model: str) -> list[OperatingLimit]:
    """Every limit one model's manual states."""
    engine = ENGINE_SPECS[model]
    return [
        *_egt_limits(model, engine),
        *_egt_trend_limits(model, engine),
        *_vibration_limits(model, engine),
        *_phase_limits(model, engine),
        *_band_limits(model),
        *_gearbox_limits(model, engine),
        *_hydraulic_fluid_limits(model),
        *_water_content_limits(model),
    ]


def operating_limits() -> list[OperatingLimit]:
    """Every limit the manuals state, sorted by aircraft type, then name.

    Raises:
        ValueError: If two limits share a name.
    """
    limits = sorted(
        (limit for model in ENGINE_SPECS for limit in model_limits(model)),
        key=lambda limit: (limit.aircraft_type, limit.name),
    )
    names = [limit.name for limit in limits]
    if duplicates := sorted({name for name in names if names.count(name) > 1}):
        raise ValueError(f"operating limits share a name: {duplicates}")
    return limits


def operating_limit_rows() -> list[dict[str, str]]:
    """The rows of operating_limits.csv."""
    return [limit.csv_row() for limit in operating_limits()]
