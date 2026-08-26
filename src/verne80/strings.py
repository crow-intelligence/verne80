r"""Every user-facing string the page shows, in one place.

The house rule is that user-facing text lives in one file and never in the markup, so
that changing what the page says is an edit here rather than a hunt through HTML and
JavaScript. This is the whole of what the reader reads, apart from the chapter
summaries, which are content and live in the data.

The page is English and there is no second language. That is a decision rather than an
omission: an empty translation catalogue and a one-item language picker are machinery
for a thing nobody is building, and they read on the page as a control that does
nothing. If a translation is ever wanted, the shape to come back to is a mapping of
language to this same table, plus ``summary`` in ``chapters.json`` gaining a language
key beside ``hover`` and ``detail``. Both are a day's work from here and neither is
worth carrying meanwhile.

Two conventions are load-bearing.

**No HTML in a string, ever.** A catalogue entry carrying ``<a href=…>`` is an
injection hole and an unreadable blob at the same time. A sentence that needs a link or
an emphasis is split into two keys with the markup built between them, or it does
without. :func:`check_strings` enforces this, and it is why the "About the project"
prose here has no italics: one emphasised word is not worth two keys.

**A printed name is a quotation and is never rewritten.** ``name_in_text`` throughout
this project is what Gutenberg #103 printed, and the text is not consistent with
itself: chapters 20 and 21 call the pilot of the *Tankadere* John Bunsby, and chapter
24 calls him John Busby. The extraction is faithful and the book is not. Tidying that
away in the data would destroy the evidence; the place to reconcile it is a display
roster, where both spellings survive and one of them is chosen to show.
"""

from __future__ import annotations

import re

__all__ = [
    "LANGUAGE",
    "STRINGS",
    "check_strings",
    "placeholder_names",
    "strings_payload",
]

# Stated so the markup, the JSON-LD and the OpenGraph locale have one source between
# them, rather than three literals that can drift.
LANGUAGE = "en"

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_MARKUP = re.compile(r"<[^>]+>")

STRINGS: dict[str, str] = {
    # --- the page itself ---
    "site.title": "Around the World in Eighty Days",
    "site.subtitle": "Fogg's itinerary, on the globe he went round",
    "site.description": (
        "The route and calendar of Jules Verne's 1872 novel, extracted from the text "
        "and shown on a rotating globe."
    ),
    # --- site chrome ---
    "nav.brand": "Crow Intelligence",
    "nav.portfolio": "Portfolio",
    "nav.services": "Services",
    "nav.about": "About",
    "nav.blog": "Blog",
    "nav.contact": "Contact",
    "skip.content": "Skip to the content",
    "skip.itinerary": "Skip the globe, read the itinerary",
    # --- the globe ---
    "route.heading": "The route",
    "globe.aria": "A globe showing Phileas Fogg's route around the world.",
    "globe.hint": "Drag to turn the globe.",
    "globe.rotate.pause": "Stop turning",
    "globe.rotate.play": "Turn slowly",
    # --- the chapter browser ---
    "chapters.heading": "The chapters",
    "chapters.note": (
        "Thirty-seven chapters. Pick one and the globe turns to where the party "
        "is, and the places that chapter names appear around them."
    ),
    "chapters.bar.label": "Chapters",
    "chapters.pick": "Pick a chapter to follow the party.",
    "chapters.overview": "Whole route",
    "chapter.heading": "Chapter {n}. {title}",
    "chapter.of": "Chapter {n} of {total}",
    "chapter.next": "Next",
    "chapter.previous": "Previous",
    # --- where the party is ---
    "where.heading": "Where the party is",
    # --- the eighty days ---
    "day.heading": "The eighty days",
    "day.window": (
        "Fogg is on the stage from {origin} to {destination}. His own table budgets "
        "days {from} to {to} for it."
    ),
    # The sentence that stops "days 20 to 23" being read as "it is day 21". `along`
    # orders pins along a line; it is not time, and RoutePoint's docstring is explicit
    # that it must not reach this page as a percentage of anything.
    "day.not_a_date": (
        "The table is a budget, not a diary — the chapter does not date itself."
    ),
    "day.no_window": "The chapter does not put Fogg on any stage of the itinerary.",
    "day.says": "The chapter says he is {status}.",
    "day.says_detail": "The chapter says he is {status}: {detail}",
    # `schedule.unknown` reads as a clause, not a state, so it cannot be dropped into
    # "he is {status}" — that composes to "he is the chapter does not say".
    "day.silent": "The chapter does not say whether he is ahead or behind.",
    # --- who is in it ---
    "people.present.heading": "Who is in this chapter",
    "people.elsewhere.heading": "Talked about, not here",
    "people.elsewhere.none": "Nobody is talked about who is not in the chapter.",
    "people.roles.note": (
        "The book names these by what they are rather than who they are, so each one "
        "belongs to its own chapter — the engineer of one is not the engineer of "
        "another."
    ),
    # The display name is ours; the printed one is the book's. Saying "printed here as"
    # rather than "also printed" is right in both cases — the chapter that calls him
    # Mr. Fogg, and the chapter that calls him two things at once.
    "people.printed_as": "printed here as {names}",
    # --- the places a chapter names ---
    "place.heading": "Places this chapter names",
    "place.count": "{plotted} of {named} have a place on the globe.",
    "place.class.here": "where the party is",
    "place.class.past": "behind them",
    "place.class.future": "ahead of them",
    "place.class.cyclic": "behind them and ahead of them",
    "place.class.off_route": "off the route",
    "place.class.unknown": "unplaced",
    "place.off_route": "a region or an institution, not somewhere to stand",
    "place.floating_interior": "somewhere inside wherever the party already is",
    "place.none_found": "no modern place has been matched to this name",
    "place.not_queried": "not yet looked up",
    "place.rejected": "the resolution was rejected and nothing has replaced it",
    "place.contradicts_its_leg": "resolved somewhere its own stage never goes",
    # --- how they travel ---
    "transport.heading": "How they travel",
    "transport.none": "The chapter names no journey.",
    "transport.between": "{from} to {to}",
    # --- stages ---
    # `stage.*` is the reader's word for one run between two stops. `leg` stays the
    # data's word — journey.legs, RouteLeg, RoutePoint.leg, the leg column in
    # places.csv — and this table is the one place the two vocabularies meet. "Leg" is
    # ordinary English for it and opaque to anyone who did not grow up with it; "stage"
    # is the older word, as in a stagecoach, and says what it means.
    "stage.days": "{n} days",
    "stage.day": "day {n}",
    "stage.count": "{n} of the eight stages",
    "stage.via": "The table names {places} along the way",
    # --- transport modes ---
    "mode.steamer": "steamer",
    "mode.railway": "rail",
    "mode.elephant": "elephant",
    "mode.sledge": "sledge",
    "mode.carriage": "carriage",
    "mode.on_foot": "on foot",
    "mode.other": "other",
    # --- the schedule chip ---
    "schedule.ahead": "ahead of the itinerary",
    "schedule.behind": "behind the itinerary",
    "schedule.on_time": "on time",
    "schedule.unknown": "the chapter does not say",
    # --- the three tracks ---
    "track.stated": "stated in chapter {n}",
    "track.carried": "carried from chapter {n}",
    "track.inferred": "inferred from where the chapter is set",
    "track.absent": "{who} has not appeared yet",
    # --- places ---
    "place.doubtful": "resolved at {score}, below the {threshold} we trust",
    "place.renamed": "{old}, now {new}",
    "place.chapters": "named in chapters {numbers}",
    # --- the key beside the globe ---
    "legend.heading": "The key",
    # --- the itinerary list ---
    "itinerary.heading": "The itinerary",
    "itinerary.note": (
        "The same nine stops the globe draws, as a list — which is also how the page "
        "reads with the pictures switched off."
    ),
    # --- honesty, above the fold ---
    "arc.schematic": (
        "The lines are great circles: the shortest path over a sphere between the "
        "stops Fogg's table names, not the route the ships and trains took. The Suez "
        "stage "
        "went through a canal, and the Indian and American stages by rail."
    ),
    "prov.line": (
        "{plotted} places are drawn, of {total} the book names. {confirmed} have been "
        "checked by a human."
    ),
    "prov.doubtful": "{n} of {located} resolutions scored below {threshold}.",
    "prov.unlocated": (
        "{n} names have no coordinate at all — some, like Kholby, have no modern place "
        "to match."
    ),
    "prov.rings": "A dot with a broken ring is a place nobody has checked yet.",
    # --- the closing section ---
    # Split into a label and a body wherever the paragraph opens with a bolded word,
    # because the bold is markup and markup does not go in a string.
    "about.heading": "About the project",
    "about.dataset": (
        "The novel already contains its own dataset. Fogg keeps an itinerary with a "
        "column of gains and losses, and the wager is a route as well as a deadline — "
        "so the job here is not to impose structure on the text but to make the text's "
        "own structure visible."
    ),
    "about.pipeline": (
        "The pipeline splits the work the way it should be split. Deterministic work "
        "goes to code: fetching, slicing, joining, geocoding, drawing. Reading "
        "comprehension goes to a language model with a human check: who is where, "
        "when, and by what means. The join between the two halves is an evidence "
        "quote. Every "
        "extracted fact carries a verbatim quotation from its chapter, and a validator "
        "greps each one back against the source, so verification is a string match "
        "rather than a re-read."
    ),
    "about.sources.label": "Sources.",
    "about.sources": (
        "Text: Project Gutenberg #103, public domain. Places: Wikidata, CC0, resolved "
        "and then reviewed by hand. Coastline: Natural Earth 1:110m land, public "
        "domain. Extraction: Google Gemini, with every answer checked against the "
        "chapter it came from."
    ),
    "about.method.label": "Method.",
    "about.method": (
        "The globe is an orthographic projection drawn with d3-geo, which clips at the "
        "horizon — so a journey round the world closes on itself with none of the "
        "seam-splitting a flat map needs. The arcs are great circles between the stops "
        "the book names, and the page says so rather than implying a survey."
    ),
    "footer.contact": "hello@crowintelligence.org",
    "footer.licence": "CC BY-NC-SA 4.0",
    "footer.text": "Text: Project Gutenberg #103, public domain",
    "footer.gazetteer": "Places: Wikidata",
    "footer.coastline": "Coastline: Natural Earth, public domain",
    "footer.fonts": "Type: Playfair Display and EB Garamond, SIL Open Font License",
}


def placeholder_names(text: str) -> frozenset[str]:
    """The ``{name}`` slots a string expects to be filled.

    Args:
        text: A string from the table.

    Returns:
        The placeholder names, without braces.

    Examples:
        >>> sorted(placeholder_names("Chapter {n} of {total}"))
        ['n', 'total']
        >>> placeholder_names("Next chapter")
        frozenset()
    """
    return frozenset(_PLACEHOLDER.findall(text))


def check_strings(strings: dict[str, str] | None = None) -> list[str]:
    """Everything wrong with the table, phrased so each line names its own fix.

    Three checks, and each one catches something a reader would otherwise see. Markup in
    a value would reach the page as literal angle brackets, because the page sets
    ``textContent`` and never ``innerHTML`` — which is deliberate, and is why the rule
    exists. An empty value renders as a gap with no clue where it came from. And a
    malformed placeholder — ``{n`` for ``{n}``, or a stray brace — is printed verbatim,
    which is how a day count ends up reading "day {n".

    What cannot be checked here is whether a call site actually supplies each
    placeholder; that is what ``tests/test_web_page.py`` greps for.

    Args:
        strings: The table. Defaults to :data:`STRINGS`.

    Returns:
        The problems, sorted. Empty means the table is sound.

    Examples:
        A tag that would print as angle brackets:

        >>> check_strings({"x": "see <a href='#'>this</a>"})
        ["'x' contains markup — split it into two keys, or do without"]

        A brace that never closes:

        >>> check_strings({"day": "day {n"})
        ["'day' has an unmatched brace — a placeholder is printed as written"]

        And a table with nothing wrong:

        >>> check_strings({"day": "Day {n} of {total}"})
        []
    """
    table = STRINGS if strings is None else strings
    problems: list[str] = []
    for key, value in table.items():
        if _MARKUP.search(value):
            problems.append(
                f"{key!r} contains markup — split it into two keys, or do without"
            )
        if not value.strip():
            problems.append(f"{key!r} is empty — a blank renders as a gap with no clue")
        if "{" in _PLACEHOLDER.sub("", value) or "}" in _PLACEHOLDER.sub("", value):
            problems.append(
                f"{key!r} has an unmatched brace — a placeholder is printed as written"
            )
    return sorted(problems)


def strings_payload(strings: dict[str, str] | None = None) -> dict[str, object]:
    """The table as ``web/data/strings.json``.

    Args:
        strings: The table. Defaults to :data:`STRINGS`.

    Returns:
        The payload: which language this is, and the strings.

    Examples:
        >>> payload = strings_payload({"a": "A"})
        >>> payload["language"], payload["strings"]
        ('en', {'a': 'A'})
    """
    return {
        "generated_by": "scripts/08_dashboard.py",
        "language": LANGUAGE,
        "strings": dict(STRINGS if strings is None else strings),
    }
