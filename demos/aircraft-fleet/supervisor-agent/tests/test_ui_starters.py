"""Tests for the starter questions in the fleet UI's ``ui/static/index.html``."""

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).resolve().parents[2] / "ui" / "static" / "index.html"
HYDRAULIC_LABEL = "Find aircraft with hydraulic system issues"
HYDRAULIC_PROMPT = (
    "Find aircraft with hydraulic system issues. Show up to five maintenance events with"
    " their event IDs, aircraft tail numbers, faults, and corrective actions. Include the"
    " event IDs in the graph query results."
)


@dataclass
class Starter:
    label: str
    prompt: str


class StarterParser(HTMLParser):
    """Collect the starter select's options and the label that names it."""

    def __init__(self) -> None:
        super().__init__()
        self.starters: list[Starter] = []
        self.label_for: list[str] = []
        self.send_button: dict[str, str | None] = {}
        self._in_select = False
        self._option: Starter | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "select" and attributes.get("id") == "starter":
            self._in_select = True
        elif tag == "option" and self._in_select:
            self._option = Starter(label="", prompt=attributes.get("value") or "")
        elif tag == "label" and attributes.get("for"):
            self.label_for.append(attributes["for"])
        elif tag == "button" and attributes.get("id") == "starter-send":
            self.send_button = attributes

    def handle_data(self, data: str) -> None:
        if self._option is not None:
            self._option.label += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._option is not None:
            self.starters.append(Starter(self._option.label.strip(), self._option.prompt))
            self._option = None
        elif tag == "select":
            self._in_select = False


@pytest.fixture(scope="module")
def page() -> StarterParser:
    parser = StarterParser()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    return parser


def test_the_hydraulic_question_comes_first_with_its_full_prompt(page: StarterParser) -> None:
    assert page.starters[0] == Starter(HYDRAULIC_LABEL, HYDRAULIC_PROMPT)


def test_the_list_holds_six_distinct_starters(page: StarterParser) -> None:
    labels = [starter.label for starter in page.starters]
    prompts = [starter.prompt for starter in page.starters]

    assert len(page.starters) == 6
    assert len(set(labels)) == len(labels)
    assert len(set(prompts)) == len(prompts)


def test_every_prompt_asks_for_ids_in_the_graph_query_results(page: StarterParser) -> None:
    for starter in page.starters:
        assert starter.label
        assert "IDs" in starter.prompt, starter.label
        assert starter.prompt.endswith("in the graph query results."), starter.label


def test_the_dropdown_has_a_label_and_a_submit_button(page: StarterParser) -> None:
    assert "starter" in page.label_for
    assert page.send_button.get("type") == "submit"
