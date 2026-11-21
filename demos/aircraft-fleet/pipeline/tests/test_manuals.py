"""Generated blocks in the maintenance manuals are rendered from specs.

A block sits between two marker lines. Rendering replaces what is between
them and leaves every other line as it was.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from generator import main as generator_main
from generator import manuals
from generator.manuals import ManualBlockError, render_text
from generator.specs import ENGINE_SPECS
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
