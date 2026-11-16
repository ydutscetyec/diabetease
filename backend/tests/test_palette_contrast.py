"""Measure the palette's contrast, in both themes, from the stylesheet itself.

This exists because the failure it guards against is silent. The previous
palette looked fine in light mode and left 26 pieces of text below 1.5:1 in dark
mode -- including the emergency-care heading at 1.11:1 -- and nothing in the
suite noticed, because a colour is only wrong in combination with another
colour and no test was looking at pairs.

The numbers come from parsing the :root blocks in styles.css, so the test reads
what ships rather than a copy of it. WCAG 2.1: 4.5:1 for body text, 3:1 for
large text and for the boundary of anything a person operates.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parents[2] / "frontend" / "assets" / "styles.css").read_text()

TEXT, LARGE, UI = 4.5, 3.0, 3.0


def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hx: str) -> float:
    hx = hx.lstrip("#")
    if len(hx) == 3:
        hx = "".join(ch * 2 for ch in hx)
    r, g, b = (int(hx[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _tokens(selector: str) -> dict[str, str]:
    """Colour custom properties declared in one :root block."""
    i = CSS.index(selector + "{")
    depth, j = 0, i
    while j < len(CSS):
        if CSS[j] == "{":
            depth += 1
        elif CSS[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    body = re.sub(r"/\*.*?\*/", "", CSS[i:j], flags=re.S)
    return {m.group(1): m.group(2).upper()
            for m in re.finditer(r"--([a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{3,8})\s*;", body)}


LIGHT = _tokens(":root")
DARK = dict(LIGHT)
DARK.update(_tokens(':root[data-theme="dark"]'))
AUTO = dict(LIGHT)
AUTO.update(_tokens(':root[data-theme="auto"]'))

# Every pairing the stylesheet actually produces. A pair that is not here is not
# protected, so a new combination in the CSS belongs here too.
PAIRINGS = [
    ("text", "bg", TEXT, "body text on the page"),
    ("text", "card", TEXT, "body text on a card"),
    ("text-2", "bg", TEXT, "secondary text on the page"),
    ("text-2", "card", TEXT, "secondary text on a card"),
    ("head", "bg", LARGE, "heading on the page"),
    ("head", "card", LARGE, "heading on a card"),
    ("green-ink", "card", TEXT, "link on a card"),
    ("green-ink", "bg", TEXT, "link on the page"),
    ("on-primary", "green", TEXT, "label on a filled primary button"),
    ("on-primary", "green-ink", TEXT, "label on a primary button, hovered"),
    ("ok-ink", "ok-bg", TEXT, "verified chip"),
    ("ok-ink", "green-wash", TEXT, "text on the mint wash"),
    ("warn-ink", "warn-bg", TEXT, "unconfirmed chip"),
    ("danger-ink", "danger-bg", TEXT, "emergency banner"),
    ("info-ink", "info-bg", TEXT, "neutral note"),
    ("rail-text", "rail-bg", TEXT, "sidebar item"),
    ("rail-dim", "rail-bg", TEXT, "sidebar group label and banner eyebrow"),
    # Four tone fills, matching the four tile classes the product renders.
    # There is no fifth: a palette that documents a colour nothing uses is a
    # palette that lies a little.
    ("pink-ink", "pink", TEXT, "text on a bubblegum fill"),
    ("mint-ink", "mint", TEXT, "text on a mint fill"),
    ("sky-ink", "sky", TEXT, "text on a candy-blue fill"),
    ("lavender-ink", "lavender", TEXT, "text on a grape fill"),
    ("line-strong", "card", UI, "input border on a card"),
    ("line-strong", "bg", UI, "input border on the page"),
    ("ok-line", "card", UI, "verified chip border and progress fill"),
    ("ok-line", "bg", UI, "progress fill on the page"),
    ("warn-line", "card", UI, "unconfirmed border"),
    ("danger-line", "card", UI, "emergency border"),
    ("info-line", "card", UI, "neutral border"),
    ("focus", "bg", UI, "focus ring on the page"),
    ("focus", "card", UI, "focus ring on a card"),
]

THEMES = [("light", LIGHT), ("dark", DARK), ("auto", AUTO)]


@pytest.mark.parametrize("theme,pal", THEMES)
@pytest.mark.parametrize("ink,surface,need,what", PAIRINGS)
def test_pairing_meets_its_threshold(theme, pal, ink, surface, need, what):
    assert ink in pal, f"{ink} is not declared in the {theme} palette"
    assert surface in pal, f"{surface} is not declared in the {theme} palette"
    got = ratio(pal[ink], pal[surface])
    assert got >= need, (
        f"{theme}: {what} -- {ink} ({pal[ink]}) on {surface} ({pal[surface]}) "
        f"is {got:.2f}:1, needs {need}:1"
    )


@pytest.mark.parametrize("theme,pal", THEMES)
def test_the_three_statuses_differ_in_lightness_not_only_hue(theme, pal):
    """Verified, unconfirmed and outdated sit side by side on the map, so they
    have to be distinguishable without colour vision. The palette this replaced
    gave 1.01 between verified and unconfirmed -- no difference at all.

    Light reaches 1.5. Dark is held to 1.35 and the reason is arithmetic: each
    status must also clear 3:1 against the dark card, which puts a floor under
    the dimmest, and the brightest pink puts a ceiling over the top; the usable
    band spans about 2.1x while three rungs 1.5x apart need 2.25x. Forcing it
    produces mud. The gap is only acceptable because status is never carried by
    colour alone -- every marker has its own shape and glyph, every chip its own
    words -- and those are enforced elsewhere in this suite.
    """
    need = 1.5 if theme == "light" else 1.35
    for a, b in (("ok-line", "warn-line"), ("warn-line", "danger-line"),
                 ("ok-line", "danger-line")):
        got = ratio(pal[a], pal[b])
        assert got >= need, (
            f"{theme}: {a} and {b} differ by only {got:.2f}, under {need}")


@pytest.mark.parametrize("theme,pal", THEMES)
def test_the_sidebar_stays_dark_in_every_theme(theme, pal):
    """A deliberate decision, not an oversight: the sidebar is dark in both
    themes so the workspace is the brightest thing on screen. If it ever
    follows the theme, the text tokens written for a dark ground stop working.
    """
    assert _lum(pal["rail-bg"]) < 0.15, f"{theme}: rail-bg is no longer dark"
    assert ratio(pal["rail-text"], pal["rail-bg"]) >= TEXT


def test_dark_and_auto_declare_the_same_values():
    """"Dark" and "match my device" must not drift apart; one is the explicit
    choice and the other the same thing from a media query.
    """
    explicit = _tokens(':root[data-theme="dark"]')
    auto = _tokens(':root[data-theme="auto"]')
    assert explicit == auto, f"differs: {set(explicit.items()) ^ set(auto.items())}"


def test_no_rule_outside_print_hardcodes_a_colour():
    """The failure this whole file exists for: a literal hex in a rule has
    silently opted out of the dark theme. Print is the one exception, because
    paper is white whatever the screen says.
    """
    body = CSS[CSS.index("h1,h2,h3"):]          # past the :root blocks
    offenders = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("/*") or stripped.startswith("*"):
            continue
        if re.search(r"#[0-9A-Fa-f]{3,6}\b", re.sub(r"rgba?\([^)]*\)", "", line)):
            offenders.append(stripped)
    allowed = {
        "body{background:#fff}",
        ".card{box-shadow:none; border:1px solid #999; break-inside:avoid}",
        "display:block; margin-top:16px; padding-top:10px; "
        "border-top:1px solid #000; font-size:10pt;",
    }
    unexpected = [o for o in offenders if o not in allowed]
    assert not unexpected, f"hard-coded colours outside print: {unexpected}"
