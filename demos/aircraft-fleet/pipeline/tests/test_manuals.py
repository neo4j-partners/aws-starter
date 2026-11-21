"""Generated blocks in the maintenance manuals are rendered from specs.

A block sits between two marker lines. Rendering replaces what is between
them and leaves every other line as it was.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from manual_text import fault_code_lines
from typer.testing import CliRunner

from generator import main as generator_main
from generator import manuals
from generator.config import GeneratorConfig
from generator.fleet import generate_fleet
from generator.maintenance import SEVERITY_BY_LEVEL
from generator.manuals import ManualBlockError, render_text
from generator.specs import (
    COMPONENT_ALIASES,
    CORRECTIVE_ACTIONS,
    ENGINE_SPECS,
    FAULT_CODES,
    MANUAL_FLEET_TAILS,
    PHASES,
    SYSTEM_SENSORS,
    VIBRATION_LEVELS,
    FaultCode,
    sensors_for,
)
from populate_aircraft_db.pipeline import DOCUMENTS, read_manual_text, strip_comments

MODEL = "B737-800"


def _greeting(model: str, engine: object, stats: object) -> str:
    return f"Hello from the {model}."


def _two_lines(model: str, engine: object, stats: object) -> str:
    return "Line one.\nLine two."


RENDERERS = {"greeting": _greeting, "two-lines": _two_lines}


def _render(text: str, required: tuple[str, ...] = ()) -> str:
    return render_text(text, MODEL, {}, renderers=RENDERERS, required=required)


def _block(block_id: str, body: str) -> str:
    return f"<!-- BEGIN GENERATED: {block_id} -->\n{body}\n<!-- END GENERATED: {block_id} -->\n"


def test_a_block_body_is_replaced_and_the_rest_is_kept() -> None:
    text = "# Title\n\nBefore.\n" + _block("greeting", "stale") + "After.\n"

    assert _render(text) == (
        "# Title\n\nBefore.\n" + _block("greeting", "Hello from the B737-800.") + "After.\n"
    )


def test_an_empty_block_and_a_multi_line_body_render() -> None:
    text = "<!-- BEGIN GENERATED: two-lines -->\n<!-- END GENERATED: two-lines -->\n" + _block(
        "greeting", "old\nlines\nhere"
    )

    assert _render(text) == _block("two-lines", "Line one.\nLine two.") + _block(
        "greeting", "Hello from the B737-800."
    )


def test_rendering_is_idempotent() -> None:
    once = _render("A\n" + _block("greeting", "") + "B\n" + _block("two-lines", "x"))

    assert _render(once) == once


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param(
            _block("unknown-id", "x"),
            "line 1: unknown block id 'unknown-id'",
            id="unknown-id",
        ),
        pytest.param(
            "<!-- BEGIN GENERATED: greeting -->\nbody\n",
            "line 1: block 'greeting' has no END marker",
            id="missing-end",
        ),
        pytest.param(
            "text\n<!-- END GENERATED: greeting -->\n",
            "line 2: END marker for 'greeting' without a BEGIN",
            id="end-without-begin",
        ),
        pytest.param(
            "<!-- BEGIN GENERATED: greeting -->\n<!-- END GENERATED: two-lines -->\n",
            "line 2: END marker for 'two-lines' inside block 'greeting'",
            id="mismatched-end",
        ),
        pytest.param(
            "<!-- BEGIN GENERATED: greeting -->\n<!-- BEGIN GENERATED: two-lines -->\n",
            "line 2: BEGIN marker for 'two-lines' inside block 'greeting'",
            id="nested-begin",
        ),
        pytest.param(
            _block("greeting", "a") + _block("greeting", "b"),
            "line 4: block 'greeting' appears twice",
            id="duplicate",
        ),
        pytest.param(
            "<!--BEGIN GENERATED: greeting-->\n",
            "line 1: malformed marker '<!--BEGIN GENERATED: greeting-->'",
            id="malformed",
        ),
        pytest.param(
            "```markdown\n" + _block("greeting", "a") + "```\n",
            "line 2: marker inside a fenced code block",
            id="in-backtick-fence",
        ),
        pytest.param(
            "Text.\n~~~\n<!-- END GENERATED: greeting -->\n~~~\n",
            "line 3: marker inside a fenced code block",
            id="in-tilde-fence",
        ),
        pytest.param(
            "```\n<!--BEGIN GENERATED: greeting-->\n```\n",
            "line 2: marker inside a fenced code block",
            id="malformed-in-fence",
        ),
    ],
)
def test_bad_markers_raise_with_the_line(text: str, message: str) -> None:
    with pytest.raises(ManualBlockError, match=f"^{message}$"):
        _render(text)


def test_a_fence_inside_a_block_is_the_block_body() -> None:
    # A block's old body is replaced, so an unclosed fence in it does not
    # put the next block's markers inside a fence.
    text = _block("greeting", "```\nstale") + _block("two-lines", "")

    assert _render(text) == (
        _block("greeting", "Hello from the B737-800.") + _block("two-lines", "Line one.\nLine two.")
    )


def test_a_leading_byte_order_mark_is_dropped() -> None:
    assert _render("\ufeff" + _block("greeting", "stale")) == _block(
        "greeting", "Hello from the B737-800."
    )


def test_crlf_line_endings_render_as_lf() -> None:
    text = ("# Title\n" + _block("greeting", "stale")).replace("\n", "\r\n")

    assert _render(text) == "# Title\n" + _block("greeting", "Hello from the B737-800.")


def test_git_checks_out_the_manuals_with_lf_endings() -> None:
    path = manuals.MANUALS_DIR / manuals.MANUAL_FILES[MODEL]
    result = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", path.name],
        cwd=path.parent,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.splitlines() == [f"{path.name}: text: set", f"{path.name}: eol: lf"]


def test_a_missing_required_block_raises() -> None:
    with pytest.raises(ManualBlockError, match="^missing required block 'two-lines'$"):
        _render(_block("greeting", ""), required=("greeting", "two-lines"))


def test_the_manual_files_match_the_document_registry() -> None:
    assert {d.aircraft_type: d.filename for d in DOCUMENTS} == manuals.MANUAL_FILES
    assert set(manuals.MANUAL_FILES) == set(ENGINE_SPECS)


def test_every_required_block_has_a_renderer() -> None:
    assert set(manuals.REQUIRED_BLOCKS) <= set(manuals.RENDERERS)


@pytest.mark.parametrize("model", sorted(manuals.MANUAL_FILES))
def test_manuals_in_sync(model: str) -> None:
    # Every required block is present once, and its body is what specs render.
    path = manuals.MANUALS_DIR / manuals.MANUAL_FILES[model]
    text = path.read_text(encoding="utf-8")

    assert manuals.render_text(text, model, manuals.load_stats()) == text, (
        f"{path.name} has drifted; run `uv run generate-data render-manuals`"
    )


# The render-manuals command, over a copy of the manuals with a test registry.


@pytest.fixture
def manuals_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(manuals, "RENDERERS", RENDERERS)
    monkeypatch.setattr(manuals, "REQUIRED_BLOCKS", ("greeting",))
    monkeypatch.setattr(manuals, "load_stats", lambda manuals_dir: {})
    for model, filename in manuals.MANUAL_FILES.items():
        body = f"Hello from the {model}."
        (tmp_path / filename).write_text(f"# {model}\n" + _block("greeting", body))
    return tmp_path


def _cli(manuals_dir: Path, *args: str):
    return CliRunner().invoke(
        generator_main.app, ["render-manuals", "--manuals-dir", str(manuals_dir), *args]
    )


def test_check_passes_when_the_manuals_are_in_sync(manuals_dir: Path) -> None:
    result = _cli(manuals_dir, "--check")

    assert result.exit_code == 0, result.output
    assert "5 manuals in sync" in result.output


def test_check_exits_1_with_a_diff_and_writes_nothing(manuals_dir: Path) -> None:
    drifted = manuals_dir / manuals.MANUAL_FILES[MODEL]
    stale = "# B737-800\n" + _block("greeting", "Hello from a stale manual.")
    drifted.write_text(stale)

    result = _cli(manuals_dir, "--check")

    assert result.exit_code == 1
    assert "-Hello from a stale manual." in result.output
    assert "+Hello from the B737-800." in result.output
    assert f"{drifted.name} has drifted" in result.output
    assert drifted.read_text() == stale


def test_render_rewrites_only_the_drifted_manual(manuals_dir: Path) -> None:
    drifted = manuals_dir / manuals.MANUAL_FILES[MODEL]
    drifted.write_text("# B737-800\n" + _block("greeting", "stale"))
    other = manuals_dir / manuals.MANUAL_FILES["E190"]
    before = other.stat().st_mtime_ns

    result = _cli(manuals_dir)

    assert result.exit_code == 0, result.output
    assert drifted.read_text() == "# B737-800\n" + _block("greeting", "Hello from the B737-800.")
    assert other.stat().st_mtime_ns == before
    assert f"Rendered {drifted.name}" in result.output


def test_a_bad_manual_stops_the_render_before_any_manual_is_written(
    manuals_dir: Path,
) -> None:
    first, *_, last = manuals.MANUAL_FILES.items()
    drifted = manuals_dir / first[1]
    stale = f"# {first[0]}\n" + _block("greeting", "stale")
    drifted.write_text(stale)
    (manuals_dir / last[1]).write_text(f"# {last[0]}\n<!-- BEGIN GENERATED: greeting -->\n")

    result = _cli(manuals_dir)

    assert result.exit_code == 1
    assert f"{last[1]}: line 2: block 'greeting' has no END marker" in result.output
    assert drifted.read_text() == stale
    assert "Rendered" not in result.output


def test_a_bad_marker_exits_1_with_the_file_and_line(manuals_dir: Path) -> None:
    broken = manuals_dir / manuals.MANUAL_FILES[MODEL]
    broken.write_text("# B737-800\n<!-- BEGIN GENERATED: greeting -->\n")

    result = _cli(manuals_dir, "--check")

    assert result.exit_code == 1
    assert f"{broken.name}: line 2: block 'greeting' has no END marker" in result.output


# The loader drops comments, so markers never reach chunks or the LLM.


def test_strip_comments_drops_marker_lines_and_inline_comments() -> None:
    text = (
        "# Title\n"
        + _block("greeting", "Body.")
        + "Keep <!-- inline --> this.\n"
        + "<!-- a comment\nover two lines -->\n"
        + "End.\n"
    )

    assert strip_comments(text) == "# Title\nBody.\nKeep  this.\nEnd.\n"


def test_strip_comments_keeps_text_between_two_comments() -> None:
    # A comment ends at its first "-->", so a line comment cannot run on to
    # a later comment and take the text between them.
    text = "<!-- note --> keep this\nmore text <!-- x -->\nlast\n"

    assert strip_comments(text) == " keep this\nmore text \nlast\n"


def test_read_manual_text_strips_comments_and_outer_space(tmp_path: Path) -> None:
    path = tmp_path / "manual.md"
    path.write_text("\n" + _block("greeting", "Body.") + "\n", encoding="utf-8")

    assert read_manual_text(path) == "Body."


# Spec-driven blocks.


def _rows(markdown: str) -> list[list[str]]:
    """The body rows of the first markdown table, as stripped cells."""
    lines = [line for line in markdown.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in lines[2:]]


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_sensor_table_lists_every_generated_sensor_with_its_spec_unit(model: str) -> None:
    table = manuals.RENDERERS["sensor-table"](model, ENGINE_SPECS[model], {})

    expected = [
        [system, spec.type, spec.name, spec.unit]
        for system in SYSTEM_SENSORS
        for spec in sensors_for(system, model)
    ]
    assert [row[:4] for row in _rows(table)] == expected
    assert all(row[4] for row in _rows(table))


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_egt_note_quotes_the_spec_baseline_and_bands(model: str) -> None:
    egt = {s.type: s for s in sensors_for("Engine", model)}["EGT"]
    note = manuals.RENDERERS["egt-trend-note"](model, ENGINE_SPECS[model], {})

    b = egt.bands
    assert (
        f"baseline is {egt.baseline:g}°C, with Advisory at {b.advisory:g}°C, "
        f"Caution at {b.caution:g}°C, and Warning at {b.warning:g}°C"
    ) in note
    assert ENGINE_SPECS[model].engine_type in note


def _registry_aircraft(model: str):
    """The first generated aircraft of model, which carries a manual tail."""
    fleet = generate_fleet(GeneratorConfig(n_aircraft=len(MANUAL_FLEET_TAILS)))
    return next(a for a in fleet if a.model == model)


def _resolve(label: str) -> str | None:
    """The component type a tree label names, by its full text or its words before ' ('."""
    for candidate in (label, label.split(" (")[0]):
        if (component_type := COMPONENT_ALIASES.get(candidate.lower())) is not None:
            return component_type
    return None


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_component_tree_matches_the_generated_aircraft(model: str) -> None:
    tree = manuals.RENDERERS["component-tree"](model, ENGINE_SPECS[model], {})
    aircraft = _registry_aircraft(model)

    groups: list[tuple[str, list[str]]] = []
    for line in tree.splitlines():
        if (header := re.match(r"^[├└]── (.+)$", line)) is not None:
            groups.append((header[1], []))
        elif (leaf := re.match(r"^[│ ]   [├└]── (.+)$", line)) is not None:
            groups[-1][1].append(leaf[1])

    engine = ENGINE_SPECS[model].engine_type
    assert [header for header, _ in groups] == [
        f"ENGINE SYSTEM #1 ({engine} Left)",
        f"ENGINE SYSTEM #2 ({engine} Right)",
        "AVIONICS SYSTEM",
        "HYDRAULICS SYSTEM",
    ]
    assert [[_resolve(label) for label in leaves] for _, leaves in groups] == [
        [c.type for c in system.components] for system in aircraft.systems
    ]
    assert tree.startswith(f"```\nAIRCRAFT ({model})\n")
    assert tree.endswith("\n```")


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_component_id_example_names_a_generated_component(model: str) -> None:
    block = manuals.RENDERERS["component-ids"](model, ENGINE_SPECS[model], {})
    aircraft = _registry_aircraft(model)

    example = re.search(r"Example: (\S+)", block)[1]
    component = next(c for s in aircraft.systems for c in s.components if c.component_id == example)
    assert f"└── Component: {component.name}" in block
    assert "└─────── System: Engine #1" in block
    assert f"└─────────────── Aircraft: {aircraft.aircraft_id} ({aircraft.tail_number})" in block
    codes = re.findall(r"^- (S\d\d): (.+)$", block, re.MULTILINE)
    assert [code for code, _ in codes] == [s.system_id[-3:] for s in aircraft.systems]
    assert [name for _, name in codes][2:] == ["Avionics", "Hydraulics"]


def _vibration(model: str):
    return {s.type: s for s in sensors_for("Engine", model)}["Vibration"]


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_vibration_table_is_the_spec_bands_and_event_severities(model: str) -> None:
    table = manuals.RENDERERS["vibration-bands"](model, ENGINE_SPECS[model], {})
    b = _vibration(model).bands

    assert table.splitlines()[0] == "| Level | N1 Vibration | Event Severity | Flight Deck Alert |"
    assert [row[:3] for row in _rows(table)] == [
        ["Normal", f"< {b.advisory:.1f} ips", "None"],
        ["Advisory", f"{b.advisory:.1f}-{b.caution:.1f} ips", SEVERITY_BY_LEVEL[1]],
        ["Caution", f"{b.caution:.1f}-{b.warning:.1f} ips", SEVERITY_BY_LEVEL[2]],
        ["Warning", f"≥ {b.warning:.1f} ips", SEVERITY_BY_LEVEL[3]],
    ]
    assert [row[0] for row in _rows(table)] == list(VIBRATION_LEVELS)


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_shutdown_note_quotes_the_spec_bands(model: str) -> None:
    note = manuals.RENDERERS["vibration-shutdown"](model, ENGINE_SPECS[model], {})
    b = _vibration(model).bands

    for level, value in (("Warning", b.warning), ("Caution", b.caution), ("Advisory", b.advisory)):
        assert f"The {level} level starts at {value:.1f} ips." in note


_BLOCK = re.compile(
    r"^<!-- BEGIN GENERATED: ([a-z0-9-]+) -->$.*?^<!-- END GENERATED: \1 -->$", re.M | re.S
)


@pytest.mark.parametrize("model", sorted(manuals.MANUAL_FILES))
def test_only_generated_blocks_quote_vibration_numbers(model: str) -> None:
    # Hand-written text names a level instead, so the numbers live in one place.
    text = (manuals.MANUALS_DIR / manuals.MANUAL_FILES[model]).read_text(encoding="utf-8")

    assert re.findall(r"^.*\d ips.*$", _BLOCK.sub("", text), re.M) == []


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_egt_limits_table_is_the_spec_limits(model: str) -> None:
    table = manuals.RENDERERS["egt-limits"](model, ENGINE_SPECS[model], {})
    limits = ENGINE_SPECS[model].egt_limits

    def row(label: str, band) -> list[str]:
        return [
            label,
            f"< {band.normal_below:,.0f}°C",
            f"{band.normal_below:,.0f}-{band.maximum:,.0f}°C",
            f"{band.maximum:,.0f}°C",
        ]

    expected = [
        row("EGT (Takeoff, 5 min)", limits.takeoff),
        row("EGT (Max Continuous)", limits.max_continuous),
    ]
    if limits.start_max is not None:
        expected.append(["EGT (Start)", "—", "—", f"{limits.start_max:,.0f}°C"])
    assert table.splitlines()[0] == "| Parameter | Normal | Caution | Maximum |"
    assert _rows(table) == expected


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_egt_bands_leave_no_gap(model: str) -> None:
    # Normal runs to the caution band, and Caution runs to the maximum, so
    # every temperature has one band. Above the maximum is Warning.
    table = manuals.RENDERERS["egt-limits"](model, ENGINE_SPECS[model], {})
    rows = [row for row in _rows(table) if row[0] != "EGT (Start)"]

    assert [row[0] for row in rows] == ["EGT (Takeoff, 5 min)", "EGT (Max Continuous)"]
    for label, normal, caution, maximum in rows:
        low, high = caution.removesuffix("°C").split("-")
        assert normal == f"< {low}°C", label
        assert maximum == f"{high}°C", label


# A hand-written band in prose: "Normal is below a. Caution is a-b. The
# maximum is c."
_PROSE_BANDS = re.compile(
    r"Normal is below ([\d,]+)°C\. Caution is ([\d,]+)-([\d,]+)°C\. "
    r"The maximum is ([\d,]+)°C\."
)


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_a_hand_written_temperature_band_leaves_no_gap(model: str) -> None:
    for normal, low, high, maximum in _PROSE_BANDS.findall(_manual(model)):
        assert (normal, high) == (low, maximum)


def test_the_a321neo_states_its_itt_bands() -> None:
    assert _PROSE_BANDS.search(_manual("A321neo"))


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_egt_limits_are_ordered_and_above_the_trend_scale(model: str) -> None:
    limits = ENGINE_SPECS[model].egt_limits
    for band in (limits.max_continuous, limits.takeoff):
        assert band.normal_below < band.maximum, band
    assert limits.max_continuous.maximum <= limits.takeoff.maximum
    # Every trend reading the generator raises an event for stays below the
    # instantaneous max continuous limit.
    egt = {s.type: s for s in sensors_for("Engine", model)}["EGT"]
    assert egt.bands.warning < limits.max_continuous.normal_below


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_n1_at_the_warning_band_stays_at_or_below_max_continuous(model: str) -> None:
    n1 = {s.type: s for s in sensors_for("Engine", model)}["N1Speed"]
    max_continuous = ENGINE_SPECS[model].phase_limits["N1Speed (%)"][2]

    assert n1.baseline + n1.bands.warning <= float(max_continuous)


def _phase_table(model: str) -> dict[str, list[str]]:
    table = manuals.RENDERERS["normal-parameters"](model, ENGINE_SPECS[model], {})
    assert table.splitlines()[0] == (
        "| Parameter | Ground Idle | Flight Idle | Cruise (digital twin) "
        "| Max Continuous | Takeoff (5 min) |"
    )
    return {row[0]: row[1:] for row in _rows(table)}


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_both_parameter_tables_render_the_same_text(model: str) -> None:
    engine = ENGINE_SPECS[model]
    assert manuals.RENDERERS["normal-parameters"](model, engine, {}) == manuals.RENDERERS[
        "quick-ref-engine"
    ](model, engine, {})


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_parameter_table_rows_come_from_the_specs(model: str) -> None:
    engine = ENGINE_SPECS[model]
    rows = _phase_table(model)
    specs = {s.type: s for s in engine.sensors}
    limits = engine.egt_limits
    advisory = f"< {specs['Vibration'].bands.advisory:.1f}"

    assert rows["EGT (°C)"][:2] == [limits.ground_idle, limits.flight_idle]
    assert rows["EGT (°C)"][3:] == [
        f"< {limits.max_continuous.normal_below:,.0f}",
        f"< {limits.takeoff.normal_below:,.0f}",
    ]
    vibration = rows["Vibration N1 (ips)"]
    assert vibration[:2] + vibration[3:] == [advisory] * 4
    for label, cells in engine.phase_limits.items():
        assert rows[label][:2] + rows[label][3:] == list(cells), label
        if label not in ("N1Speed (%)", "FuelFlow (kg/s)"):
            assert rows[label][2] == "—", label
    assert set(rows) == set(engine.phase_limits) | {"EGT (°C)", "Vibration N1 (ips)"}
    assert len(PHASES) == 4


def test_the_fuel_flow_range_runs_from_ground_idle_to_takeoff() -> None:
    engine = ENGINE_SPECS["A320-200"]

    assert engine.phase_limits["FuelFlow (kg/s)"][0].startswith("0.15-")
    assert engine.phase_limits["FuelFlow (kg/s)"][3].endswith("-1.95")
    assert manuals.RENDERERS["fuel-flow-range"]("A320-200", engine, {}) == (
        "**Flow Rate:** 0.15 - 1.95 kg/s (ground idle to takeoff)"
    )


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_fuel_flow_range_holds_every_phase_and_the_cruise_baseline(model: str) -> None:
    engine = ENGINE_SPECS[model]
    line = manuals.RENDERERS["fuel-flow-range"](model, engine, {})
    low, high = map(float, re.findall(r"\d+\.\d+", line))
    fuel = {s.type: s for s in engine.sensors}["FuelFlow"]

    for cell in engine.phase_limits["FuelFlow (kg/s)"]:
        cell_low, cell_high = map(float, cell.split("-"))
        assert low <= cell_low <= cell_high <= high, cell
    assert low < fuel.baseline < high


@pytest.mark.parametrize("model", sorted(manuals.MANUAL_FILES))
def test_only_generated_blocks_quote_fuel_flow_numbers(model: str) -> None:
    text = (manuals.MANUALS_DIR / manuals.MANUAL_FILES[model]).read_text(encoding="utf-8")

    assert re.findall(r"^.*\d\s*kg/s.*$", _BLOCK.sub("", text), re.M) == []


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_each_cruise_cell_holds_its_spec_baseline(model: str) -> None:
    rows = _phase_table(model)
    labels = {
        "N1Speed": "N1Speed (%)",
        "EGT": "EGT (°C)",
        "FuelFlow": "FuelFlow (kg/s)",
        "Vibration": "Vibration N1 (ips)",
    }
    for spec in sensors_for("Engine", model):
        assert rows[labels[spec.type]][2].startswith(f"{spec.baseline:g} ("), spec.type


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_hydraulics_table_is_the_spec_bands(model: str) -> None:
    table = manuals.RENDERERS["quick-ref-hydraulics"](model, ENGINE_SPECS[model], {})

    assert table.splitlines()[0] == (
        "| Parameter | Nominal | Normal | Advisory | Caution | Warning |"
    )
    expected = []
    for spec in sensors_for("Hydraulics", model):
        b, u = spec.bands, spec.unit
        expected.append(
            [
                f"{spec.name} ({u})",
                f"{spec.baseline:,g}",
                f"> {b.advisory:,g}",
                f"{b.caution:,g}-{b.advisory:,g}",
                f"{b.warning:,g}-{b.caution:,g}",
                f"≤ {b.warning:,g}",
            ]
        )
    assert _rows(table) == expected


def _manual(model: str) -> str:
    return (manuals.MANUALS_DIR / manuals.MANUAL_FILES[model]).read_text(encoding="utf-8")


def _routed(system: str, model: str) -> set[str]:
    return {r.fault for spec in sensors_for(system, model) for r in spec.faults if r.weight > 0}


def test_every_generated_code_records_a_fault_its_system_routes_on_every_model() -> None:
    for code in FAULT_CODES:
        if code.generated:
            assert code.fault in CORRECTIVE_ACTIONS, code
            assert all(code.fault in _routed(code.system, m) for m in ENGINE_SPECS), code


def test_every_routed_fault_has_exactly_one_generated_code() -> None:
    routed = {
        (system, fault)
        for system in SYSTEM_SENSORS
        for model in ENGINE_SPECS
        for fault in _routed(system, model)
    }
    generated = [(c.system, c.fault) for c in FAULT_CODES if c.generated]

    assert sorted(generated) == sorted(routed)


def test_the_codes_are_unique_and_numbered_in_order_per_system() -> None:
    for system in SYSTEM_SENSORS:
        numbers = [int(c.code.rsplit("-", 1)[1]) for c in FAULT_CODES if c.system == system]
        assert numbers == list(range(1, len(numbers) + 1)), system


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_a_generated_code_carries_every_severity_worst_first(model: str) -> None:
    worst_first = tuple(SEVERITY_BY_LEVEL[level] for level in sorted(SEVERITY_BY_LEVEL)[::-1])
    for code in FAULT_CODES:
        severities = manuals.fault_code_severities(code, model)
        if code.generated:
            assert severities == worst_first, code
        else:
            assert severities == code.severities
            assert [s for s in worst_first if s in severities] == list(severities), code


def test_a_generated_code_without_a_route_raises() -> None:
    code = FaultCode("ENG-ELF-099", "Engine", "Electrical fault")

    with pytest.raises(ValueError, match="^fault code ENG-ELF-099: no Engine route raises"):
        manuals.fault_code_severities(code, MODEL)


@pytest.mark.parametrize(
    ("generated", "severities", "message"),
    [
        (True, ("MAJOR",), "a generated code takes its severities from the routes"),
        (False, (), "a manual-only code needs severities"),
    ],
)
def test_a_code_must_take_its_severities_from_one_place(
    generated: bool, severities: tuple[str, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=f"^fault code 'X-Y-001': {message}$"):
        FaultCode("X-Y-001", "Engine", "Leak", generated=generated, severities=severities)


_ABBREVIATIONS = {"CRITICAL": "CRIT", "MAJOR": "MAJ", "MINOR": "MIN"}
_FAULT_CODE_BLOCKS = {
    "Engine": "fault-codes-engine",
    "Avionics": "fault-codes-avionics",
    "Hydraulics": "fault-codes-hydraulics",
}


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_the_fault_code_tables_are_the_canonical_list(model: str) -> None:
    b737 = {}
    for system, block_id in _FAULT_CODE_BLOCKS.items():
        rows = _rows(manuals.RENDERERS[block_id](model, ENGINE_SPECS[model], {}))
        codes = [c for c in FAULT_CODES if c.system == system]
        assert [row[0] for row in rows] == [c.code for c in codes]
        assert [row[2] for row in rows] == [
            "/".join(_ABBREVIATIONS[s] for s in manuals.fault_code_severities(c, model))
            for c in codes
        ]
        reference = _rows(manuals.RENDERERS[block_id]("B737-800", ENGINE_SPECS["B737-800"], {}))
        b737.update({r[0]: r for r in reference})
        # Only the action may differ from the B737, and only where an override names
        # the model's own equipment.
        for row in rows:
            overridden = row[0] in manuals.MODEL_ACTIONS.get(model, {})
            assert row[:4] == b737[row[0]][:4]
            assert (row[4] != b737[row[0]][4]) is overridden, row


# A code-shaped token, loose enough to catch a variant of a code: any prefix,
# any case, a "-", "_", or en dash between segments, two to four digits, and an
# optional letter or "-<digits>" tail.
_CODE_TOKEN = re.compile(
    r"\b[A-Z]{2,5}[-_\u2013][A-Z]{2,6}[-_\u2013]\d{2,4}[A-Za-z]?(?:-\d+)?\b", re.IGNORECASE
)
# A task card shares the code shape. Its id is valid in the manual that
# defines it, so fault sections can refer to it.
_TASK_CARD = re.compile(r"^#### Task Card: (\S+)", re.MULTILINE)
# A part number shares it too. It is valid only in a part number field.
_PART_NUMBER_FIELD = re.compile(r"\(P/N: [^)\n]*\)|^\*\*Part Number:\*\* .*$", re.MULTILINE)


def _unknown_codes(text: str) -> list[str]:
    """Code-shaped tokens that are not a fault code, task card, or part number."""
    valid = {c.code for c in FAULT_CODES} | set(_TASK_CARD.findall(text))
    fields = [m.span() for m in _PART_NUMBER_FIELD.finditer(text)]
    return [
        m.group()
        for m in _CODE_TOKEN.finditer(text)
        if m.group() not in valid
        and not any(start <= m.start() and m.end() <= end for start, end in fields)
    ]


def test_the_code_check_flags_a_mistyped_code_but_not_a_part_number() -> None:
    text = (
        "Record ENG-OHV-006, not ENG-OVH-006. Order the computer (P/N: AVN-FMS-737-100).\n"
        "**Part Number:** HYD-PUMP-2901\n"
    )

    assert _unknown_codes(text) == ["ENG-OHV-006"]


@pytest.mark.parametrize(
    "token",
    [
        "ENG-OVH-06",
        "ENG-OVHEAT-006",
        "ENG-OVH-006a",
        "ENG-OVH-006-1",
        "ELEC-OVH-006",
        "GBX-CHP-001",
        "APU-OVH-001",
        "eng-ovh-006",
        "ENG\u2013OVH\u2013006",
        "ENG_OVH_006",
        "AVN-SDR-01",
    ],
)
def test_the_code_check_flags_a_variant_of_a_code(token: str) -> None:
    assert _unknown_codes(f"Record {token} in the log.") == [token]


def test_a_part_number_counts_only_in_a_part_number_field() -> None:
    assert _unknown_codes("Use the hand pump (P/N: HYD-TOOL-100).") == []
    assert _unknown_codes("Use HYD-TOOL-100 to bleed the system.") == ["HYD-TOOL-100"]


def test_a_task_card_counts_only_in_the_manual_that_defines_it() -> None:
    reference = "See task card ENG-TC-009 for the inspection.\n"
    card = "#### Task Card: ENG-TC-009 - Borescope Inspection\n"

    assert _unknown_codes(card + reference) == []
    assert _unknown_codes(reference) == ["ENG-TC-009"]


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_every_fault_code_in_a_manual_is_canonical(model: str) -> None:
    assert _unknown_codes(_manual(model)) == []


# Heading words -> the fault a troubleshooting section covers.
_SECTION_FAULTS = {
    "sensor drift": "sensor drift",
    "contamination": "contamination",
    "bearing wear": "bearing wear",
    "leak": "leak",
    "vibration": "vibration exceedance",
    "overheat": "overheat",
    "fuel starvation": "fuel starvation",
    "electrical fault": "electrical fault",
}
_SECTION_SYSTEMS = {"4": "Engine", "5": "Avionics", "6": "Hydraulics"}


@pytest.mark.parametrize(
    "line",
    [
        "**Fault Code:** ENG-OVH-006 (EGT)",
        "**Fault Codes:** ENG-OVH-006",
        "**Fault Code:** ENG-OVH-006 ",
        "**Fault Code:**ENG-OVH-006",
        "**Fault Code**: ENG-OVH-006",
        "- **Fault Code:** ENG-OVH-006",
        " **Fault Code:** ENG-OVH-006",
        "Fault Code: ENG-OVH-006",
        "**Fault Code :** ENG-OVH-006",
        "**FAULT_CODE:** ENG-OVH-006",
    ],
)
def test_a_fault_code_line_variant_fails_instead_of_vanishing(line: str) -> None:
    with pytest.raises(ValueError, match="not a plain Fault Code line"):
        fault_code_lines(f"### 4.1 Overheat\n{line}\n")


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_each_fault_code_line_is_the_code_of_its_sections_fault(model: str) -> None:
    lines = fault_code_lines(_manual(model))
    assert len(lines) >= 8
    for code, heading in lines:
        system = _SECTION_SYSTEMS[heading[0]]
        faults = [f for word, f in _SECTION_FAULTS.items() if word in heading.lower()]
        assert len(faults) == 1, heading
        expected = [
            c.code for c in FAULT_CODES if c.system == system and c.fault.lower() == faults[0]
        ]
        assert [code] == expected, heading


# Fault codes a manual covers although the generator never raises them.
_MANUAL_ONLY_SECTIONS = {"A321neo": {"ENG-ELF-008"}}


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_section_4_covers_every_engine_fault_once(model: str) -> None:
    codes = [code for code, heading in fault_code_lines(_manual(model)) if heading[0] == "4"]
    generated = {c.code for c in FAULT_CODES if c.system == "Engine" and c.generated}

    assert len(codes) == len(set(codes))
    assert set(codes) == generated | _MANUAL_ONLY_SECTIONS.get(model, set())


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_a_severity_line_lists_the_severities_of_its_code(model: str) -> None:
    by_code = {c.code: c for c in FAULT_CODES}
    pairs = re.findall(
        r"^\*\*Fault Code:\*\* (\S+)\n\*\*Severity Classification:\*\* (.+)$",
        _manual(model),
        re.M,
    )

    assert pairs
    for code, line in pairs:
        expected = " / ".join(manuals.fault_code_severities(by_code[code], model))
        assert line == expected or line.startswith(f"{expected} ("), (code, line)


# A gearbox code. The A220's gearbox findings are recorded under the engine
# codes, so no manual names one. The gearbox CAS messages, such as
# "GBX CHIP DET", are cockpit text and stay.
_GBX_CODE = re.compile(r"\bGBX-[A-Z0-9]")


def test_the_gearbox_check_flags_a_code_but_not_a_cas_message() -> None:
    text = "GBX CHIP DET and GBX OIL PRESS show on EICAS. See GBX-TC-001 and ENG-TC-002."

    assert _GBX_CODE.findall(text) == ["GBX-T"]


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_no_manual_names_a_gearbox_code(model: str) -> None:
    assert re.findall(r"^.*\bGBX-[A-Z0-9].*$", _manual(model), re.M) == []


@pytest.mark.parametrize("model", sorted(ENGINE_SPECS))
def test_chapters_1_and_3_share_the_numbering_of_every_manual(model: str) -> None:
    text = _manual(model)

    assert re.search(r"^### 1\.2 Fleet Configuration$", text, re.M)
    assert re.search(r"^### 3\.2 Component Descriptions$", text, re.M)


@pytest.mark.parametrize("model", sorted(manuals.MANUAL_FILES))
def test_no_manual_uses_piston_mixture_terms(model: str) -> None:
    # A turbofan has no mixture control, so "lean mixture" is piston wording.
    text = (manuals.MANUALS_DIR / manuals.MANUAL_FILES[model]).read_text(encoding="utf-8")

    assert not re.findall(r".*\bmixture\b.*", text, re.IGNORECASE)


def test_the_e190_manual_names_its_engine_one_way() -> None:
    text = (manuals.MANUALS_DIR / manuals.MANUAL_FILES["E190"]).read_text(encoding="utf-8")
    prose = _PART_NUMBER_FIELD.sub("", text)

    assert set(re.findall(r"\bCF34-[\w-]+", prose)) == {ENGINE_SPECS["E190"].engine_type}
