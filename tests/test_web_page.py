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
import struct
from pathlib import Path

import pytest

from verne80 import page
from verne80.strings import SITE_URL

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
def summaries():
    return CHAPTERS_PAGE.read_text(encoding="utf-8")


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


# Root-absolute paths are the *site's* files, not this page's: they resolve only once
# this directory is copied to crowintelligence.org. There is exactly one, and naming it
# here is what stops a second arriving unnoticed.
SITE_ASSETS = {"/consent.js"}


@needs_page
def test_the_page_asks_for_nothing_over_the_network(html):
    """Every stylesheet, module and font is local. Absolute URLs are links out."""
    for attribute in re.findall(r'(?:src|href)="([^"]+)"', html):
        if attribute.startswith(("#", "data:", "mailto:", "https://")):
            continue
        if attribute in SITE_ASSETS:
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
def test_the_head_matches_the_string_table(html, strings):
    """The title and the description are in the markup twice over, on purpose.

    A crawler that runs no JavaScript still has to read them, so they are written into
    the head rather than filled by `localise()`. That is a duplicate, and a duplicate
    nobody checks is a duplicate that drifts.
    """
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    assert title and title.group(1).strip() == strings["site.page_title"]

    for pattern, key in (
        (r'<meta name="description"[^>]*content="([^"]*)"', "site.description"),
        (r'<meta property="og:title" content="([^"]*)"', "site.title"),
        (r'<meta name="twitter:title" content="([^"]*)"', "site.title"),
        (r'<meta name="twitter:description" content="([^"]*)"', "site.subtitle"),
        (r'<meta property="og:image:alt" content="([^"]*)"', "site.card_alt"),
    ):
        found = re.search(pattern, html)
        assert found, pattern
        assert found.group(1) == strings[key], key


@needs_page
def test_every_border_era_has_a_label(strings):
    """The control builds its own labels from the era names."""
    for era in ("none", "1880", "today"):
        assert f"borders.{era}" in strings, era


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
DYNAMIC = ("mode.", "schedule.", "track.", "place.class.", "borders.")

# Written into the markup rather than filled at run time, because a crawler has to see
# them without executing anything. test_the_head_matches_the_string_table is what stops
# the two copies drifting.
HEAD = {"site.page_title", "site.title", "site.description"}

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
    # The corpus includes the builder and the template: the written-out chapters carry
    # no data-i18n, so their strings are used by page.py rather than by the markup.
    used = (WEB / "index.html").read_text(encoding="utf-8")
    used += TEMPLATE.read_text(encoding="utf-8")
    used += CHAPTERS_TEMPLATE.read_text(encoding="utf-8")
    used += (REPO_ROOT / "src" / "verne80" / "page.py").read_text(encoding="utf-8")
    for path in sorted(WEB.glob("*.js")):
        used += path.read_text(encoding="utf-8")
    unused = sorted(
        key
        for key in strings
        if key not in used
        and key not in COMPUTED
        and key not in HEAD
        and not key.startswith(DYNAMIC)
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


@needs_page
def test_the_share_card_the_head_promises_exists():
    """It did not, for three phases. Every share unfurled without an image."""
    card = WEB / "assets" / "og.png"
    assert card.exists(), "run scripts/09_og_card.py"

    # The PNG header, rather than Pillow: the dimensions are asserted against what the
    # markup declares, and a test should not need the library that made the file.
    header = card.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", header[16:24])
    assert (width, height) == (1200, 630)


@needs_page
def test_the_card_is_the_size_the_head_says_it_is(html):
    declared = {
        key: int(re.search(rf'"og:image:{key}" content="(\d+)"', html).group(1))
        for key in ("width", "height")
    }
    assert (declared["width"], declared["height"]) == (1200, 630)


# ------------------------------------- what the page says with no JavaScript at all

TEMPLATE = REPO_ROOT / "src" / "verne80" / "page_template.html"
CHAPTERS_TEMPLATE = REPO_ROOT / "src" / "verne80" / "chapters_template.html"
CHAPTERS_PAGE = WEB / "chapters" / "index.html"


@needs_page
def test_the_page_says_what_it_says_without_javascript(html):
    """107 words was 15% of what a rendering crawler saw. This is the floor now.

    Three numbers set it. The page carries about 6,200 words after the chapter sections,
    so a floor of 3,000 leaves half the value as headroom and no editorial trim will
    reach it. If the chapter block silently failed to render the page would fall to
    about 520, so the gap between passing and failing is an order of magnitude and
    nobody has to argue the figure.

    What this does not catch is one chapter going missing, which costs about 90 words.
    That is deliberate — the test below names each chapter, and a blunt floor should not
    pretend to do a precise test's job.
    """
    words = len(page.visible_text(html).split())
    assert words >= page.WORD_FLOOR, (
        f"the globe says {words} words with scripting off, and it said 107 "
        "before the strings and the itinerary were baked in. A number this low means a "
        "block did not render. Run `make dashboard && make page`."
    )


@needs_page
def test_the_summaries_page_says_the_whole_book(summaries):
    """The 5,566 words that were 90% of the globe, on a page of their own now."""
    words = len(page.visible_text(summaries).split())
    assert words >= page.CHAPTERS_WORD_FLOOR, f"only {words} words — a block is missing"


@needs_page
def test_every_chapter_reaches_the_raw_html(summaries):
    """The counterpart to the blunt floor: one chapter missing costs 90 words."""
    payload = json.loads((WEB / "data" / "chapters.json").read_text(encoding="utf-8"))
    readable = page.visible_text(summaries)
    for entry in payload["chapters"]:
        number = entry["chapter"]
        assert f'id="ch-{number}"' in summaries, number
        assert " ".join(entry["title"].split()) in readable, number
        assert " ".join(entry["summary"]["detail"].split()) in readable, number


@needs_page
def test_the_two_pages_link_to_each_other(html, summaries):
    """Two files that have to agree, so a test holds them together.

    The globe sends a reader to the summaries twice — under the chapter bar and after
    the itinerary — and every summary sends them back to that chapter on the globe. A
    one-way link is how a second page becomes an orphan.
    """
    assert html.count('href="./chapters/"') >= 2
    payload = json.loads((WEB / "data" / "chapters.json").read_text(encoding="utf-8"))
    for entry in payload["chapters"]:
        assert f'href="../#ch-{entry["chapter"]}"' in summaries, entry["chapter"]


@needs_page
def test_the_summaries_page_needs_no_javascript_of_its_own(summaries):
    """It is prose. A script on it would only be a way for it to break."""
    scripts = re.findall(r"<script([^>]*)>", summaries)
    for attributes in scripts:
        assert 'type="application/ld+json"' in attributes or "/consent.js" in attributes


@needs_page
def test_the_summaries_page_reaches_the_shared_assets_one_level_up(summaries):
    for path in re.findall(r'(?:href|src)="(\.\./[^"#]*)"', summaries):
        assert (CHAPTERS_PAGE.parent / path).resolve().exists(), path


@needs_page
def test_the_itinerary_is_in_the_file_not_only_in_the_script(html):
    journey = json.loads((WEB / "data" / "journey.json").read_text(encoding="utf-8"))
    readable = page.visible_text(html)
    for node in journey["nodes"]:
        assert node["name_in_text"] in readable, node["name_in_text"]


# ----------------------------------------------- the page is generated, and checked


@needs_page
def test_no_module_function_calls_into_the_main_closure():
    """The bug that got past every test here, made impossible to repeat.

    `go()` was declared at module scope and called `render()`, a closure inside
    `main()`. Every tab click threw a ReferenceError, while the initial load and Back
    went on working — so a test that opened a URL and read the DOM passed and proved
    nothing about clicking.

    Only calls are flagged, never bare identifiers: this file has module-scope functions
    taking parameters named `chapters` and `journey`, which are also names inside
    `main()`, and nobody calls those.
    """
    source = _without_comments((WEB / "app.js").read_text(encoding="utf-8"))
    start = source.index("async function main() {")
    end = source.index("\n}\n", start)
    inside, outside = source[start:end], source[:start] + source[end:]

    declared = set(re.findall(r"\n  (?:function|const|let) (\w+)", inside))
    at_module_scope = set(re.findall(r"\n(?:function|const|let) (\w+)", outside))
    private = declared - at_module_scope

    called = set(re.findall(r"(?<![\w.$])(\w+)\s*\(", outside))
    reaching = sorted(private & called)
    assert reaching == [], (
        f"{reaching} live inside main() and are called from module scope, which throws "
        "a ReferenceError the moment a reader clicks anything"
    )


def _without_comments(source: str) -> str:
    """JavaScript with its comments removed, so prose does not read as code.

    This file explains itself at length, and four of those explanations say the word
    `render()` — including the one describing the bug. A scanner that cannot tell a
    sentence from a call finds them all.

    Crude on purpose: block comments go, and so does any line that begins with `//` or
    with the `*` of a continued block. A trailing `// note` survives, which can only
    make the scan miss a call, never invent one.
    """
    import re as _re

    source = _re.sub(r"/\*.*?\*/", "", source, flags=_re.S)
    return "\n".join(
        "" if line.lstrip().startswith(("//", "*")) else line
        for line in source.splitlines()
    )


@needs_page
def test_the_committed_page_still_matches_its_template_and_payloads():
    """The same freshness contract the payloads have, for the same reason."""
    loaded = {
        name: json.loads((WEB / "data" / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("chapters", "journey", "places", "provenance")
    }
    rebuilt = page.render(
        loaded["chapters"],
        loaded["journey"],
        loaded["places"],
        loaded["provenance"],
        TEMPLATE.read_text(encoding="utf-8"),
    )
    assert rebuilt == (WEB / "index.html").read_text(encoding="utf-8"), (
        "web/index.html is stale — run `make dashboard && make page` and commit both"
    )
    assert page.render_chapters(
        loaded["chapters"], CHAPTERS_TEMPLATE.read_text(encoding="utf-8")
    ) == CHAPTERS_PAGE.read_text(encoding="utf-8"), (
        "web/chapters/index.html is stale — run `make page` and commit it"
    )


@needs_page
@pytest.mark.parametrize("which", ["page_template.html", "chapters_template.html"])
def test_the_template_leaves_no_element_for_javascript_to_fill(which):
    """Thirteen elements were empty in the markup and filled only at run time."""
    source = (REPO_ROOT / "src" / "verne80" / which).read_text(encoding="utf-8")
    assert page.check_template(source) == []


@needs_page
def test_no_token_survives_into_the_page(html):
    assert "{{" not in html and "}}" not in html


# --------------------------------------------------------- the address, stated once


@needs_page
def test_every_absolute_self_reference_uses_the_one_constant(html):
    """Four URLs said /verne80/ while the deployed directory is /verne/."""
    ours = re.findall(r"https://crowintelligence\.org/verne[^\"'< ]*", html)
    assert ours, "the page should state its own address"
    assert [one for one in ours if not one.startswith(SITE_URL)] == []


@needs_page
def test_the_repository_name_is_not_the_deployed_slug(html):
    """A GitHub link to the repo is fine; crowintelligence.org/verne80 is a 404."""
    assert "crowintelligence.org/verne80" not in html


@needs_page
def test_the_router_and_the_tab_bar_agree_on_the_hash(html):
    """Two halves of one decision, in two files, so a test holds them together."""
    router = (WEB / "app.js").read_text(encoding="utf-8")
    assert r"/^#ch-(\d+)$/" in router
    # The tab points at the summary and the click never follows it: a table of contents
    # with scripting off, a tab with it on.
    assert "./chapters/#ch-${entry.chapter}" in router


# ------------------------------------------------- the head, and the structured data


@needs_page
def test_the_page_loads_the_sites_consent_script(html):
    """Every other microsite on the domain carries it. This one did not."""
    assert '<script defer src="/consent.js"></script>' in html


@needs_page
def test_the_page_preloads_the_faces_the_first_screenful_needs(html):
    preloads = re.findall(r'<link rel="preload" href="\./fonts/([^"]+)"', html)
    assert set(preloads) == {
        "ebgaramond-400-600-n-lat.woff2",
        "playfairdisplay-400-n-lat.woff2",
    }
    for name in preloads:
        assert (WEB / "fonts" / name).exists(), name
    # A font preload without crossorigin is discarded and quietly fetched twice.
    assert html.count('as="font"\n      type="font/woff2" crossorigin') == 2


@needs_page
def test_the_structured_data_parses_and_names_what_it_should(html):
    """A malformed graph is invisible until Search Console complains, weeks later."""
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert block, "the page should carry structured data"
    graph = json.loads(block.group(1))["@graph"]

    kinds = {node["@type"] for node in graph}
    assert kinds == {
        "WebPage",
        "ImageObject",
        "Book",
        "Dataset",
        "BreadcrumbList",
        "Organization",
    }

    defined = {node["@id"] for node in graph}
    for node in graph:
        for value in _references(node):
            assert value in defined or value.startswith("https://"), value

    dataset = next(node for node in graph if node["@type"] == "Dataset")
    for part in dataset["distribution"]:
        assert part["contentUrl"].startswith(SITE_URL), part["contentUrl"]
        name = part["contentUrl"].rsplit("/", 1)[-1]
        assert (WEB / "data" / name).exists(), name


@needs_page
def test_the_dataset_claims_no_licence_it_does_not_hold(html):
    """borders_1880.json is GPL-3.0; calling it CC BY-NC-SA would be a false claim."""
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    dataset = next(
        node
        for node in json.loads(block.group(1))["@graph"]
        if node["@type"] == "Dataset"
    )
    listed = {part["contentUrl"].rsplit("/", 1)[-1] for part in dataset["distribution"]}
    assert "borders_1880.json" not in listed
    assert "land.json" not in listed and "borders_modern.json" not in listed


@needs_page
def test_the_book_is_identified_by_the_right_wikidata_entity(html):
    """Q1219561 is the novel. The films and the play have their own identifiers."""
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    book = next(
        node for node in json.loads(block.group(1))["@graph"] if node["@type"] == "Book"
    )
    assert "https://www.wikidata.org/wiki/Q1219561" in book["sameAs"]
    assert book["author"]["sameAs"] == "https://www.wikidata.org/wiki/Q33977"


@needs_page
def test_the_preview_card_is_what_the_site_grid_expects():
    """Its only consumer is another repository, which loads none of these fonts."""
    import xml.etree.ElementTree as ElementTree

    card = WEB / "preview.svg"
    assert card.exists()
    root = ElementTree.parse(card).getroot()
    assert root.get("viewBox") == "0 0 560 440"
    raw = card.read_text(encoding="utf-8")
    assert "@font-face" not in raw and "xlink:href" not in raw
    assert "http" not in raw.replace("http://www.w3.org/2000/svg", "")


def _references(node, out=None):
    """Every `@id` this node points at, however deeply nested."""
    out = [] if out is None else out
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "@id":
                continue
            if isinstance(value, dict) and set(value) == {"@id"}:
                out.append(value["@id"])
            else:
                _references(value, out)
    elif isinstance(node, list):
        for item in node:
            _references(item, out)
    return out
