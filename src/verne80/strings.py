r"""Every user-facing string the page shows, in one place, keyed by language.

The house rule says keep these centralised so that a Hungarian version is a translation
job and not a rewrite. No Crow project has actually done it — the lyrics dashboard has
its Hungarian prose typed directly into the markup — so this is the precedent rather
than a copy of one.

Two halves, and only one of them is here.

**Chrome** — buttons, headings, labels, the provenance sentence — lives in
:data:`CATALOGUE`. It is Python rather than a hand-written JavaScript object so that
:func:`check_catalogue` can assert the two things that actually break a translation:
that no key has gone missing, and that a translated string still has the same
placeholders as the English it replaced. A translator who drops ``{n}`` from a day count
produces a page that says "day of" and no test would otherwise notice.

**Content** — the chapter summaries — is language-keyed inside the data instead, as
``summary.en.hover``. Adding Hungarian there is an edit to a JSON file: no markup
changes, no code changes, nothing to re-wire.

Two conventions that are load-bearing:

**No HTML in a string, ever.** A catalogue entry carrying ``<a href=…>`` is an injection
hole and an untranslatable blob at the same time. A sentence that needs a link is split
into a ``.before`` and an ``.after`` key, and the anchor is built in JavaScript between
them. :func:`check_catalogue` enforces this.

**A place's printed name is not translatable.** ``name_in_text`` is a quotation from the
English text of Gutenberg #103. The Hungarian translation of the novel spells its places
differently, and asserting those spellings without the Hungarian text in hand would be
inventing data to fill a schema. So the Hungarian build shows the same
``name_in_text``, alongside the modern name, and translates the prose around it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

__all__ = [
    "CATALOGUE",
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "catalogue_payload",
    "check_catalogue",
    "missing_keys",
    "placeholder_names",
]

DEFAULT_LANGUAGE = "en"

# Offered in the language picker. Hungarian is listed with an empty catalogue rather
# than a machine translation: an empty key falls back to English visibly, where a
# guessed one reads as finished work nobody wrote.
LANGUAGES: tuple[tuple[str, str], ...] = (("en", "English"), ("hu", "Magyar"))

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_MARKUP = re.compile(r"<[^>]+>")

CATALOGUE: dict[str, dict[str, str]] = {
    "en": {
        # --- the page itself ---
        "site.title": "Around the World in Eighty Days",
        "site.subtitle": "Fogg's itinerary, on the globe he went round",
        "site.description": (
            "The route and calendar of Jules Verne's 1872 novel, extracted from the "
            "text and shown on a rotating globe."
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
        "globe.aria": "A globe showing Phileas Fogg's route around the world.",
        "globe.hint": "Drag to turn the globe.",
        "globe.rotate.pause": "Stop turning",
        "globe.rotate.play": "Turn slowly",
        # --- the chapter stepper ---
        "chapter.heading": "Chapter {n}. {title}",
        "chapter.of": "Chapter {n} of {total}",
        "chapter.next": "Next chapter",
        "chapter.previous": "Previous chapter",
        # --- legs ---
        "leg.days": "{n} days",
        "leg.table_says": "Fogg's own table says days {from} to {to}",
        "leg.via": "The table names {places} along the way",
        "leg.heading": "{origin} to {destination}",
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
        "place.unchecked": "nobody has checked this yet",
        "place.doubtful": "resolved at {score}, below the {threshold} we trust",
        "place.renamed": "{old}, now {new}",
        "place.chapters": "named in chapters {numbers}",
        "place.unlocated": "no modern place has been matched to this name",
        # --- layers ---
        "layer.heading": "What to show",
        "layer.itinerary": "The route",
        "layer.interior": "Places inside London",
        "layer.named": "Named in the book, not yet classified",
        "layer.named.note": (
            "These are every other place the novel names. None has been reviewed, and "
            "some are resolved to the wrong continent."
        ),
        # --- the itinerary list ---
        "itinerary.heading": "The itinerary",
        "itinerary.note": (
            "The same nine stops the globe draws, as a list — which is also how the "
            "page reads with the pictures switched off."
        ),
        # --- honesty, above the fold ---
        "arc.schematic": (
            "The lines are great circles: the shortest path over a sphere between the "
            "stops Fogg's table names, not the route the ships and trains took. The "
            "Suez leg went through a canal, and the Indian and American legs by rail."
        ),
        "prov.line": (
            "{plotted} places are drawn, of {total} the book names. {confirmed} have "
            "been checked by a human."
        ),
        "prov.doubtful": "{n} of {located} resolutions scored below {threshold}.",
        "prov.unlocated": (
            "{n} names have no coordinate at all — some, like Kholby, have no modern "
            "place to match."
        ),
        "prov.rings": "A pin with a broken ring is one nobody has checked.",
        # --- the closing section ---
        "about.heading": "About the project",
        "footer.contact": "hello@crowintelligence.org",
        "footer.licence": "CC BY-NC-SA 4.0",
        "footer.text": "Text: Project Gutenberg #103, public domain",
        "footer.gazetteer": "Places: Wikidata",
        "footer.coastline": "Coastline: Natural Earth, public domain",
        "footer.fonts": "Type: Playfair Display and EB Garamond, SIL Open Font License",
    },
    # Empty on purpose. check_catalogue reports every key as the translator's worklist,
    # and until they are filled the page falls back to English one key at a time.
    "hu": {},
}


def placeholder_names(text: str) -> frozenset[str]:
    """The ``{name}`` slots a string expects to be filled.

    Args:
        text: A catalogue string.

    Returns:
        The placeholder names, without braces.

    Examples:
        >>> sorted(placeholder_names("Chapter {n} of {total}"))
        ['n', 'total']
        >>> placeholder_names("Next chapter")
        frozenset()
    """
    return frozenset(_PLACEHOLDER.findall(text))


def missing_keys(
    catalogue: Mapping[str, Mapping[str, str]] | None = None,
    reference: str = DEFAULT_LANGUAGE,
) -> dict[str, list[str]]:
    """What each language still has to translate.

    Args:
        catalogue: The catalogue. Defaults to :data:`CATALOGUE`.
        reference: The language every other is measured against. Default ``"en"``.

    Returns:
        Language to its untranslated keys, sorted. A language with nothing outstanding
        is omitted, so an empty result means the catalogue is complete.

    Examples:
        >>> missing_keys({"en": {"a": "A", "b": "B"}, "hu": {"a": "Á"}})
        {'hu': ['b']}
        >>> missing_keys({"en": {"a": "A"}, "hu": {"a": "Á"}})
        {}
    """
    source = catalogue if catalogue is not None else CATALOGUE
    expected = set(source.get(reference, {}))
    out = {}
    for language, entries in source.items():
        if language == reference:
            continue
        outstanding = sorted(expected - set(entries))
        if outstanding:
            out[language] = outstanding
    return out


def check_catalogue(
    catalogue: Mapping[str, Mapping[str, str]] | None = None,
    reference: str = DEFAULT_LANGUAGE,
) -> list[str]:
    """Everything wrong with a catalogue, phrased so each line names its own fix.

    Checks the three things that break a translated page and that nothing else would
    catch: a key nobody has ever written in the reference language, a translation whose
    placeholders no longer match the original, and markup smuggled into a string.

    A missing translation is not a problem — it is expected, it falls back, and
    :func:`missing_keys` is where it gets reported.

    Args:
        catalogue: The catalogue. Defaults to :data:`CATALOGUE`.
        reference: The language every other is measured against. Default ``"en"``.

    Returns:
        The problems, sorted. Empty means the catalogue is sound.

    Examples:
        A translation that has lost a placeholder:

        >>> check_catalogue({"en": {"day": "Day {n}"}, "hu": {"day": "Nap"}})
        ["hu 'day' is missing the placeholder {n}"]

        A string with a tag in it:

        >>> check_catalogue({"en": {"x": "see <a href='#'>this</a>"}})
        ["en 'x' contains markup — split it into .before and .after keys instead"]

        And one with nothing wrong:

        >>> check_catalogue({"en": {"day": "Day {n}"}, "hu": {"day": "{n}. nap"}})
        []
    """
    source = catalogue if catalogue is not None else CATALOGUE
    problems: list[str] = []
    expected = source.get(reference, {})

    for language, entries in source.items():
        for key, value in entries.items():
            if _MARKUP.search(value):
                problems.append(
                    f"{language} {key!r} contains markup — split it into .before and "
                    ".after keys instead"
                )
            if language == reference:
                continue
            if key not in expected:
                problems.append(
                    f"{language} {key!r} has no {reference} original — either it is a "
                    f"typo or the {reference} key was deleted"
                )
                continue
            wanted = placeholder_names(expected[key])
            got = placeholder_names(value)
            for name in sorted(wanted - got):
                problems.append(
                    f"{language} {key!r} is missing the placeholder {{{name}}}"
                )
            for name in sorted(got - wanted):
                problems.append(
                    f"{language} {key!r} has a placeholder {{{name}}} the "
                    f"{reference} original does not"
                )
    return sorted(problems)


def catalogue_payload(
    catalogue: Mapping[str, Mapping[str, str]] | None = None,
    languages: Sequence[tuple[str, str]] = LANGUAGES,
) -> dict[str, object]:
    """The catalogue as ``web/data/strings.json``.

    Args:
        catalogue: The catalogue. Defaults to :data:`CATALOGUE`.
        languages: Code and label for each language the picker offers.

    Returns:
        The payload: the default language, the offered languages, and one object of
        strings per language.

    Contract:
        - Every language in ``languages`` has an object, empty if untranslated, so the
          front end never has to distinguish "not offered" from "not yet written".

    Examples:
        >>> payload = catalogue_payload({"en": {"a": "A"}}, (("en", "English"),))
        >>> payload["default"], payload["en"]
        ('en', {'a': 'A'})
    """
    source = catalogue if catalogue is not None else CATALOGUE
    payload: dict[str, object] = {
        "generated_by": "scripts/08_dashboard.py",
        "default": DEFAULT_LANGUAGE,
        "languages": [{"code": code, "label": label} for code, label in languages],
    }
    for code, _ in languages:
        payload[code] = dict(source.get(code, {}))
    return payload
