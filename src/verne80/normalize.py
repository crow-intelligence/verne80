r"""Typography folding and whitespace collapse — the project's comparison primitive.

Every verbatim comparison in this project goes through :func:`normalize_quote`. Two
independent problems make that necessary, and both would otherwise sink the evidence
validator:

**Line wrapping.** Project Gutenberg hard-wraps its plain text at about seventy-two
columns. A sentence quoted from the middle of a chapter therefore contains a newline in
the file but not in the extraction JSON, so *any* quote longer than one line would fail
a naive substring test — not occasionally, but always.

**Typography.** The 1872 text uses U+2019 for apostrophes, U+201C/U+201D for quotation
marks and unspaced em dashes; a language model asked to copy a sentence verbatim will
sometimes hand back the ASCII spellings instead. That is a difference in how punctuation
is *spelled*, not in what the sentence *says*.

**Italics.** Gutenberg marks them with underscores — ``_Times_``, ``_viâ_`` — and a
model quoting the passage silently drops them.

Folding weakens the word "verbatim", and it is worth being precise about how far. The
fold can only ever collapse punctuation variants and whitespace onto a canonical form;
it cannot invent, delete or reorder a word. A quote that passes because the model wrote
``--`` where Verne wrote an em dash is still the same sentence. A quote the model made
up cannot be folded into existence. Deleting the underscore does cost something real —
``_Times_`` and ``Times`` become one key, so emphasis is no longer distinguishable — but
nothing downstream reads emphasis, and the alternative is a permanent drizzle of false
alarms on every italicised quotation. Note also that the fold is applied to the
*matching key* only: the evidence string stored in ``data/extractions/`` is never
rewritten.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["fold_typography", "match_key", "normalize_quote"]

# Fold families. Each maps a set of codepoints onto one canonical ASCII spelling, so
# that two texts differing only in typographic convention reduce to the same key.
# Verified against the actual Gutenberg #103 text, which uses U+2019, U+201C/D and
# U+2014.
_APOSTROPHES = dict.fromkeys(map(ord, "‘’‚‛ʼ´`"), "'")
_QUOTES = dict.fromkeys(map(ord, "“”„‟«»″"), '"')
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_SPACES = dict.fromkeys(
    map(ord, "       "),
    " ",
)
# Zero-width characters carry no meaning here and would break a substring test silently.
_DELETE: dict[int, str | None] = dict.fromkeys(map(ord, "­​﻿"), None)
_ELLIPSIS = {ord("…"): "..."}

# Project Gutenberg marks italics with underscores. In #103 there are 78 of them, in 39
# balanced spans and none free-standing: newspaper titles (``_Times_``), foreign words
# (``_viâ_``, ``_visa_``) and emphasis on the words the plot turns on (``_eighty_``,
# ``_eastward_``, ``_westward_``). One span crosses a wrapped line. A model quoting such
# a passage drops the markers, which is a difference in how emphasis is *typeset*, not
# in what the sentence says.
_ITALICS: dict[int, str | None] = {ord("_"): None}

_FOLD: dict[int, str | None] = {
    **_APOSTROPHES,
    **_QUOTES,
    **_DASHES,
    **_SPACES,
    **_ELLIPSIS,
    **_DELETE,
    **_ITALICS,
}

_WHITESPACE = re.compile(r"\s+")
_DASH_RUN = re.compile(r"-{2,}")


def fold_typography(text: str) -> str:
    r"""Normalise to NFC and fold punctuation variants onto their ASCII spelling.

    Line structure is deliberately left alone, so the result can still be displayed or
    counted by line. Use :func:`normalize_quote` when you want a single-line key.

    Args:
        text: Any string.

    Returns:
        The NFC-normalised string with apostrophes, quotation marks, dashes, exotic
        spaces and ellipses folded, and zero-width characters and Gutenberg's underscore
        italic markers removed.

    Contract:
        - Idempotent: folding a folded string changes nothing.
        - The output is in NFC.
        - Newlines and tabs survive unchanged.
        - Total: never raises, for any string.

    Examples:
        Curly quotation marks and apostrophes become their ASCII spellings:

        >>> fold_typography("“I’ll wager it,” said Fogg.")
        '"I\'ll wager it," said Fogg.'

        An em dash becomes a hyphen, and an ellipsis becomes three dots:

        >>> fold_typography("Suez—Bombay…")
        'Suez-Bombay...'

        Gutenberg's underscore italic markers go:

        >>> fold_typography("From London to Suez _viâ_ Mont Cenis")
        'From London to Suez viâ Mont Cenis'

        Line structure is preserved:

        >>> fold_typography("one\ntwo")
        'one\ntwo'
    """
    return unicodedata.normalize("NFC", text).translate(_FOLD)


def normalize_quote(text: str) -> str:
    r"""Reduce a string to the single-line key used for every verbatim comparison.

    This is :func:`fold_typography` followed by a whitespace collapse. The collapse is
    what lets a quotation spanning a wrapped line match the chapter file it came from.

    Args:
        text: Any string — a chapter body, or one evidence quote.

    Returns:
        The folded text on one line, with runs of whitespace collapsed to a single
        space, runs of hyphens collapsed to one, and no leading or trailing whitespace.

    Contract:
        - Idempotent.
        - The output is in NFC.
        - The output contains no newline, no tab, no double space, and equals its own
          ``strip()``.
        - Typography-invariant: replacing any character by another member of its fold
          family leaves the output unchanged.
        - Total: never raises, and maps the empty string to the empty string.

    Examples:
        A quotation broken across two wrapped lines matches its single-line form:

        >>> normalize_quote("They mounted upon\nthe elephant, and set out")
        'They mounted upon the elephant, and set out'

        Typographic variants collapse onto one key:

        >>> normalize_quote("“Suez—Bombay”") == normalize_quote('"Suez--Bombay"')
        True

        Idempotent, and safe on the empty string:

        >>> spaced = "  a   b  "
        >>> normalize_quote(normalize_quote(spaced)) == normalize_quote(spaced)
        True
        >>> normalize_quote("")
        ''
    """
    folded = fold_typography(text)
    collapsed = _WHITESPACE.sub(" ", folded)
    return _DASH_RUN.sub("-", collapsed).strip()


def match_key(text: str) -> str:
    r"""Fold case on top of :func:`normalize_quote`, for tolerant comparison only.

    Used where two strings should be considered the same name or title regardless of
    capitalisation — chapter titles are ALL CAPS in the source, for instance. A quote
    that matches its chapter only under this key is reported as a warning, never as a
    pass: a change in capitalisation is a change the model made to the text.

    Args:
        text: Any string.

    Returns:
        The normalised, case-folded key.

    Contract:
        - Idempotent.
        - Case-invariant for ASCII. Full Unicode case-invariance does not hold —
          U+0131 (dotless i) upper-cases to "I" but folds to itself — so the general
          form is ``match_key(s.casefold()) == match_key(s)``.
        - Total: never raises.

    Examples:
        >>> match_key("AROUND THE WORLD") == match_key("Around the World")
        True
        >>> match_key("  Bombay\n")
        'bombay'
    """
    return normalize_quote(text).casefold()
