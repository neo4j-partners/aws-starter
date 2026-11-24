"""operating_limits.csv matches every limit the rendered manuals state.

The test reads the committed manuals and parses their limit blocks on its
own, so it does not reuse the generator's cell parser. A limit the manuals
state but the CSV lacks fails, and so does a CSV row the manuals don't state.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from generator.limits import (
    LIMITS_FILE,
    OperatingLimit,
    operating_limit_rows,
    parse_cell,
    phase_cell,
)
from generator.manuals import MANUAL_FILES, MANUALS_DIR
from generator.specs import HARD_LIMIT_REGIMES, OPERATING_LIMIT_REGIMES
from generator.writers import write_csv

ROWS = operating_limit_rows()
_BLOCK = re.compile(
    r"<!-- BEGIN GENERATED: ([a-z0-9-]+) -->\n(.*?)\n<!-- END GENERATED: \1 -->", re.S
)
# A number in manual text. A hyphen between two numbers is a range, not a sign.
_NUMBER = re.compile(r"(?<![\d.])-?\d[\d,]*(?:\.\d+)?")

# Blocks that only restate limits another block states. They get no rows.
RESTATING_BLOCKS = {"quick-ref-engine", "egt-exceedance", "vibration-shutdown", "fuel-flow-range"}

# Aircraft type, parameter, regime, unit, minimum, maximum, nominal.
Fact = tuple[str, str, str, str, float | None, float | None, float | None]
# A limit's minimum, maximum, and nominal value.
Values = tuple[float | None, float | None, float | None]


def _blocks(model: str) -> dict[str, str]:
    text = (MANUALS_DIR / MANUAL_FILES[model]).read_text(encoding="utf-8")
    return dict(_BLOCK.findall(text))


def _numbers(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in _NUMBER.findall(text)]


def _value(cell: str) -> float | None:
    return float(cell) if cell else None


def _fact(row: dict[str, str]) -> Fact:
    return (
        row["aircraftType"],
        row["parameterName"],
        row["regime"],
        row["unit"],
        _value(row["minValue"]),
        _value(row["maxValue"]),
        _value(row["nominalValue"]),
    )


def _cell(cell: str, *, idle: bool = False) -> Values:
    """A limit cell's minimum, maximum, and nominal, read the way a person reads it.

    A cruise cell's leading number is a typical reading, and so is a lone
    number in an idle column. Neither one is a bound.
    """
    cell = cell.removesuffix("°C").removesuffix(" ips")
    nominal = None
    if cruise := re.fullmatch(r"(\S+) \((.+)\)", cell):
        nominal, cell = _numbers(cruise.group(1))[0], cruise.group(2)
    if cell.startswith("≥ "):
        return _numbers(cell)[0], None, nominal
    if cell.startswith(("< ", "≤ ")):
        return None, _numbers(cell)[0], nominal
    low, *high = _numbers(cell)
    if high:
        return low, high[0], nominal
    return (None, None, low) if idle else (None, low, nominal)


def _cell_unit(cell: str) -> str:
    """The unit after a limit cell's last number: "≥ 3.5 ips" gives "ips"."""
    return re.sub(r"^.*\d", "", cell).strip()


def _table(body: str) -> list[dict[str, str]]:
    """The rows of the Markdown table in a block, keyed by header cell."""
    lines = [line for line in body.splitlines() if line.startswith("|")]
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    return [
        dict(zip(header, (cell.strip() for cell in line.strip("|").split("|")), strict=True))
        for line in lines[2:]
    ]


def _label(label: str) -> tuple[str, str]:
    """A row label's parameter and unit: "EGT (°C)" gives ("EGT", "°C")."""
    parameter, _, unit = label.rpartition(" (")
    return parameter, unit.removesuffix(")")


_PHASE_REGIMES = {
    "Ground Idle": "Ground Idle Normal",
    "Flight Idle": "Flight Idle Normal",
    "Cruise (digital twin)": "Cruise Normal",
    "Max Continuous": "Max Continuous Normal",
    "Takeoff (5 min)": "Takeoff Normal",
}
_IDLE_COLUMNS = {"Ground Idle", "Flight Idle"}
_EGT_REGIMES = {
    "EGT (Takeoff, 5 min)": "Takeoff",
    "EGT (Max Continuous)": "Max Continuous",
    "EGT (Start)": "Start",
}
_BAND_PARAMETERS = {
    "Hydraulic Pressure": "HydPressure",
    "Hydraulic Fluid Quantity": "HydQuantity",
    "DC Bus Voltage": "BusVoltage",
}


def _manual_facts(model: str) -> set[Fact]:
    """Every limit one rendered manual states, parsed from its blocks."""
    blocks = _blocks(model)
    facts: set[Fact] = set()

    def add(parameter: str, regime: str, unit: str, values: Values) -> None:
        facts.add((model, parameter, regime, unit, *values))

    for row in _table(blocks["normal-parameters"]):
        label, unit = _label(row["Parameter"])
        parameter = {"Vibration N1": "Vibration"}.get(label, label)
        for column, regime in _PHASE_REGIMES.items():
            if row[column] != "—":
                idle = column in _IDLE_COLUMNS
                add(parameter, regime, unit, _cell(row[column], idle=idle))
    for row in _table(blocks["egt-limits"]):
        maximum = row["Maximum"]
        add("EGT", _EGT_REGIMES[row["Parameter"]], _cell_unit(maximum), _cell(maximum))
    trend = re.search(
        r"Advisory at (\d+)°C, Caution at (\d+)°C, and Warning at (\d+)°C", blocks["egt-trend-note"]
    )
    assert trend is not None
    for level, value in zip(("Advisory", "Caution", "Warning"), trend.groups(), strict=True):
        add("EGT", f"Trend {level}", "°C", (float(value), None, None))
    for row in _table(blocks["vibration-bands"]):
        if row["Level"] != "Normal":
            band = row["N1 Vibration"]
            add("Vibration", row["Level"], _cell_unit(band), _cell(band))
    for block in ("quick-ref-hydraulics", "quick-ref-avionics"):
        for row in _table(blocks[block]):
            label, unit = _label(row["Parameter"])
            for level in ("Advisory", "Caution", "Warning"):
                add(_BAND_PARAMETERS[label], level, unit, _cell(row[level]))
    if "gearbox-oil-temperature" in blocks:
        [row] = _table(blocks["gearbox-oil-temperature"])
        add("Gearbox Oil Temperature", "Caution", "°C", _cell(row["Caution (°C)"]))
        add("Gearbox Oil Temperature", "All", "°C", _cell(row["Limit (°C)"]))
        outlet = re.search(
            r"operation above (\d+)°C is not permitted", blocks["gearbox-temperature-monitoring"]
        )
        assert outlet is not None
        add("Gearbox Oil Outlet Temperature", "All", "°C", (None, float(outlet.group(1)), None))
    fluid = blocks["hydraulic-fluid-temperature"]
    operating = re.search(r"operate from (-?\d+) to \+(\d+)°C\.", fluid)
    assert operating is not None
    add(
        "Hydraulic Fluid Temperature",
        "All",
        "°C",
        (float(operating.group(1)), float(operating.group(2)), None),
    )
    if warning := re.search(r"Above (\d+)°C is a warning\.", fluid):
        add("Hydraulic Fluid Temperature", "Warning", "°C", (float(warning.group(1)), None, None))
    if "hydraulic-water-content" in blocks:
        water = re.search(r"(\d+(?:\.\d+)?)% by volume", blocks["hydraulic-water-content"])
        assert water is not None
        add("Water Content", "All", "% by volume", (None, float(water.group(1)), None))
    return facts


def test_the_csv_has_one_row_per_limit() -> None:
    assert len(ROWS) == 262


@pytest.mark.parametrize("model", sorted(MANUAL_FILES))
def test_the_csv_matches_every_limit_the_manual_states(model: str) -> None:
    csv_facts = {_fact(row) for row in ROWS if row["aircraftType"] == model}

    manual_facts = _manual_facts(model)

    assert sorted(manual_facts - csv_facts, key=str) == []
    assert sorted(csv_facts - manual_facts, key=str) == []


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["name"])
def test_the_source_text_occurs_once_in_its_block(row: dict[str, str]) -> None:
    body = _blocks(row["aircraftType"])[row["sourceBlock"]]

    assert body.count(row["sourceText"]) == 1


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["name"])
def test_the_source_text_states_the_values(row: dict[str, str]) -> None:
    numbers = _numbers(row["sourceText"])

    for cell in (row["minValue"], row["maxValue"], row["nominalValue"]):
        if cell:
            assert float(cell) in numbers


def test_names_are_unique_and_regimes_are_in_the_vocabulary() -> None:
    names = [row["name"] for row in ROWS]

    assert len(set(names)) == len(names)
    assert {row["regime"] for row in ROWS} <= set(OPERATING_LIMIT_REGIMES)


def test_names_follow_the_graph_form() -> None:
    for row in ROWS:
        prefix = "Vibration N1" if row["parameterName"] == "Vibration" else row["parameterName"]
        assert row["name"] == f"{prefix} {row['regime']} - {row['aircraftType']}"


def test_every_row_has_a_value_and_every_hard_limit_a_maximum() -> None:
    for row in ROWS:
        assert row["minValue"] or row["maxValue"] or row["nominalValue"], row["name"]
        if row["regime"] in HARD_LIMIT_REGIMES:
            assert row["maxValue"], row["name"]


def test_values_are_plain_decimals() -> None:
    for row in ROWS:
        for cell in (row["minValue"], row["maxValue"], row["nominalValue"]):
            assert re.fullmatch(r"(-?\d+(\.\d+)?)?", cell), (row["name"], cell)


def _row(name: str) -> dict[str, str]:
    [row] = [row for row in ROWS if row["name"] == name]
    return row


def test_lone_idle_cells_are_nominal_readings_with_no_bounds() -> None:
    # The A320-200 manual prints one typical reading in each idle column.
    nominal_only = {
        row["name"]: row["nominalValue"]
        for row in ROWS
        if row["nominalValue"] and not (row["minValue"] or row["maxValue"])
    }

    assert nominal_only == {
        "N1Speed Ground Idle Normal - A320-200": "22",
        "N1Speed Flight Idle Normal - A320-200": "28",
        "N2 Ground Idle Normal - A320-200": "58",
        "N2 Flight Idle Normal - A320-200": "65",
        "EGT Ground Idle Normal - A320-200": "380",
        "EGT Flight Idle Normal - A320-200": "450",
    }


def test_every_cruise_row_carries_its_baseline_inside_its_bounds() -> None:
    cruise = [row for row in ROWS if row["regime"] == "Cruise Normal"]

    assert len(cruise) == 20
    for row in cruise:
        nominal = float(row["nominalValue"])
        assert row["maxValue"], row["name"]
        assert nominal < float(row["maxValue"]), row["name"]
        if row["minValue"]:
            assert float(row["minValue"]) < nominal, row["name"]


def test_only_idle_and_cruise_rows_have_a_nominal() -> None:
    regimes = {row["regime"] for row in ROWS if row["nominalValue"]}

    assert regimes == {"Ground Idle Normal", "Flight Idle Normal", "Cruise Normal"}
    assert sum(1 for row in ROWS if row["nominalValue"]) == 26


def test_a_lone_takeoff_cell_stays_a_maximum() -> None:
    row = _row("N1Speed Takeoff Normal - A320-200")

    assert (row["minValue"], row["maxValue"], row["nominalValue"]) == ("", "104", "")


def test_the_rows_are_sorted_by_aircraft_type_then_name() -> None:
    keys = [(row["aircraftType"], row["name"]) for row in ROWS]

    assert keys == sorted(keys)


def test_the_csv_round_trips_through_the_writer(tmp_path: Path) -> None:
    # sourceText holds pipes, commas and quotes, so the file must quote them.
    path = tmp_path / LIMITS_FILE

    assert write_csv(ROWS, path) == len(ROWS)
    with path.open(newline="", encoding="utf-8") as f:
        assert list(csv.DictReader(f)) == ROWS


@pytest.mark.parametrize("model", sorted(MANUAL_FILES))
def test_restating_blocks_state_no_new_limit(model: str) -> None:
    blocks = _blocks(model)
    values = {
        parameter: {
            value
            for row in ROWS
            if row["aircraftType"] == model and row["parameterName"] == parameter
            for value in (_value(row["minValue"]), _value(row["maxValue"]))
            if value is not None
        }
        for parameter in ("EGT", "Vibration", "FuelFlow")
    }

    assert blocks["quick-ref-engine"] == blocks["normal-parameters"]
    assert set(_numbers(blocks["fuel-flow-range"])) <= values["FuelFlow"]
    if "egt-exceedance" in blocks:
        egt = re.findall(r"([\d,]+)°C", blocks["egt-exceedance"])
        assert {float(n.replace(",", "")) for n in egt} <= values["EGT"]
    shutdown = re.findall(r"([\d.]+) ips", blocks["vibration-shutdown"])
    assert {float(n) for n in shutdown} <= values["Vibration"]
    assert not RESTATING_BLOCKS & {row["sourceBlock"] for row in ROWS}


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("20-25", (20, 25)),
        ("< 895", (None, 895)),
        ("1,060°C", (None, 1060)),
        ("≤ 2,400", (None, 2400)),
        ("≥ 4.5 ips", (4.5, None)),
        ("88 (86-90)", (86, 90)),
        ("658 (< 678)", (None, 678)),
        ("0.36 (0.33-0.39)", (0.33, 0.39)),
        ("95", (None, 95)),
    ],
)
def test_parse_cell_reads_each_cell_form(cell: str, expected: tuple) -> None:
    assert parse_cell(cell) == expected


@pytest.mark.parametrize(
    ("cell", "idle", "expected"),
    [
        ("22", True, (None, None, 22)),
        ("22", False, (None, 22, None)),
        ("87 (85-89)", False, (85, 89, 87)),
        ("560 (< 580)", False, (None, 580, 560)),
        ("0.8 (< 2.0)", False, (None, 2.0, 0.8)),
        ("0.15-0.25", True, (0.15, 0.25, None)),
        ("< 2.0", True, (None, 2.0, None)),
        ("< 620", False, (None, 620, None)),
    ],
)
def test_phase_cell_reads_each_normal_parameters_cell(
    cell: str, idle: bool, expected: tuple
) -> None:
    assert phase_cell(cell, idle=idle) == expected


def test_phase_cell_rejects_a_cell_with_no_limit() -> None:
    with pytest.raises(ValueError, match="states no limit"):
        phase_cell("—", idle=True)


def test_parse_cell_rejects_a_cell_with_no_limit() -> None:
    with pytest.raises(ValueError, match="states no limit"):
        parse_cell("—")


def test_an_empty_value_is_an_empty_cell() -> None:
    limit = OperatingLimit("EGT", "Takeoff", "E190", "°C", None, 900.0, "egt-limits", "x")

    row = limit.csv_row()

    assert (row["minValue"], row["maxValue"], row["nominalValue"]) == ("", "900", "")
