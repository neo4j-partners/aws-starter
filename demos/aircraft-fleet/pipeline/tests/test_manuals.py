"""Generated blocks in the maintenance manuals are rendered from specs.

A block sits between two marker lines. Rendering replaces what is between
them and leaves every other line as it was.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from generator import main as generator_main
from generator import manuals
from generator.config import GeneratorConfig
from generator.fleet import generate_fleet
from generator.maintenance import SEVERITY_BY_LEVEL
from generator.manuals import ManualBlockError, render_text
from generator.specs import (
    COMPONENT_ALIASES,
    ENGINE_SPECS,
    MANUAL_FLEET_TAILS,
    SYSTEM_SENSORS,
    VIBRATION_LEVELS,
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
    ],
)
def test_bad_markers_raise_with_the_line(text: str, message: str) -> None:
    with pytest.raises(ManualBlockError, match=f"^{message}$"):
        _render(text)


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
    monkeypatch.setattr(manuals, "load_stats", dict)
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
def test_only_generated_blocks_quote_vibration_numbers_in_sections_4_and_8(model: str) -> None:
    # Hand-written text names a level instead, so the numbers live in one place.
    text = (manuals.MANUALS_DIR / manuals.MANUAL_FILES[model]).read_text(encoding="utf-8")
    sections = re.findall(r"^## [48]\. .*?(?=^## \d)", _BLOCK.sub("", text), re.M | re.S)

    assert len(sections) == 2
    assert [line for s in sections for line in re.findall(r"^.*\d ips.*$", s, re.M)] == []
