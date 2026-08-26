"""The static page: that it is self-contained, and that its wiring still joins up.

None of this needs a browser. What it checks is the class of breakage that a browser
would show you only if you happened to look at the right part of the page: a string key
with no string behind it, a file the markup asks for that is not there, a vendored
module that quietly went back to fetching itself from a CDN.

What it deliberately does not check is anything about how the page *looks*. Canvas
output, drag, font features and colour contrast are all real and none of them is a
pytest's business; ``web/globe.js`` opens with the list to run through by eye instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB = REPO_ROOT / "web"
INDEX = WEB / "index.html"
SPINE = REPO_ROOT / "data" / "processed" / "route_spine.json"

needs_page = pytest.mark.skipif(
    not INDEX.exists(), reason="web/index.html not built yet"
)


@pytest.fixture(scope="module")
def html():
    return INDEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def strings():
    payload = json.loads((WEB / "data" / "strings.json").read_text(encoding="utf-8"))
    return payload["strings"]


# ------------------------------------------------------- no network at view time


@needs_page
def test_no_vendored_module_still_imports_from_a_cdn():
    """A missing tile layer degrades. A missing d3-geo is a blank screen."""
    for path in (WEB / "vendor").glob("*.js"):
        for target in re.findall(r'from\s*"([^"]+)"', path.read_text(encoding="utf-8")):
            assert target.startswith("./"), f"{path.name} imports {target}"


@needs_page
def test_the_page_asks_for_nothing_over_the_network(html):
    """Every stylesheet, module and font is local. Absolute URLs are links out."""
    for attribute in re.findall(r'(?:src|href)="([^"]+)"', html):
        if attribute.startswith(("#", "data:", "mailto:", "https://")):
            continue
        assert (WEB / attribute.lstrip("./")).exists(), f"missing: {attribute}"


@needs_page
def test_no_stylesheet_or_script_is_loaded_from_someone_elses_server(html):
    """Only actual fetches count.

    `rel="canonical"` and `rel="license"` are declarations about the page rather than
    things it goes and gets, so this filters to stylesheets and modules instead of
    banning absolute URLs outright.
    """
    fetched = re.findall(r'<script[^>]*\ssrc="(https?://[^"]+)"', html)
    fetched += re.findall(
        r'<link[^>]*\srel="stylesheet"[^>]*\shref="(https?://[^"]+)"', html
    )
    assert fetched == [], f"the page would fetch {fetched} at view time"


# --------------------------------------------------------------- strings, not markup


@needs_page
def test_every_key_the_markup_asks_for_exists(html, strings):
    keys = set(re.findall(r'data-i18n(?:-label)?="([^"]+)"', html))
    assert keys, "the markup should be driven by the catalogue"
    missing = sorted(key for key in keys if key not in strings)
    assert missing == [], f"no string for {missing}"


@needs_page
def test_every_key_the_scripts_ask_for_exists(strings):
    keys: set[str] = set()
    for path in WEB.glob("*.js"):
        # The lookbehind matters: without it this also matches getContext("2d") and
        # createElement("li"), which end in the same two characters.
        # Only literal keys — `t(`mode.${mode}`)` is built at run time, and the
        # transport-mode test below is what covers it.
        keys |= set(
            re.findall(
                r'(?<![A-Za-z0-9_$])t\(\s*"([^"]+)"',
                path.read_text(encoding="utf-8"),
            )
        )
    missing = sorted(key for key in keys if key not in strings)
    assert missing == [], f"no string for {missing}"


@needs_page
def test_every_transport_mode_has_a_label(strings):
    journey = json.loads((WEB / "data" / "journey.json").read_text(encoding="utf-8"))
    for mode in journey["transport_style"]:
        assert f"mode.{mode}" in strings, mode


@needs_page
def test_no_string_carries_markup(strings):
    """A tag in the table is an injection hole and prints as angle brackets."""
    for key, value in strings.items():
        assert not re.search(r"<[^>]+>", value), key


# ---------------------------------------------------------- the no-JavaScript page


@needs_page
def test_the_noscript_stops_are_the_route_the_data_states(html):
    """Hand-written, because there is no build step to generate it — so it is checked.

    The nine names are the book's and will not change. That makes duplicating them safe
    and makes leaving them unverified pointless.
    """
    block = re.search(r"<noscript>(.*?)</noscript>", html, re.S)
    assert block, "the page needs to say something with scripting turned off"
    # Whitespace-collapsed, because the markup wraps and "San Francisco" is allowed to
    # arrive as "San\n      Francisco".
    text = " ".join(block.group(1).split())
    spine = json.loads(SPINE.read_text(encoding="utf-8"))
    for node in spine["nodes"]:
        assert node["name_in_text"] in text, node["name_in_text"]


# ---------------------------------------------- the credibility anchor and the licence


@needs_page
def test_the_page_names_its_sources(html):
    for source in ("Gutenberg", "Wikidata", "Natural Earth"):
        assert source in html, source


@needs_page
def test_the_page_carries_the_licence_the_spec_asks_for(html):
    assert "by-nc-sa" in html
    assert "hello@crowintelligence.org" in html


@needs_page
def test_the_page_says_the_arcs_are_schematic(html, strings):
    """The one sentence that keeps a great circle from reading as a surveyed route."""
    assert "arc.schematic" in html
    assert "great circles" in strings["arc.schematic"]


@needs_page
def test_the_fonts_ship_with_their_licence():
    """The SIL OFL requires the licence to travel with the files."""
    fonts = WEB / "fonts"
    assert list(fonts.glob("*.woff2")), "no fonts self-hosted"
    for family in ("ebgaramond", "playfairdisplay"):
        assert (fonts / f"OFL-{family}.txt").exists(), family


@needs_page
def test_every_font_the_stylesheet_names_is_present():
    css = (WEB / "fonts" / "fonts.css").read_text(encoding="utf-8")
    for name in re.findall(r"url\('\./([^']+)'\)", css):
        assert (WEB / "fonts" / name).exists(), name


@needs_page
def test_the_page_has_no_roadmap_prose(html):
    """The page says what it shows, not what it does not.

    Data honesty stays — the provenance box counts what nobody has checked, and
    `arc.schematic` says the lines are not a survey. What goes is anything about what
    has not been built. This test is what keeps it from creeping back.
    """
    body = re.sub(r"<!--.*?-->", "", html, flags=re.S).lower()
    for phrase in (
        "not finished",
        "not built",
        "coming soon",
        "is next",
        "are next",
        "todo",
        "not yet built",
        "for now",
    ):
        assert phrase not in body, f"the page still says {phrase!r}"


@needs_page
def test_every_heading_comes_from_the_table(html):
    """A hardcoded heading is the crack the rest of the prose gets back in through."""
    for heading in re.findall(r"<h2([^>]*)>", html):
        assert "data-i18n" in heading, f"<h2{heading}> is hardcoded"


@needs_page
def test_the_page_offers_a_way_past_the_globe(html):
    """A canvas is nothing to a screen reader, so the itinerary has to be reachable."""
    assert 'href="#itinerary"' in html
    assert 'href="#main"' in html


# ------------------------------------------------- every key defined is a key used

# Prefixes whose keys are chosen at run time from an enum or a data value, so a grep
# cannot see them. Each is covered by a completeness test below instead.
DYNAMIC = ("mode.", "schedule.", "track.", "place.class.")

# Reasons and one-off keys the page reaches through a computed name.
COMPUTED = {
    "place.off_route",
    "place.floating_interior",
    "place.none_found",
    "place.not_queried",
    "place.rejected",
    "place.contradicts_its_leg",
}


@needs_page
def test_every_key_defined_is_a_key_used(strings):
    """A defined-and-unused key is how the last twenty-five accumulated.

    The chapter payload shipped for a phase with nothing reading it, and half the table
    described a panel that did not exist. Neither was visible until somebody went
    looking. This is what makes it visible.
    """
    used = (WEB / "index.html").read_text(encoding="utf-8")
    for path in sorted(WEB.glob("*.js")):
        used += path.read_text(encoding="utf-8")
    unused = sorted(
        key
        for key in strings
        if key not in used and key not in COMPUTED and not key.startswith(DYNAMIC)
    )
    assert unused == [], f"defined and never used: {unused}"


@needs_page
def test_every_key_used_is_a_key_defined(strings, html):
    """The other direction. A missing key renders as its own name."""
    used = set(re.findall(r'data-i18n(?:-label|-content)?="([^"]+)"', html))
    for path in sorted(WEB.glob("*.js")):
        used |= set(
            re.findall(
                r'(?<![A-Za-z0-9_$])t\(\s*"([^"]+)"',
                path.read_text(encoding="utf-8"),
            )
        )
    assert sorted(key for key in used if key not in strings) == []


@needs_page
def test_every_schedule_status_has_a_label(strings):
    from verne80.schema import ScheduleStatus

    for status in ScheduleStatus:
        assert f"schedule.{status.value}" in strings, status


@needs_page
def test_every_position_source_has_a_label(strings):
    """Except `stated`, which the panel words differently — assert that too."""
    from verne80.position import PositionSource

    for source in PositionSource:
        key = (
            "track.absent"
            if source is PositionSource.UNKNOWN
            else f"track.{source.value}"
        )
        assert key in strings, source


@needs_page
def test_every_temporal_class_has_a_label(strings):
    """Including UNKNOWN, which the data does not use yet but the enum allows."""
    from verne80.position import TemporalClass

    for temporal in TemporalClass:
        assert f"place.class.{temporal.value}" in strings, temporal


@needs_page
def test_every_reason_a_place_is_held_back_has_a_label(strings):
    listed = json.loads((WEB / "data" / "places.json").read_text(encoding="utf-8"))
    for entry in listed["listed"]:
        assert f"place.{entry['reason']}" in strings, entry["reason"]
