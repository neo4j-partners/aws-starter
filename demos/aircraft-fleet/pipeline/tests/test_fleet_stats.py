"""The manuals' statistics come from the generated dataset that setup.sh loads."""

from __future__ import annotations

import copy
import csv
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from generator import main as generator_main
from generator import manuals
from generator.fleet import generate_fleet
from generator.main import generate
from generator.specs import ENGINE_SPECS, FAULT_CODES
from generator.stats import STATS_CONFIG, count_events, fleet_stats

MODEL = "B737-800"
ENGINE = ENGINE_SPECS[MODEL]

STATS = {
    "config": {"aircraft": 30, "days": 90, "seed": 42},
    "models": {
        MODEL: {
            "aircraft": 6,
            "events": 40,
            "by_severity": {"CRITICAL": 4, "MAJOR": 12, "MINOR": 24},
            "by_system": {"Engine": 30, "Avionics": 4, "Hydraulics": 6},
            "by_fault": {
                "Engine": {
                    "Bearing wear": 8,
                    "Contamination": 2,
                    "Fuel starvation": 0,
                    "Leak": 1,
                    "Overheat": 10,
                    "Sensor drift": 3,
                    "Vibration exceedance": 6,
                },
                "Avionics": {"Electrical fault": 1, "Sensor drift": 3},
                "Hydraulics": {"Contamination": 0, "Leak": 6},
            },
        }
    },
}


def _code(code: str):
    return next(c for c in FAULT_CODES if c.code == code)


def _render(block_id: str, stats: dict = STATS) -> str:
    return manuals.RENDERERS[block_id](MODEL, ENGINE, stats)


# Renderers, over hand-made counts.


def test_the_engine_share_names_the_three_most_common_faults() -> None:
    assert _render("system-shares-engine") == (
        "In the generated fleet data, engine systems account for 30 of the B737-800's 40 "
        "maintenance events, or 75%. The most common engine faults are overheat with "
        "10 events, bearing wear with 8, and vibration exceedance with 6."
    )


def test_a_share_with_two_faults_names_both() -> None:
    assert _render("system-shares-avionics") == (
        "In the generated fleet data, avionics accounts for 4 of the B737-800's 40 "
        "maintenance events, or 10%. The avionics faults are sensor drift with 3 events "
        "and electrical fault with 1."
    )


def test_a_share_with_one_fault_says_so() -> None:
    assert _render("system-shares-hydraulics") == (
        "In the generated fleet data, the hydraulics system accounts for 6 of the "
        "B737-800's 40 maintenance events, or 15%. All of them are leak."
    )


def test_a_system_without_events_has_a_zero_share() -> None:
    stats = copy.deepcopy(STATS)
    stats["models"][MODEL]["by_system"]["Hydraulics"] = 0
    stats["models"][MODEL]["by_fault"]["Hydraulics"] = {"Contamination": 0, "Leak": 0}

    assert _render("system-shares-hydraulics", stats) == (
        "In the generated fleet data, the hydraulics system accounts for 0 of the "
        "B737-800's 40 maintenance events, or 0%."
    )
    assert _render(manuals.fault_stats_id(_code("HYD-LEAK-001")), stats).endswith(
        "accounts for 0 of the B737-800's 0 hydraulics maintenance events, or 0%."
    )


def test_a_fault_line_gives_its_share_of_the_system_events() -> None:
    assert _render(manuals.fault_stats_id(_code("AVN-SDR-001"))) == (
        "**Fleet Statistics:** In the generated fleet data, sensor drift accounts for 3 of "
        "the B737-800's 4 avionics maintenance events, or 75%."
    )


def test_a_manual_only_fault_line_says_the_generator_never_raises_it() -> None:
    assert _render(manuals.fault_stats_id(_code("ENG-ELF-008"))) == (
        "**Fleet Statistics:** The generated fleet data has no engine electrical fault "
        "events, because the data generator does not raise this fault."
    )


def test_the_fleet_statistics_name_the_config_and_rank_the_faults() -> None:
    assert _render("fleet-statistics") == (
        "These figures are counts from this demo's generated fleet data: 30 aircraft over "
        "90 days, seed 42. The B737-800 has 6 of the aircraft and 40 of the maintenance "
        "events.\n\n"
        "**Events by Severity:**\n\n"
        "| Severity | Events | Share |\n|----------|--------|-------|\n"
        "| Critical | 4 | 10% |\n| Major | 12 | 30% |\n| Minor | 24 | 60% |\n\n"
        "**Events by System:**\n\n"
        "| System | Events | Share |\n|--------|--------|-------|\n"
        "| Engine | 30 | 75% |\n| Avionics | 4 | 10% |\n| Hydraulics | 6 | 15% |\n\n"
        "**Events by Fault:**\n\n"
        "| Fault | System | Events | Share |\n|-------|--------|--------|-------|\n"
        "| Overheat | Engine | 10 | 25% |\n"
        "| Bearing wear | Engine | 8 | 20% |\n"
        "| Vibration exceedance | Engine | 6 | 15% |\n"
        "| Leak | Hydraulics | 6 | 15% |\n"
        "| Sensor drift | Engine | 3 | 8% |\n"
        "| Sensor drift | Avionics | 3 | 8% |\n"
        "| Contamination | Engine | 2 | 5% |\n"
        "| Leak | Engine | 1 | 3% |\n"
        "| Electrical fault | Avionics | 1 | 3% |"
    )


@pytest.mark.parametrize(
    ("count", "total", "share"),
    [
        (1, 8, "13%"),  # 12.5 rounds half up, not to the even 12
        (5, 200, "3%"),  # 2.5 rounds half up, not to the even 2
        (199, 200, "99%"),  # 99.5 would show 100% for a share below all
        (200, 200, "100%"),
        (0, 0, "0%"),
    ],
)
def test_a_share_rounds_half_up_and_only_all_events_show_100(
    count: int, total: int, share: str
) -> None:
    assert manuals._share(count, total) == share


def test_every_fault_code_has_its_own_stats_block() -> None:
    ids = [manuals.fault_stats_id(code) for code in FAULT_CODES]

    assert len(set(ids)) == len(ids)
    assert not set(ids) & set(manuals.REQUIRED_BLOCKS)


# Counting.


def test_count_events_lists_every_routed_fault_with_zero_counts() -> None:
    fleet = generate_fleet(STATS_CONFIG)
    aircraft = next(a for a in fleet if a.model == MODEL)
    engine = next(s for s in aircraft.systems if s.type == "Engine")
    rows = [
        {"aircraft_id": aircraft.aircraft_id, "system_id": engine.system_id,
         "severity": "MAJOR", "fault": "Overheat"},
    ]  # fmt: skip

    counts = count_events(fleet, rows, STATS_CONFIG)["models"][MODEL]

    assert counts["aircraft"] == sum(a.model == MODEL for a in fleet)
    assert counts["events"] == 1
    assert counts["by_severity"] == {"CRITICAL": 0, "MAJOR": 1, "MINOR": 0}
    assert counts["by_system"] == {"Engine": 1, "Avionics": 0, "Hydraulics": 0}
    assert counts["by_fault"]["Engine"]["Overheat"] == 1
    assert sum(counts["by_fault"]["Engine"].values()) == 1
    assert counts["by_fault"]["Hydraulics"] == {"Contamination": 0, "Leak": 0}


def test_the_stats_config_is_the_setup_default() -> None:
    setup = (Path(__file__).parent.parent / "setup.sh").read_text(encoding="utf-8")
    defaults = dict(re.findall(r"^\s*DEFAULT_(AIRCRAFT|DAYS)=(\d+)", setup, re.MULTILINE))

    assert len(defaults) == 2, defaults
    assert int(defaults["AIRCRAFT"]) == STATS_CONFIG.n_aircraft
    assert int(defaults["DAYS"]) == STATS_CONFIG.n_days
    assert re.search(rf"GEN_SEED:-{STATS_CONFIG.seed}\}}", setup)
    assert re.search(rf"GEN_AIRPORTS:-{STATS_CONFIG.n_airports}\}}", setup)


# The committed file.


def test_fleet_stats_current() -> None:
    # A generator change that moves the counts fails here until
    # `generate-data stats` and `generate-data render-manuals` are re-run.
    assert manuals.load_stats() == fleet_stats(), (
        "manuals/fleet-stats.json is stale; run `uv run generate-data stats` "
        "and `uv run generate-data render-manuals`"
    )


def test_the_stats_match_the_dataset_a_generate_writes(tmp_path: Path) -> None:
    config = STATS_CONFIG
    generate(
        aircraft=config.n_aircraft,
        airports=config.n_airports,
        days=config.n_days,
        seed=config.seed,
        output=tmp_path,
    )
    with (tmp_path / "nodes_maintenance.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert count_events(generate_fleet(config), rows, config) == fleet_stats()


def test_the_stats_command_writes_the_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(generator_main.app, ["stats", "--manuals-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert json.loads((tmp_path / manuals.STATS_NAME).read_text()) == fleet_stats()


# Placement in the manuals.


def _stats_blocks(text: str) -> list[tuple[str, str]]:
    """Each fault statistics block id, with the heading above it."""
    out = []
    heading = ""
    for line in text.splitlines():
        if re.match(r"^#{3,5} \d", line):
            heading = line.lstrip("# ")
        elif match := re.match(
            rf"^<!-- BEGIN GENERATED: ({manuals.FAULT_STATS_PREFIX}\S+) -->$", line
        ):
            out.append((match.group(1), heading))
    return out


def _fault_code_lines(text: str) -> list[tuple[str, str]]:
    """Each "**Fault Code:**" line's code, with the heading above it.

    A line that starts like one in any other form raises, so a variant fails
    a test instead of being skipped.
    """
    out = []
    heading = ""
    for line in text.splitlines():
        if re.match(r"^#{3,5} \d", line):
            heading = line.lstrip("# ")
        elif re.match(r"^\*\*Fault Codes?:\*\*", line, re.IGNORECASE):
            match = re.fullmatch(r"\*\*Fault Code:\*\* (\S+)", line)
            if match is None:
                raise ValueError(f"not a plain Fault Code line: {line!r}")
            out.append((match.group(1), heading))
    return out


def test_a_fault_code_line_variant_fails_instead_of_vanishing() -> None:
    with pytest.raises(ValueError, match="not a plain Fault Code line"):
        _fault_code_lines("### 4.1 Overheat\n**Fault Codes:** ENG-OVH-006\n")


@pytest.mark.parametrize("model", sorted(manuals.MANUAL_FILES))
def test_each_fault_section_has_the_stats_block_of_its_code(model: str) -> None:
    text = (manuals.MANUALS_DIR / manuals.MANUAL_FILES[model]).read_text(encoding="utf-8")
    expected = [(manuals.fault_stats_id(_code(c)), h) for c, h in _fault_code_lines(text)]

    assert len(expected) >= 6
    assert _stats_blocks(text) == expected


@pytest.mark.parametrize("model", sorted(manuals.MANUAL_FILES))
def test_no_manual_quotes_industry_statistics(model: str) -> None:
    text = (manuals.MANUALS_DIR / manuals.MANUAL_FILES[model]).read_text(encoding="utf-8")

    assert not re.findall(r".*industry.*", text, re.IGNORECASE)


def _root_cause_sections(text: str) -> list[str]:
    """The body of each "Common Root Causes" section, up to the next heading."""
    return re.findall(
        r"^#{3,5} Common Root Causes.*?\n(.*?)(?=^#|\Z)", text, re.MULTILINE | re.DOTALL
    )


def test_a_percentage_in_a_root_cause_section_is_found() -> None:
    text = "#### Common Root Causes\n- Fan blade damage (40% of cases)\n\n### 4.3 Next\n"

    assert re.findall(r"\d\s*%", _root_cause_sections(text)[0]) == ["0%"]


@pytest.mark.parametrize("model", sorted(manuals.MANUAL_FILES))
def test_no_root_cause_section_quotes_a_percentage(model: str) -> None:
    # The fleet's own fault shares are in the generated blocks. A hand-written
    # percentage of cases is not drawn from the data, so it does not belong.
    # A guard on every bare percentage in a fault section would also catch
    # legitimate thresholds, such as sensor drift > 10% or motoring to 20% N2.
    text = (manuals.MANUALS_DIR / manuals.MANUAL_FILES[model]).read_text(encoding="utf-8")
    sections = _root_cause_sections(text)

    assert sections
    assert not [s for s in sections if re.search(r"\d\s*%", s)]
