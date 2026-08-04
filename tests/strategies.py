"""Shared Hypothesis strategies.

The interesting one is :func:`typographic_variant`. It re-spells a string's punctuation
and re-wraps its lines at random, which is exactly what stands between an evidence
quotation and the chapter it came from. A property that survives it is a property that
survives a real paste.
"""

from __future__ import annotations

import hypothesis.strategies as st

# Each family maps to the character the fold collapses it onto, so a variant is built by
# picking any member at random.
APOSTROPHES = "'‘’‚‛ʼ´`"
QUOTES = '"“”„‟«»'
DASHES = "-‐‑‒–—―−"
SPACES = "    "

_FAMILIES = {
    **{char: APOSTROPHES for char in APOSTROPHES},
    **{char: QUOTES for char in QUOTES},
    **{char: DASHES for char in DASHES},
    **{char: SPACES for char in SPACES},
}


@st.composite
def typographic_variant(draw: st.DrawFn, text: str) -> str:
    """Re-spell punctuation and re-wrap whitespace without changing the words.

    Args:
        draw: Hypothesis' draw function.
        text: The string to vary.

    Returns:
        A string that folds to the same key as ``text``.
    """
    out: list[str] = []
    for char in text:
        family = _FAMILIES.get(char)
        if family is None:
            out.append(char)
        elif family is SPACES:
            # Whitespace collapses, so any run of any whitespace is equivalent.
            out.append(draw(st.sampled_from([" ", "\n", "  ", " \n", "\t"])))
        else:
            out.append(draw(st.sampled_from(family)))
    return "".join(out)


@st.composite
def italicised(draw: st.DrawFn, text: str) -> str:
    """Wrap random word runs in Gutenberg's underscore italic markers.

    A different shape from :func:`typographic_variant`: that one *re-spells*
    characters, this one *inserts* them. Both must leave the matching key alone.

    Args:
        draw: Hypothesis' draw function.
        text: The string to italicise parts of.

    Returns:
        A string that folds to the same key as ``text``.
    """
    words = text.split(" ")
    out: list[str] = []
    for word in words:
        if word and draw(st.booleans()):
            out.append(f"_{word}_")
        else:
            out.append(word)
    return " ".join(out)


@st.composite
def chapter_body(draw: st.DrawFn, min_words: int = 5, max_words: int = 40) -> str:
    """Build a plausible chapter body: real words, hard-wrapped."""
    words = draw(
        st.lists(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=9),
            min_size=min_words,
            max_size=max_words,
        )
    )
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        if sum(len(w) + 1 for w in current) > 60:
            lines.append(" ".join(current))
            current = []
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


@st.composite
def gutenberg_document(
    draw: st.DrawFn, min_chapters: int = 1, max_chapters: int = 6
) -> tuple[str, int]:
    """Build a whole synthetic Gutenberg document.

    Returns:
        The document text and how many chapters it contains.
    """
    from verne80.chapters import int_to_roman

    count = draw(st.integers(min_value=min_chapters, max_value=max_chapters))
    parts = [
        "*** START OF THE PROJECT GUTENBERG EBOOK TEST ***",
        "",
        "A Title",
        "",
        "Contents",
        "",
    ]
    parts.extend(
        f" CHAPTER {int_to_roman(n)}. TITLE NUMBER {n}" for n in range(1, count + 1)
    )
    parts.append("")
    for number in range(1, count + 1):
        parts.extend(
            [
                f"CHAPTER {int_to_roman(number)}.",
                f"TITLE NUMBER {number}",
                "",
                draw(chapter_body()) or "a body.",
                "",
            ]
        )
    parts.append("*** END OF THE PROJECT GUTENBERG EBOOK TEST ***")
    return "\n".join(parts), count


@st.composite
def evidence_quote(draw: st.DrawFn, chapter_text: str) -> str:
    """Draw a word-boundary slice of a chapter — a quotation genuinely present."""
    words = chapter_text.split()
    length = draw(st.integers(min_value=3, max_value=min(12, max(3, len(words)))))
    start = draw(st.integers(min_value=0, max_value=max(0, len(words) - length)))
    return " ".join(words[start : start + length])
