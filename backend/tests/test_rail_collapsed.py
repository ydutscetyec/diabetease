"""Guard the collapsed sidebar against prose that will not fit in 72px.

Expanded, the rail is 264px wide. Collapsed, it is 72px, of which 48px is
usable after .rail-scroll's padding. Any child holding words rather than a
single icon has to be handled explicitly at that width, and when it is not the
text either clips or runs out past the edge of the rail -- which is exactly
what shipped: the account name and chevron reached x=109 in a 72px rail, and
the "Your health, your pace." card was squeezed into a 21px column.

Nothing in the suite caught that, because the CSS cascade was correct. Each
declaration had the winning value it was supposed to have; the fault was a
missing rule, not a wrong one, and a test that compares computed values cannot
see a rule that was never written.

So this test works from the markup instead. Every direct child of .rail is
listed below with what the collapsed state must do to it. A new child fails the
test until someone adds it to the list, which forces the decision to be made
rather than discovered on the live site.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "frontend"
CSS = (ROOT / "assets" / "styles.css").read_text()
HTML = (ROOT / "index.html").read_text()

# class on a direct child of .rail -> how the collapsed rail must treat it.
#   "icon"   icon-only already; no text to shrink, nothing required
#   "hidden" must be hidden outright when collapsed
#   "detext" stays, but its text-bearing parts must be hidden
RAIL_CHILDREN = {
    "rail-brand": "detext",     # keeps the mark, drops the wordmark
    "rail-scroll": "icon",      # nav links; .lbl is hidden by its own rule
    "rail-note": "hidden",
    "rail-bottom": "hidden",
    "rail-account": "detext",   # keeps the avatar, drops name/sub/chevron
    "rail-foot": "icon",        # the collapse toggle; its span is hidden
}


def _rail_block() -> str:
    """The markup between <aside class="rail"> and its close."""
    start = re.search(r'<(aside|div|nav)[^>]*class="[^"]*\brail\b[^"]*"', HTML)
    assert start, "no .rail element in index.html"
    tag = start.group(1)
    depth, i = 0, start.start()
    for m in re.finditer(rf"</?{tag}\b", HTML[start.start():]):
        depth += 1 if m.group(0)[1] != "/" else -1
        if depth == 0:
            i = start.start() + m.end()
            break
    return HTML[start.start():i]


def _direct_children() -> set[str]:
    block = _rail_block()
    body = block[block.index(">") + 1:]
    out, depth = set(), 0
    for m in re.finditer(r"<(/?)(\w+)([^>]*)>", body):
        closing, tag, attrs = m.group(1), m.group(2), m.group(3)
        if tag in {"br", "img", "input", "path", "circle", "line", "rect", "polyline"}:
            continue
        if not closing:
            if depth == 0:
                cls = re.search(r'class="([^"]*)"', attrs)
                if cls:
                    out |= {c for c in cls.group(1).split() if c.startswith("rail")}
            if not attrs.rstrip().endswith("/"):
                depth += 1
        else:
            depth -= 1
    return out


def _collapsed_rules(selector_part: str) -> list[str]:
    """Collapsed-state rules whose prelude mentions selector_part."""
    return [
        m.group(0)
        for m in re.finditer(r"[^{}]*\{[^{}]*\}", CSS)
        if 'data-rail="collapsed"' in m.group(0)
        and selector_part in m.group(0).split("{")[0]
    ]


def test_every_rail_child_is_accounted_for():
    """A new direct child of .rail has to declare what 72px does to it."""
    found = _direct_children()
    assert found, "parsed no .rail children -- the parser is broken, not the CSS"
    unlisted = found - set(RAIL_CHILDREN)
    assert not unlisted, (
        f"these .rail children have no collapsed-state decision: {sorted(unlisted)}. "
        f"Add each to RAIL_CHILDREN as icon/hidden/detext and write the rule."
    )


@pytest.mark.parametrize(
    "cls", [c for c, kind in RAIL_CHILDREN.items() if kind in ("hidden", "detext")]
)
def test_text_bearing_rail_children_have_a_collapsed_rule(cls):
    rules = _collapsed_rules(f".{cls}")
    assert rules, (
        f".{cls} holds text but no rule hides or shrinks it when the rail is "
        f"collapsed, so it will clip or overflow the 72px rail."
    )
    assert any("display:none" in r.replace(" ", "") for r in rules), (
        f"no collapsed rule for .{cls} hides anything; found {len(rules)} rule(s) "
        f"but none with display:none"
    )


@pytest.mark.parametrize("cls", [c for c, k in RAIL_CHILDREN.items() if k == "hidden"])
def test_hidden_children_come_back_on_mobile(cls):
    """Below 1024px the rail is a full-width drawer, so the text must return.

    Two ways to get this right: scope the hiding rule to a min-width query, or
    undo it in the max-width:1023px block. Either passes; neither fails open.
    """
    scoped = re.search(
        r"@media\s*\(min-width:\s*1024px\)\s*\{(?:[^{}]|\{[^{}]*\})*?"
        + re.escape(f".{cls}") + r"(?:[^{}]|\{[^{}]*\})*?\}",
        CSS,
    )
    undone = re.search(
        r"@media\s*\(max-width:\s*1023px\)\s*\{(?:[^{}]|\{[^{}]*\})*?"
        + re.escape(f".{cls}") + r"\s*\{[^{}]*display\s*:\s*(block|flex|grid)",
        CSS,
    )
    assert scoped or undone, (
        f".{cls} is hidden when collapsed but nothing brings it back below "
        f"1024px, where the rail is a full-width drawer and has room for it."
    )


def test_group_headings_are_not_clipped_when_collapsed():
    """"Assessment" needs 61px; the collapsed box is 47px.

    Shrinking the font was not enough -- it still clipped. The heading has to be
    taken out of the flow, and it has to stay readable by screen readers, since
    it is what names each group of icons.
    """
    rules = _collapsed_rules(".rail-group > h4")
    assert rules, "no collapsed rule for the rail group headings"
    joined = "".join(rules).replace(" ", "")
    assert "clip-path:inset(50%)" in joined or "clip:rect" in joined, (
        "collapsed group headings must be visually hidden (clip-path), not "
        "merely shrunk -- a smaller font still clipped at 47px"
    )
    assert "display:none" not in joined, (
        "do not display:none the group headings -- that removes them from the "
        "accessibility tree, and they are what label each group of icons"
    )
