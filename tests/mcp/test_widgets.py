"""The four MCP Apps widgets: self-contained, small, and their fixtures carry a gap.

A widget makes no outbound request to any host other than the bridge: no `http(s)://`
inside a `src`, `href`, `url(`, `fetch(` or `import(`; the only network is the host's
postMessage bridge. The fixture of every widget holds at least one `not_reviewed` field
(the empty state is designed before the happy path)."""

import json
import re
from pathlib import Path

import pytest

# The repository root's mcp/widgets (not a folder under tests/).
ROOT = Path(__file__).resolve().parents[2]
WIDGETS = ROOT / "mcp" / "widgets"
NAMES = ("tender_card", "financial_model", "changes_view", "comparison_table")
OUTBOUND = re.compile(
    r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//|url\(\s*["']?\s*(?:https?:)?//|fetch\(|import\(|"""
    r"""new\s+XMLHttpRequest|XMLHttpRequest|navigator\.sendBeacon|new\s+WebSocket|new\s+EventSource|"""
    r"""new\s+Image\(|<link\b|@import|image_url|render_url""",
    re.IGNORECASE,
)


def test_the_widgets_live_at_the_repository_root() -> None:
    assert (ROOT / "pyproject.toml").is_file() and WIDGETS.parent.name == "mcp"
    assert WIDGETS == ROOT / "mcp" / "widgets" and "tests" not in WIDGETS.parts
    for name in NAMES:
        assert (WIDGETS / f"{name}.html").is_file(), name
        assert (WIDGETS / "fixtures" / f"{name}.json").is_file(), name


@pytest.mark.parametrize("name", NAMES)
def test_a_widget_is_one_self_contained_file_under_200_kb(name: str) -> None:
    html = (WIDGETS / f"{name}.html").read_text(encoding="utf-8")
    # Page images arrive inside the bridge result as a data: URL; an <img> is bound to
    # nothing else, and nothing is fetched.
    assert "image_data_url" in html
    for src in re.findall(r"""<img[^>]*\ssrc\s*=\s*["']([^"']*)""", html):
        assert src.startswith("data:"), src
    assert re.search(r"""\{\s*src:(?!\s*sc\.image_data_url)""", html) is None
    assert len(html.encode("utf-8")) < 200 * 1024
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "profile=mcp-app" in html, "the resource names its MIME profile"
    assert OUTBOUND.search(html) is None, OUTBOUND.search(html)
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", ""), "no host but the bridge"
    assert "https://" not in html
    assert "ui/initialize" in html and "postMessage" in html, "the bridge handshake"
    assert "The tender document is the authoritative source" in html
    assert "prefers-color-scheme" in html, "light and dark themes"
    assert "min-height:44px" in html.replace(" ", ""), "touch targets"


def _not_reviewed(obj: object) -> int:
    if isinstance(obj, dict):
        hit = 1 if obj.get("status") == "not_reviewed" else 0
        return hit + sum(_not_reviewed(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_not_reviewed(v) for v in obj)
    return 0


@pytest.mark.parametrize("name", NAMES)
def test_every_fixture_holds_its_designed_gap(name: str) -> None:
    """A tender card and a comparison carry a `not_reviewed` field; the model a fixed
    parameter the reading does not hold; a changelog has no fields — its gap is a pending
    (unreviewed) version, listed by path only."""
    fixture = json.loads((WIDGETS / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
    if name == "financial_model":
        # The model's gap: a fixed parameter the reviewed reading does not hold.
        assert any(f["status"] == "not_reviewed" and f["gap_reason"] for f in fixture["fixed"])
    elif name == "changes_view":
        # The changelog's gap: an unreviewed version, its fields listed by path only.
        assert any(not v["reviewed"] and v["pending"] for v in fixture["versions"])
    else:
        assert _not_reviewed(fixture) >= 1
    if name == "financial_model":
        assert fixture["note"].startswith("indicative")
    else:
        assert fixture.get("authority_note") or fixture.get("columns")
