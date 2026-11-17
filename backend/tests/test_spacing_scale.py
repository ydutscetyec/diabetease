"""Keep every gap in the app on one scale.

Before this, 324 spacing declarations used 26 different pixel values -- 2, 3, 4,
5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 22, 24, 26, 28, 32, 36 --
plus seven `em`-based margins that produced fractional gaps like 5.6px and
22.2px depending on the font size of whatever carried them, and 36 inline
`style="margin-top: ..."` attributes in index.html that the stylesheet could not
reach at all. Nothing lined up with anything, which is what reads as untidy
space between components.

Measured in a browser afterwards, the whole app uses six gaps: 0, 2, 8, 12, 16
and 24px, every one of them a step on the scale, in a deliberate three tiers --
12px inside a card, 16px between cards and grids, 24px between sections.

These tests hold that. They do not check the rendered geometry, which needs a
browser; they check that nobody can reintroduce a one-off value.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "frontend"
CSS = (ROOT / "assets" / "styles.css").read_text()
HTML = (ROOT / "index.html").read_text()

NO_COMMENTS = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), CSS, flags=re.S)

SPACING_PROPS = (
    r"margin|padding|gap|row-gap|column-gap"
    r"|margin-(?:top|bottom|left|right|block|inline)"
    r"|padding-(?:top|bottom|left|right|block|inline)"
)

# Values a spacing declaration may hold as a literal rather than a scale token.
#   0 / 0px  no space at all is not a step on a scale
#   1px      a hairline, used where a border and a padding have to agree
#   100px    the footer run-out under .work, a size rather than a gap
#   negative a deliberate optical pull, e.g. a sticky bar bleeding past a card
LITERAL_OK = {"0", "0px", "1px", "100px", "auto", "inherit", "initial", "unset"}


def _spacing_declarations():
    """(selector, property, value) for every spacing declaration in the sheet."""
    out = []
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", NO_COMMENTS):
        prelude = rule.group(1).strip().split("}")[-1].strip()
        if prelude.startswith("@"):
            continue
        for decl in rule.group(2).split(";"):
            m = re.match(rf"\s*({SPACING_PROPS})\s*:\s*(.+)", decl, re.S)
            if m:
                out.append((prelude, m.group(1), m.group(2).strip()))
    return out


def test_the_scale_is_declared_once():
    root = re.search(r"^:root\{(.*?)^\}", NO_COMMENTS, re.S | re.M).group(1)
    steps = dict(re.findall(r"(--s-\d+)\s*:\s*(\d+)px", root))
    assert steps, "no spacing scale in :root"
    values = sorted(int(v) for v in steps.values())
    assert values == sorted(set(values)), f"two steps share a value: {values}"
    assert values[0] >= 2, "a step below 2px is not a gap anyone can see"
    assert len(values) <= 10, (
        f"{len(values)} steps is not a scale, it is the old mess with new names: {values}")
    # every step a multiple of 2, so halves never appear
    odd = [v for v in values if v % 2]
    assert not odd, f"odd-numbered steps break alignment with everything else: {odd}"


@pytest.mark.parametrize("sel,prop,val", _spacing_declarations())
def test_spacing_uses_the_scale(sel, prop, val):
    """No raw pixel spacing outside the handful of documented literals."""
    if "calc(" in val or "env(" in val:
        return                                  # safe-area insets, checked by eye
    for tok in re.findall(r"-?\d+(?:\.\d+)?(?:px|rem|em)?", val):
        if tok in LITERAL_OK or tok.startswith("-"):
            continue
        if re.fullmatch(r"0(?:px)?", tok):
            continue
        pytest.fail(
            f"{sel} {{ {prop}: {val} }} uses the literal {tok}. Spacing comes from "
            f"the scale -- var(--s-1) .. var(--s-8) -- so that one component "
            f"cannot drift 2px away from every other one."
        )


def test_no_em_based_spacing():
    """An em margin is a different gap on every font size that carries it.

    `h1,h2,h3,h4 { margin: 0 0 .35em }` and `p { margin: 0 0 .9em }` were
    producing 5.6px, 13.5px and 22.2px gaps in different cards from the same two
    rules, which is unfixable by picking a better number.
    """
    bad = [f"{sel} {{ {prop}: {val} }}"
           for sel, prop, val in _spacing_declarations()
           if re.search(r"\d\s*(?:em|rem)\b", val)]
    assert not bad, "spacing in em/rem scales with font size:\n  " + "\n  ".join(bad)


def test_no_inline_spacing_in_the_markup():
    """36 of these made the spacing unreachable from the stylesheet."""
    found = re.findall(r'style="[^"]*(?:margin|padding|gap)[^"]*"', HTML)
    assert not found, (
        "inline spacing in index.html cannot be changed from the stylesheet, so "
        "it drifts:\n  " + "\n  ".join(found)
        + "\nUse a component class, or let the flow rule space it.")


def test_a_container_that_sets_a_gap_does_not_also_margin_its_children():
    """Paying twice.

    `.grid` set `gap:16px` while `.card + .card` added `margin-top:16px`, so
    cards in a grid asking for 16px of space got 32. The grid exception has to
    stay for as long as both rules exist.
    """
    assert re.search(r"\.grid\s*>\s*\.card\s*\+\s*\.card\s*\{[^}]*margin-top\s*:\s*0",
                     NO_COMMENTS), (
        "the rule that stops a grid's cards being charged twice is gone; cards "
        "in a grid will get the grid's gap plus .card + .card's margin")


def test_the_flow_rule_outranks_element_margins():
    """Specificity, not wishful thinking.

    Written as `:where(.card) > :where(* + *)` this rule carries zero
    specificity, and the bare `p` rule's own `margin-top:0` beat it at (0,0,1) --
    so paragraphs inside a card sat flush against one another with no gap at all.
    """
    m = re.search(r"(\S*\.card\S*)\s*>\s*(\S+)\s*\+\s*(\S+)\s*\{[^}]*margin-top", NO_COMMENTS)
    assert m, "no flow rule spacing the children of a card"
    assert ":where" not in m.group(0), (
        "the card flow rule must not be wrapped in :where(): at zero specificity "
        "the plain `p` rule outranks it and paragraphs lose their spacing")
