"""The page markup and the script must agree.

Twice an edit to index.html removed elements the script depends on: once a
settings card that was never written, once a pattern that deleted the sidebar.
Neither raised an error anywhere. These checks make that a failing test.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
HTML = (FRONTEND / "index.html").read_text(encoding="utf-8")
JS = (FRONTEND / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (FRONTEND / "assets" / "styles.css").read_text(encoding="utf-8")

VOID = {"meta", "link", "br", "img", "input", "hr", "path", "rect", "circle",
        "ellipse", "source", "line", "polyline", "polygon"}


def test_every_element_the_script_looks_up_exists():
    in_html = set(re.findall(r'id="([^"]+)"', HTML))
    in_js = set(re.findall(r'\$\("([^"]+)"\)', JS))
    assert not (in_js - in_html), f"script references missing elements: {sorted(in_js - in_html)}"


def test_no_duplicate_ids():
    ids = re.findall(r'id="([^"]+)"', HTML)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate ids: {dupes}"


def test_every_routed_view_has_a_section():
    m = re.search(r"var VIEW_IDS = \[(.*?)\];", JS, re.S)
    assert m, "VIEW_IDS not found"
    for view in re.findall(r'"([a-z]+)"', m.group(1)):
        assert f'id="v-{view}"' in HTML, f"no section for view '{view}'"


def test_shell_landmarks_are_present():
    for needed in ('id="rail"', 'id="railNav"', 'id="main"', 'id="chatPanel"',
                   'id="chatFab"', 'id="boot"', 'id="leafmap"'):
        assert needed in HTML, f"missing {needed}"


def test_tags_balance():
    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.bad = [], []

        def handle_starttag(self, tag, attrs):
            if tag not in VOID:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()
            elif tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.bad.append(self.stack.pop())
                self.stack.pop()

    p = P()
    p.feed(HTML)
    assert not p.bad and not p.stack, f"unbalanced: {p.bad or p.stack}"


def test_referenced_assets_exist():
    for ref in set(re.findall(r'(?:src|href)="(/assets/[^"]+|/manifest\.webmanifest)"', HTML)):
        assert (FRONTEND / ref.lstrip("/")).is_file(), f"missing file {ref}"


def test_no_blocked_or_keyed_tile_hosts():
    """OSM's own servers refuse this kind of app and CARTO watermarks its tiles;
    neither may lead the provider list again."""
    first = re.search(r"var TILE_PROVIDERS = \[\s*\{(.*?)\}", JS, re.S).group(1)
    assert "cartocdn" not in JS
    assert "tile.openstreetmap.org" not in first


def test_css_braces_balance():
    assert CSS.count("{") == CSS.count("}")


def test_guide_page_is_routed_and_present():
    """A new section is only reachable if the nav, VIEW_IDS and CRUMBS all know
    about it. Each has been forgotten separately before."""
    assert 'id="v-guide"' in HTML
    assert '{ id: "guide", label: "User guide"' in JS
    assert '"guide"' in re.search(r"var VIEW_IDS = \[(.*?)\];", JS, re.S).group(1)
    assert 'guide: "User guide"' in JS


def test_guide_does_not_contradict_the_assessment_tiers():
    """The guide once showed 'Follow-up' with the success colour, implying an
    all-clear. Every tier it lists must appear with a non-success tag."""
    guide = HTML.split('id="v-guide"')[1].split("</section>")[0]
    assert "Not an all-clear" in guide
    for phrase in ("Emergency", "See a doctor promptly", "Worth getting tested"):
        assert phrase in guide, phrase
    assert 'tag tag-ok">Worth' not in guide


def test_voice_never_prefers_a_male_voice_over_a_female_one():
    """The quality bonus (+20) once outranked the gender penalty (-15), so a
    male 'Natural' voice beat a female local one."""
    block = re.search(r"var Voice = \{.*?\n  \};", JS, re.S).group(0)
    assert "!male && /natural|premium|online|enhanced|neural/i" in block
    assert "andrew" in block, "the Windows 'Andrew' voice must be in the male list"
    assert "notMale.length ? notMale[0] : scored[0]" in block


# ------------------------------------------------- accessibility of markers
def test_marker_status_is_not_carried_by_colour_alone():
    """Verified vs unconfirmed is the difference between 'someone phoned and
    confirmed this clinic does the test' and 'nobody checked'. A colourblind
    reader must be able to tell them apart, so each status needs its own shape
    and glyph as well as its colour."""
    block = JS[JS.index("var MARKERS = {"):JS.index("function pinIcon(")]
    for status in ("verified", "unconfirmed", "outdated", "pharmacy", "municipality"):
        assert status + ":" in block, status
    # three shapes and both fill styles are in use
    for shape in ('shape: "pin"', 'shape: "square"', 'shape: "circle"'):
        assert shape in block, shape
    assert "solid: true" in block and "solid: false" in block
    # every status carries a glyph
    assert block.count("glyph:") == 5


def test_legend_is_generated_from_the_marker_table():
    """A hand-written legend drifts from the pins the first time one is edited."""
    assert "function buildMapLegend()" in JS
    assert "markerSvg(row[0], 20)" in JS
    assert 'class="lg lg-verified"' not in HTML, "legend must not be hardcoded in markup"


def test_unconfirmed_facility_offers_a_call_to_verify():
    assert "Call to verify" in JS
    assert 'tel:' in JS


# ------------------------------------------------- chat provenance
def test_reviewed_and_generated_answers_are_distinguished_structurally():
    """Not by a footnote alone: the two carry different classes, and the CSS
    gives them different rules and tints."""
    assert 'pending.classList.add("generated")' in JS
    assert 'pending.classList.add("reviewed")' in JS
    assert "Generated — not reviewed by the research team" in JS
    assert "Reviewed · " in JS
    assert ".bubble.bot.reviewed" in CSS and ".bubble.bot.generated" in CSS


def test_thinking_indicator_is_animated_and_labelled():
    assert 'pending.classList.add("thinking")' in JS
    assert '"Candie is thinking"' in JS, "the dots need an accessible label"
    assert ".bubble.thinking" in CSS and "@keyframes thinkdot" in CSS


def test_animations_respect_reduced_motion():
    for selector in ("thinkdot", "voicering"):
        assert selector in CSS
    reduced = CSS.count("prefers-reduced-motion")
    assert reduced >= 3, f"only {reduced} reduced-motion guards found"
    assert ':root[data-motion="off"] .bubble.thinking i' in CSS


# ------------------------------------------------- assessment flow (C)
def test_stepper_is_named_and_has_microcopy():
    assert 'id="stepper"' in HTML and 'id="stepNote"' in HTML
    assert 'id="stepBar"' not in HTML, "the anonymous bar list was replaced"
    assert "var STEPNOTES" in JS
    assert JS.count("STEPNOTES") >= 2
    assert ".stepseg" in CSS and ".stepnote" in CSS


def test_step_actions_dock_on_small_screens():
    block = CSS[CSS.index(".stepactions"):]
    assert "position:sticky" in block[:600]
    assert "env(safe-area-inset-bottom" in block[:600]


def test_choice_rows_are_large_touch_targets():
    block = CSS[CSS.index(".step .choice"):]
    assert "min-height:52px" in block[:200]


# ------------------------------------------------- tile fallback (4)
def test_tile_fallback_counts_unique_failures_not_events():
    """Leaflet retries a tile and fires tileerror each time. Counting events made
    one slow tile look like four failures and skipped a working provider."""
    assert "MapView.failedUrls" in JS
    assert "generation !== MapView.generation" in JS
    assert "Object.keys(MapView.failedUrls).length < 4" in JS
    assert "MapView.errors" not in JS, "the event counter must be gone"


# ------------------------------------------------- dashboard (D)
def test_empty_states_have_art_and_an_action():
    assert "var EMPTY_ART" in JS
    for art in ("clipboard", "pin", "search", "chart"):
        assert art + ":" in JS, art
    assert 'label: "Start an assessment"' in JS


def test_count_up_is_skipped_under_reduced_motion():
    block = JS[JS.index("function countUp("):JS.index("function statCard(")]
    assert 'data-motion") === "off"' in block
    assert "prefers-reduced-motion" in block


# ------------------------------------------------- bottom sheet (E)
def test_chat_is_a_bottom_sheet_on_phones():
    assert 'id="chatScrim"' in HTML
    assert ".chatsheet-scrim" in CSS
    mobile = CSS[CSS.index("Chat as a bottom sheet"):]
    assert "translateY(100%)" in mobile[:900]
    assert "function sheetDown(" in JS and "function sheetUp(" in JS
    assert "if (dy > 110)" in JS, "swipe-to-dismiss threshold"


def test_sheet_does_not_steal_focus_on_a_phone():
    """Focusing the input raises the keyboard over the sheet before the greeting
    can be read."""
    assert "if (!sheet) $(\"chatInput\").focus();" in JS


# ---------------------------------------- adopted reference UI
def test_no_framework_crept_in_with_the_reference_design():
    """The reference was a Next.js/Tailwind/shadcn app. Only its visual language
    was taken; none of its machinery may appear in a no-build frontend."""
    for banned in ("tailwind", "shadcn", "lucide-react", "next/", "react-dom",
                   "className=", "useState("):
        assert banned not in JS, f"{banned} found in app.js"
        assert banned not in HTML, f"{banned} found in index.html"


def test_reference_placeholder_data_was_not_copied():
    """The mockup shipped invented values: districts, a glucose reading, a
    distance, a fake user. None belongs in a system with real records."""
    for placeholder in ("Central District", "North District", "WellSpring",
                        "198", "1.2 km", "10:42", "Northside Family"):
        assert placeholder not in HTML, f"placeholder {placeholder!r} copied into markup"


def test_adopted_styles_introduce_no_new_colours():
    """The reference shipped its own palette. Adopting its layout must not drag
    those hexes in: every literal colour in the adopted layer has to be one the
    palette above already uses."""
    import re as _re
    marker = "Layer adopted from the supplied reference UI"
    before, adopted = CSS[:CSS.index(marker)], CSS[CSS.index(marker):]
    existing = set(_re.findall(r"#[0-9A-Fa-f]{6}\b", before))
    introduced = set(_re.findall(r"#[0-9A-Fa-f]{6}\b", adopted)) - existing
    assert not introduced, f"new colours introduced: {sorted(introduced)}"

    # and the reference's own values specifically must not appear anywhere
    for ref_hex in ("#75c5d1", "#2689a7", "#bce7ec", "#a9e2e8", "#eab79d", "#50ba9d"):
        assert ref_hex.lower() not in CSS.lower(), f"reference colour {ref_hex} copied"


def test_welcome_card_keeps_the_real_mascot():
    """The reference replaced Candie with an abstract CSS droplet."""
    assert 'src="/assets/candie.png"' in HTML
    assert "mascot-shine" not in CSS and "clip-path: path(" not in CSS


def test_breadcrumbs_and_eyebrows_present():
    assert 'class="crumbs"' in HTML and 'id="crumb"' in HTML
    assert HTML.count('class="eyebrow"') >= 8


def test_stat_cards_have_tone_tiles():
    assert "var STAT_TONES" in JS
    for tone in ("tone-mint", "tone-blue", "tone-peach", "tone-lav"):
        assert tone in CSS, tone


def test_result_alert_states_urgency_in_words():
    assert "var URGENCY" in JS
    assert '"Seek care now"' in JS
    assert ".resultalert" in CSS and ".urgency" in CSS


def test_chat_keeps_provenance_after_the_restyle():
    """The reference's chat had provenance chips; ours must still carry the
    reviewed/generated distinction added for safety."""
    assert 'pending.classList.add("generated")' in JS
    assert 'pending.classList.add("reviewed")' in JS
    assert ".miniavatar" in CSS and ".chatday" in CSS


# ------------------------------------------------- onboarding
def test_onboarding_sets_expectations_rather_than_touring_features():
    """A health tool's introduction has to say what it will not do, or the
    interface itself creates the wrong expectation."""
    block = JS[JS.index("var Onboard = {"):JS.index("/* ========================================================= account */")]
    assert "Does not diagnose" in block
    assert "Does not give a risk percentage or score" in block
    assert "American Diabetes Association" in block
    assert "Nothing is stored" in block


def test_onboarding_is_skippable_and_replayable():
    assert 'id="obSkip"' in HTML
    assert 'id="replayOnboard"' in HTML
    block = JS[JS.index("var Onboard = {"):]
    assert "shouldShow:" in block and "diabetease.onboarded" in block
    # skipping still records the choice, so it does not reappear next visit
    assert "// Marked done either way" in block


def test_onboarding_collects_no_health_data():
    """The only thing it asks for is a municipality, which is a convenience
    setting, not health information."""
    card = HTML[HTML.index('id="onboard"'):HTML.index('<a class="vh" href="#main">')]
    for field in ("type=\"number\"", "age", "glucose", "hba1c", "symptom"):
        assert field not in card.lower(), f"onboarding must not ask for {field}"
    assert 'id="obMuni"' in card


def test_onboarding_dialog_is_accessible():
    card = HTML[HTML.index('id="onboard"'):HTML.index('<a class="vh" href="#main">')]
    assert 'role="dialog"' in card and 'aria-modal="true"' in card
    assert 'aria-labelledby="obTitle"' in card
    assert '<label for="obMuni">' in card
    block = JS[JS.index("var Onboard = {"):]
    assert 'e.key === "Escape"' in JS
    assert "e.shiftKey && document.activeElement === first" in JS, "focus trap missing"
    assert "lastFocus" in block, "focus must return to where it came from"


def test_onboarding_does_not_interrupt_a_deep_link():
    assert "Onboard.shouldShow() && !location.hash" in JS


def test_onboarding_survives_blocked_storage():
    """A browser with storage disabled must not show the dialog on every load."""
    block = JS[JS.index("shouldShow: function"):JS.index("markDone:")]
    assert "catch (e) { return false; }" in block
