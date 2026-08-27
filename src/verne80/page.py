r"""Build the page, so that it says what it says before any script runs.

A crawler that executes no JavaScript used to read **107 words** of this page: the
navigation, the skip links and the labels on three buttons. Not the subtitle, not the
About section, not one of the thirty-seven chapter summaries. Thirteen of the page's
``data-i18n`` elements were empty in the markup and filled only at run time, and the
summaries — two thousand nine hundred words — appeared in the file exactly nowhere.
Google renders JavaScript; the crawlers that feed language models generally do not. So
the page was, to most of them, a menu.

This module is the fix, and it is nothing cleverer than putting the words in the file.

**Two ways of saying the same thing, and the duplication is the point.** A template
element carries both the attribute the run-time filler uses and an explicit token::

    <p class="note" data-i18n="chapters.note">{{ strings.chapters.note }}</p>

:func:`check_template` refuses to build if those two ever disagree. The alternative —
finding ``data-i18n`` elements by pattern and filling them — fails silently: reorder an
attribute and the fill simply stops happening, with nothing said, which is precisely the
bug being closed here. Two statements that must agree beat one statement that must be
correct.

**Three namespaces.** ``{{ strings.KEY }}`` is a string from the table, escaped.
``{{ page.NAME }}`` is a fact about the publication — its address, its dates — escaped.
``{{ block.NAME }}`` is markup this module built, escaped leaf by leaf at construction.
Nothing else is substituted, and a token naming something absent is a build failure
rather than a literal ``{{ strings.nope }}`` on the page.

**No timestamps.** :data:`~verne80.strings.UPDATED` is hand-bumped. A generated file
whose content moves with the clock diffs on every rebuild, and the freshness test would
then fail on every day but the one it was written.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from verne80.strings import (
    LANGUAGE,
    PUBLISHED,
    SITE_URL,
    STRINGS,
    UPDATED,
)

__all__ = [
    "CHAPTERS_TEMPLATE",
    "CHAPTERS_WORD_FLOOR",
    "TEMPLATE",
    "WORD_FLOOR",
    "check_template",
    "fill",
    "render",
    "render_chapters",
    "visible_text",
]

TEMPLATE = Path(__file__).with_name("page_template.html")
CHAPTERS_TEMPLATE = Path(__file__).with_name("chapters_template.html")

# The floors each page must clear with scripting switched off, and the reason there are
# two of them.
#
# The thirty-seven summaries were written out below the globe for one release. They came
# to 5,566 words — ninety per cent of that page — and made it unreadable for the person
# it was built for. They are their own page now, and the numbers follow: the globe keeps
# its title, subtitle, headings, itinerary and closing section, about 640 words; the
# summaries page carries about 5,600.
#
# Each floor sits far enough below its page that ordinary editing never reaches it, and
# far enough above what a failed block would leave that the failure is unambiguous.
# Deliberately blunt: neither notices one chapter going missing, and the test that names
# every chapter is what does.
WORD_FLOOR = 400
CHAPTERS_WORD_FLOOR = 3000

# The novel on Wikidata. Verified rather than assumed: Q1219561 is the literary work,
# its author is Q33977 (Jules Verne), it is dated 1872, and its title is recorded as
# "Le Tour du monde en quatre-vingts jours". The films and the stage play have their own
# identifiers and are not this. One wrong identifier in `sameAs` is worse than none.
NOVEL_QID = "https://www.wikidata.org/wiki/Q1219561"
AUTHOR_QID = "https://www.wikidata.org/wiki/Q33977"
GUTENBERG = "https://www.gutenberg.org/ebooks/103"
LICENCE = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
ORGANISATION = "https://crowintelligence.org/#organization"

# The order a chapter's places are read out in: where the party is, then forward, then
# back, then the two that are neither. Each group is led by its own `place.class.*`
# string, which were written as clauses and so read as clauses.
CLASS_ORDER = ("here", "future", "past", "cyclic", "off_route", "unknown")

_STRING_TOKEN = re.compile(r"\{\{\s*strings\.([a-zA-Z0-9_.]+)\s*\}\}")
_PAGE_TOKEN = re.compile(r"\{\{\s*page\.([a-zA-Z0-9_]+)\s*\}\}")
_BLOCK_TOKEN = re.compile(r"\{\{\s*block\.([a-zA-Z0-9_]+)\s*\}\}")
_ANY_TOKEN = re.compile(r"\{\{[^}]*\}\}")

# An element carrying data-i18n, its attributes, and its body. Non-greedy, which is
# correct for this markup: the one nested case is a <strong> and a <span> inside a <p>
# that carries no attribute of its own.
_I18N_BODY = re.compile(r"<(\w+)([^>]*\bdata-i18n=\"([^\"]+)\"[^>]*)>(.*?)</\1>", re.S)
_I18N_ATTR = re.compile(r"data-i18n-(label|content)=\"([^\"]+)\"")


def fill(key: str, **values: object) -> str:
    """One string from the table, with its ``{placeholder}`` slots filled.

    A five-line mirror of ``t()`` in ``web/i18n.js``, and it has to stay one: two
    implementations of the same substitution drift, and the drift shows up as a literal
    brace on a page nobody is looking at.

    Args:
        key: A key in :data:`~verne80.strings.STRINGS`.
        **values: The slots to fill.

    Returns:
        The filled string. A slot with no value is left as written, which is visible.

    Raises:
        KeyError: If the key is not in the table. A missing string is a build failure,
            not a page that says ``chapter.of``.

    Examples:
        >>> fill("chapter.of", n=12, total=37)
        'Chapter 12 of 37'
        >>> fill("stage.days", n=7)
        '7 days'
    """
    text = STRINGS[key]
    return re.sub(
        r"\{(\w+)\}",
        lambda found: (
            str(values[found.group(1)]) if found.group(1) in values else found.group(0)
        ),
        text,
    )


def visible_text(page: str) -> str:
    """What a crawler that runs no JavaScript actually reads.

    The order matters, and each step removes something that would otherwise make the
    count a lie.

    1. ``<script>`` and ``<style>``, contents and all. The structured data is real and
       is asserted by its own test, but it is not prose, and nine hundred words of it
       would flatter the number by a third.
    2. The whole ``<head>``. The title and the description are read by a crawler and are
       checked elsewhere; what this measures is body copy, which is the thing that was
       missing.
    3. Comments. This repository comments its markup heavily and none of it is for a
       reader; counting it would be measuring our own explanations.
    4. Every remaining tag, replaced by a space rather than deleted, so ``a</p><p>b``
       counts as two words rather than one.

    ``<noscript>`` is kept, because a reader with scripting off sees it, which is the
    entire reason it is there.

    Args:
        page: The rendered HTML.

    Returns:
        The words, whitespace collapsed. A token counts only if it contains a letter or
        a digit, so the em dashes and middots that separate this page's clauses are
        punctuation rather than vocabulary.

    Examples:
        >>> visible_text("<head><title>Hidden</title></head><p>Two words</p>")
        'Two words'
        >>> visible_text("<p>a</p><p>b</p>")
        'a b'
        >>> visible_text("<p>Kept <!-- dropped --> <script>alsoDropped()</script></p>")
        'Kept'
    """
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
    text = re.sub(r"<head\b.*?</head>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    words = html.unescape(text).split()
    return " ".join(word for word in words if any(c.isalnum() for c in word))


def check_template(template: str | None = None) -> list[str]:
    """Everything wrong with the template, phrased so each line names its own fix.

    Two rules, and both catch a page that renders wrongly rather than one that fails to
    render at all — which is the only kind of breakage worth a check here.

    A ``data-i18n`` element whose body is not that key's own token is an element the
    build leaves empty and only JavaScript fills. That was true of thirteen of them, and
    it is the bug this module exists to close.

    A token naming a key the table does not define reaches the page as a literal
    ``{{ strings.nope }}``.

    Args:
        template: The template source. Defaults to the shipped one.

    Returns:
        The problems, sorted. Empty means the template is sound.

    Examples:
        >>> check_template('<p data-i18n="site.title">{{ strings.site.title }}</p>')
        []

        An element the build would leave empty:

        >>> check_template('<p data-i18n="site.title"></p>')
        ["'site.title' is filled only by JavaScript — its body should be the token"]

        And a token with no string behind it:

        >>> check_template("<p>{{ strings.nope }}</p>")
        ["'nope' has no string in the table — it would print as a token"]
    """
    source = TEMPLATE.read_text(encoding="utf-8") if template is None else template
    problems: list[str] = []

    for _, attributes, key, body in _I18N_BODY.findall(source):
        wanted = f"{{{{ strings.{key} }}}}"
        if body.strip() != wanted:
            problems.append(
                f"{key!r} is filled only by JavaScript — its body should be the token"
            )
        del attributes

    for kind, key in _I18N_ATTR.findall(source):
        attribute = "aria-label" if kind == "label" else "content"
        wanted = f'{attribute}="{{{{ strings.{key} }}}}"'
        if wanted not in source:
            problems.append(
                f"{key!r} sets {attribute} only at run time — write the token into it"
            )

    for key in _STRING_TOKEN.findall(source):
        if key not in STRINGS:
            problems.append(
                f"{key!r} has no string in the table — it would print as a token"
            )
    return sorted(set(problems))


def render(
    chapters: Mapping[str, Any],
    journey: Mapping[str, Any],
    places: Mapping[str, Any],
    provenance: Mapping[str, Any],
    template: str | None = None,
) -> str:
    """The finished page.

    Args:
        chapters: ``chapters.json``, as loaded.
        journey: ``journey.json``.
        places: ``places.json``.
        provenance: ``provenance.json``.
        template: The template source. Defaults to the shipped one.

    Returns:
        The HTML.

    Raises:
        ValueError: If the template is unsound, or if a token survives substitution. A
            page with ``{{ strings.nope }}`` printed on it should never be written to
            disk, let alone committed.

    Contract:
        - Every ``data-i18n`` element carries its string as text.
        - Every chapter's title and summary appear in the output.
        - No timestamp: the same inputs always give the same bytes.
    """
    source = TEMPLATE.read_text(encoding="utf-8") if template is None else template
    problems = check_template(source)
    if problems:
        raise ValueError("; ".join(problems))

    blocks = {
        "jsonld": _jsonld(provenance),
        "itinerary": _itinerary(journey, places),
        "checked": _escape(
            fill(
                "about.checked",
                plotted=provenance["places"]["plotted"],
                total=provenance["places"]["total"],
                doubtful=provenance["places"]["doubtful"],
                threshold=provenance["doubtful_below"],
            )
        ),
    }
    facts = {
        "url": SITE_URL,
        "card": SITE_URL + "assets/og.png",
        "language": LANGUAGE,
        "published": PUBLISHED,
        "updated": UPDATED,
    }

    return _substitute(source, facts, blocks)


def render_chapters(chapters: Mapping[str, Any], template: str | None = None) -> str:
    """The thirty-seven summaries, as a page of their own.

    Everything the globe's panel says about a chapter in passing, written down: what
    happens, who is there, where it reaches, how they travel. It carries no
    JavaScript, which makes it fast and takes a category of breakage off it entirely.

    Args:
        chapters: ``chapters.json``, as loaded.
        template: The template source. Defaults to the shipped one.

    Returns:
        The HTML.

    Raises:
        ValueError: If the template is unsound, or a token survives substitution.

    Contract:
        - Every chapter's title and summary appear in the output, anchored ``#ch-N``.
        - Every chapter links back to the same chapter on the globe.
    """
    source = (
        CHAPTERS_TEMPLATE.read_text(encoding="utf-8") if template is None else template
    )
    problems = check_template(source)
    if problems:
        raise ValueError("; ".join(problems))

    facts = {
        # One level down, so the shared stylesheet, the fonts and the payloads are all
        # reached with `..`. The consent script stays root-absolute: it is the site's
        # file and resolves from the domain root wherever this page sits.
        "url": SITE_URL + "chapters/",
        "home": SITE_URL,
        "base": "..",
        "card": SITE_URL + "assets/og.png",
        "language": LANGUAGE,
        "published": PUBLISHED,
        "updated": UPDATED,
    }
    blocks = {"jsonld": _chapters_jsonld(), "chapters": _chapter_sections(chapters)}
    return _substitute(source, facts, blocks)


def _substitute(
    source: str, facts: Mapping[str, str], blocks: Mapping[str, str]
) -> str:
    """Fill the three namespaces, and refuse a page with a token left in it."""
    page = _STRING_TOKEN.sub(lambda m: _escape(STRINGS[m.group(1)]), source)
    page = _PAGE_TOKEN.sub(lambda m: _escape(facts[m.group(1)]), page)
    page = _BLOCK_TOKEN.sub(lambda m: blocks[m.group(1)], page)

    left = _ANY_TOKEN.findall(page)
    if left:
        raise ValueError(f"tokens survived substitution: {sorted(set(left))}")
    return page


def _escape(value: object) -> str:
    """Text on its way into markup.

    ``&``, ``<``, ``>`` and the double quote — and deliberately **not** the apostrophe.
    ``html.escape(quote=True)`` would turn every one into ``&#x27;``, and this page is
    written in English about a man called Fogg: the generated file would carry a hundred
    of them, in prose a person is meant to read in a diff. Every attribute here is
    delimited with a double quote, so escaping the single one protects nothing.

    ``check_strings`` already forbids markup in a string, so in practice this touches
    almost nothing. The curly quotes, em dashes and middots the page is full of pass
    through as UTF-8, which is what the file already did.
    """
    return html.escape(str(value), quote=False).replace('"', "&quot;")


def _chapter_sections(chapters: Mapping[str, Any]) -> str:
    """The thirty-seven chapters, written out.

    This is the block the whole module exists for. Each chapter is an ``<article>`` with
    a heading, the summary as a paragraph, and a description list of four facts: who is
    in it, who is spoken of, where it reaches, and how they travel.

    Places are grouped by where they sit relative to the party rather than listed one by
    one — chapter 29 names twenty-four of them, and twenty-four parentheses is a data
    dump rather than a sentence.

    Nothing here carries ``data-i18n``: JavaScript never rebuilds this block, so there
    is no reason to make ``localise()`` walk a hundred and fifty extra nodes at load.
    """
    out = []
    for entry in chapters["chapters"]:
        number = entry["chapter"]
        facts = [
            (STRINGS["people.present.heading"], _cast(entry["present"])),
            (
                STRINGS["people.elsewhere.heading"],
                _cast(entry["named_elsewhere"]) or STRINGS["people.elsewhere.none"],
            ),
            (STRINGS["place.heading"], _places(entry["places"])),
            (STRINGS["transport.heading"], _travel(entry["transport"])),
        ]
        rows = "\n".join(
            f"    <dt>{_escape(label)}</dt>\n    <dd>{_escape(value)}</dd>"
            for label, value in facts
            if value
        )
        out.append(
            f'<article class="chapter" id="ch-{number}">\n'
            f'  <h3><span class="chapter-number tabular">{number}</span> '
            f"{_escape(entry['title'])}</h3>\n"
            f"  <p>{_escape(entry['summary']['detail'])}</p>\n"
            f'  <dl class="chapter-facts">\n{rows}\n  </dl>\n'
            f'  <p class="chapter-back">'
            f'<a class="to-globe" href="../#ch-{number}" '
            f'data-chapter="{number}">'
            f"{_escape(fill('chapter.on_globe', n=number))}</a></p>\n"
            f"</article>"
        )
    return "\n".join(out)


def _cast(people: Sequence[Mapping[str, Any]]) -> str:
    """Named people, then the ones the book identifies only by what they are.

    Kept apart because merging them would assert that the engineer of one chapter is the
    engineer of another. There are nine engineers in this book and they are nine men.
    """
    named = [one["display"] for one in people if one["kind"] == "person"]
    roles = [one["display"] for one in people if one["kind"] == "role"]
    parts = []
    if named:
        parts.append(", ".join(named) + ".")
    if roles:
        parts.append(fill("people.by_role", names=", ".join(roles)) + ".")
    return " ".join(parts)


def _places(places: Sequence[Mapping[str, Any]]) -> str:
    """A chapter's places, grouped by where they sit relative to the party."""
    grouped: dict[str, list[str]] = {}
    for place in places:
        grouped.setdefault(str(place["class"]), []).append(str(place["name_in_text"]))
    parts = [
        f"{STRINGS[f'place.class.{name}']}, {', '.join(sorted(grouped[name]))}"
        for name in CLASS_ORDER
        if grouped.get(name)
    ]
    return "; ".join(parts) + "." if parts else ""


def _travel(transport: Sequence[Mapping[str, Any]]) -> str:
    """How a chapter's journeys are made, with the vessel where the book names one."""
    if not transport:
        return STRINGS["transport.none"]
    parts = []
    for item in transport:
        label = STRINGS[f"mode.{item['mode']}"]
        parts.append(f"{label}, {item['vessel']}" if item.get("vessel") else label)
    seen = list(dict.fromkeys(parts))
    return "; ".join(seen).capitalize() + "."


def _itinerary(journey: Mapping[str, Any], places: Mapping[str, Any]) -> str:
    """The nine stops, in the file rather than assembled at load.

    The same list ``app.js`` builds, built here too, so that a reader with scripting off
    and a crawler that never runs any both get the spine of the journey.
    """
    named = {place["key"]: place for place in places["places"]}
    out = []
    for position, node in enumerate(journey["nodes"]):
        day = _escape(fill("stage.day", n=node["day"]))
        line = (
            f'  <li><span class="day-badge tabular">{day}</span>'
            f'<span class="stop-name">{_escape(node["name_in_text"])}</span>'
        )
        modern = named.get(node["key"], {})
        if node["name_changed"] and node["modern_name"] != node["name_in_text"]:
            renamed = fill(
                "place.renamed", old=node["name_in_text"], new=node["modern_name"]
            )
            line += f'<span class="renamed"> — {_escape(renamed)}</span>'
        del modern
        leg = journey["legs"][position] if position < len(journey["legs"]) else None
        if leg:
            days = fill("stage.days", n=leg["days"])
            via = (
                " " + fill("stage.via", places=", ".join(leg["via_as_written"])) + "."
                if leg["via_as_written"]
                else ""
            )
            onward = f"{leg['mode_as_written']}, {days}.{via}"
            line += f'\n    <p class="onward">{_escape(onward)}</p>'
        out.append(line + "</li>")
    return "\n".join(out)


def _chapters_jsonld() -> str:
    """The summaries page, said to be part of the globe rather than a rival to it.

    Lean on purpose. It repeats the book it is about and names its parent, and it does
    not repeat the dataset: one page should claim that, and it is the one carrying it.
    """
    graph = [
        {
            "@type": "WebPage",
            "@id": SITE_URL + "chapters/#webpage",
            "url": SITE_URL + "chapters/",
            "name": STRINGS["chapters.page_title"],
            "description": STRINGS["chapters.page_description"],
            "inLanguage": LANGUAGE,
            "datePublished": PUBLISHED,
            "dateModified": UPDATED,
            "license": LICENCE,
            "isPartOf": {"@id": SITE_URL + "#webpage"},
            "author": {"@id": ORGANISATION},
            "publisher": {"@id": ORGANISATION},
            "breadcrumb": {"@id": SITE_URL + "chapters/#breadcrumb"},
            "about": {"@id": SITE_URL + "#book"},
        },
        {
            "@type": "BreadcrumbList",
            "@id": SITE_URL + "chapters/#breadcrumb",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "Crow Intelligence",
                    "item": "https://crowintelligence.org/",
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": STRINGS["site.title"],
                    "item": SITE_URL,
                },
                {
                    "@type": "ListItem",
                    "position": 3,
                    "name": STRINGS["chapters.page_heading"],
                },
            ],
        },
        {
            "@type": "Organization",
            "@id": ORGANISATION,
            "name": "Crow Intelligence",
            "url": "https://crowintelligence.org/",
        },
    ]
    body = json.dumps(
        {"@context": "https://schema.org", "@graph": graph},
        ensure_ascii=False,
        indent=2,
    )
    return f'<script type="application/ld+json">\n{body}\n</script>'


def _jsonld(provenance: Mapping[str, Any]) -> str:
    """The structured data, built as a dictionary so it cannot be malformed.

    A ``@graph`` rather than a single node, because the page is several things at once
    and saying so precisely is the only reason structured data exists: it is a web page,
    it is about a novel, and it publishes a dataset.

    The organisation node is a stub carrying the site's own identifier, so that it
    merges with the fuller record the rest of the site emits rather than dangling or
    competing with it. Cross-page identifier resolution is guaranteed by no consumer.

    ``distribution`` lists only the four payloads this project made. The coastline and
    the modern borders are Natural Earth and the 1880 borders are GPL-3.0; naming them
    inside a dataset declared under a Creative Commons licence would be a false claim
    about somebody else's work.
    """
    counts = provenance["places"]
    dataset_description = (
        "Phileas Fogg's itinerary as nine stops and eight stages, with the days the "
        "novel's own table budgets for each; every place name the 37 chapters use, "
        "resolved against Wikidata where a match exists and held back with a stated "
        f"reason where it does not; and per-chapter summaries, cast and positions. "
        f"{counts['total']} place names, {counts['plotted']} with coordinates, "
        f"{counts['confirmed']} confirmed by a human."
    )
    graph = [
        {
            "@type": "WebPage",
            "@id": SITE_URL + "#webpage",
            "url": SITE_URL,
            "name": STRINGS["site.page_title"],
            "description": STRINGS["site.description"],
            "inLanguage": LANGUAGE,
            "datePublished": PUBLISHED,
            "dateModified": UPDATED,
            "license": LICENCE,
            "author": {"@id": ORGANISATION},
            "publisher": {"@id": ORGANISATION},
            "breadcrumb": {"@id": SITE_URL + "#breadcrumb"},
            "primaryImageOfPage": {"@id": SITE_URL + "#card"},
            "about": [{"@id": SITE_URL + "#book"}, {"@id": SITE_URL + "#dataset"}],
        },
        {
            "@type": "ImageObject",
            "@id": SITE_URL + "#card",
            "contentUrl": SITE_URL + "assets/og.png",
            "width": 1200,
            "height": 630,
            "caption": STRINGS["site.card_alt"],
        },
        {
            "@type": "Book",
            "@id": SITE_URL + "#book",
            "name": "Around the World in Eighty Days",
            "alternateName": "Le Tour du monde en quatre-vingts jours",
            "author": {
                "@type": "Person",
                "name": "Jules Verne",
                "sameAs": AUTHOR_QID,
            },
            "datePublished": "1872",
            "inLanguage": "fr",
            "sameAs": [NOVEL_QID, GUTENBERG],
        },
        {
            "@type": "Dataset",
            "@id": SITE_URL + "#dataset",
            "name": ("Around the World in Eighty Days — route, places and chapters"),
            "description": dataset_description,
            "url": SITE_URL,
            "mainEntityOfPage": {"@id": SITE_URL + "#webpage"},
            "isBasedOn": {"@id": SITE_URL + "#book"},
            "creator": {"@id": ORGANISATION},
            "license": LICENCE,
            "inLanguage": LANGUAGE,
            "isAccessibleForFree": True,
            "keywords": [
                "Jules Verne",
                "Around the World in Eighty Days",
                "Phileas Fogg",
                "named entity recognition",
                "gazetteer",
                "historical geography",
                "Project Gutenberg",
                "digital humanities",
            ],
            "distribution": [
                {
                    "@type": "DataDownload",
                    "name": name,
                    "encodingFormat": "application/json",
                    "contentUrl": SITE_URL + "data/" + file,
                }
                for file, name in (
                    (
                        "journey.json",
                        "The itinerary: nine stops, eight stages, the days budgeted",
                    ),
                    (
                        "places.json",
                        "Every place the book names, resolved or held back",
                    ),
                    (
                        "chapters.json",
                        "37 chapters: title, summary, cast, places, positions",
                    ),
                    (
                        "provenance.json",
                        "Input hashes, and the counts of what is unchecked",
                    ),
                )
            ],
        },
        {
            "@type": "BreadcrumbList",
            "@id": SITE_URL + "#breadcrumb",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "Crow Intelligence",
                    "item": "https://crowintelligence.org/",
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": "Projects",
                    "item": "https://crowintelligence.org/projects.html",
                },
                {
                    "@type": "ListItem",
                    "position": 3,
                    "name": STRINGS["site.title"],
                },
            ],
        },
        {
            "@type": "Organization",
            "@id": ORGANISATION,
            "name": "Crow Intelligence",
            "url": "https://crowintelligence.org/",
        },
    ]
    body = json.dumps(
        {"@context": "https://schema.org", "@graph": graph},
        ensure_ascii=False,
        indent=2,
    )
    return f'<script type="application/ld+json">\n{body}\n</script>'
