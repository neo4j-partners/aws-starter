"""Tests for the evidence panel's two views in the fleet UI's ``ui/static/index.html``."""

from html.parser import HTMLParser
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).resolve().parents[2] / "ui" / "static" / "index.html"
GRAPH_IDS = {"canvas", "graph-empty", "node-details"}
MEMORY_IDS = {"memory-note", "memory-entries"}


class ViewParser(HTMLParser):
    """Collect the tabs, the tab panels, and the IDs inside each panel."""

    def __init__(self) -> None:
        super().__init__()
        self.tabs: list[dict[str, str | None]] = []
        self.panels: dict[str, dict[str, str | None]] = {}
        self.inside: dict[str, set[str]] = {}
        self._open: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("role") == "tab":
            self.tabs.append(attributes)
        if attributes.get("role") == "tabpanel" and (panel_id := attributes.get("id")):
            self.panels[panel_id] = attributes
            self.inside[panel_id] = set()
        for _, panel_id in self._open:
            if panel_id is not None and (element_id := attributes.get("id")):
                self.inside[panel_id].add(element_id)
        if tag not in {"br", "img", "input", "meta", "link"}:
            role_panel = attributes.get("id") if attributes.get("role") == "tabpanel" else None
            self._open.append((tag, role_panel))

    def handle_endtag(self, tag: str) -> None:
        while self._open:
            opened, _ = self._open.pop()
            if opened == tag:
                break


@pytest.fixture(scope="module")
def page() -> ViewParser:
    parser = ViewParser()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    return parser


def test_there_are_two_views_current_evidence_then_memory(page: ViewParser) -> None:
    assert [tab["id"] for tab in page.tabs] == ["evidence-tab", "memory-tab"]
    assert [tab["aria-controls"] for tab in page.tabs] == ["evidence-view", "memory-view"]


def test_each_tab_and_panel_name_each_other(page: ViewParser) -> None:
    for tab in page.tabs:
        panel = page.panels[tab["aria-controls"] or ""]
        assert panel["aria-labelledby"] == tab["id"]
        assert tab.get("type") == "button"


def test_the_evidence_view_starts_selected_and_the_memory_view_inert(page: ViewParser) -> None:
    evidence, memory = page.tabs
    assert evidence["aria-selected"] == "true"
    assert memory["aria-selected"] == "false"
    assert memory["tabindex"] == "-1"
    assert "inert" not in page.panels["evidence-view"]
    assert "inert" in page.panels["memory-view"]


def test_the_graph_and_the_memory_list_live_in_their_own_views(page: ViewParser) -> None:
    assert page.inside["evidence-view"] >= GRAPH_IDS
    assert page.inside["memory-view"] >= MEMORY_IDS
    assert not page.inside["evidence-view"] & MEMORY_IDS
    assert not page.inside["memory-view"] & GRAPH_IDS
