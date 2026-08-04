r"""Grep every evidence quotation back against the chapter it claims to come from.

This is the piece the spec singles out. Asking a model for a verbatim quotation
alongside each extracted fact turns verification from a reading task into a string
search: thirty-seven chapters times roughly six fields is not something one person
rereads, but it is something a script checks in a second. A fact whose quotation is not
in the chapter did not come from the chapter.

The invariant the whole pipeline rests on, and the reason both halves read the same
file:

    ``render_prompt`` embeds ``chapter_NN.txt`` verbatim, and ``check_quote`` searches
    ``chapter_NN.txt`` verbatim. What the model saw and what the validator greps are the
    same bytes.

Matching runs down a ladder rather than answering yes or no, because "not found" covers
two very different situations. A quotation that differs by a curly apostrophe is a
transcription difference; a quotation that differs by a noun is a fabrication. Only the
first two rungs pass. Everything below them lands in the review queue with the closest
real text, its line number and an inline diff, so the fix takes seconds and the
judgement stays with a human.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from verne80.normalize import match_key, normalize_quote, strip_edge_quotes
from verne80.schema import ChapterExtraction, EvidenceRef

__all__ = [
    "MIN_FRAGMENT",
    "NEAR_MISS_RATIO",
    "PASSING",
    "MatchKind",
    "NormalisedChapter",
    "QuoteCheck",
    "check_chapter_quotes",
    "check_quote",
    "find_best_span",
    "inline_diff",
    "summarise",
]

# Tuned from nothing so far — the JSON report carries the full ratio distribution so
# this can be set from real data after the first complete run.
NEAR_MISS_RATIO = 0.82

# Below this, an ellipsis fragment is too short to be evidence of anything.
MIN_FRAGMENT = 8

_ELLIPSIS_SPLIT = re.compile(r"\s*\.\.\.\s*")
_WORD_EDGE = re.compile(r"\w")


class MatchKind(StrEnum):
    """How well a quotation matched its chapter."""

    EXACT = "exact"
    NORMALISED = "normalised"
    CASE_INSENSITIVE = "case_insensitive"
    ELLIPSIS = "ellipsis"
    NEAR_MISS = "near_miss"
    MISSING = "missing"


PASSING = frozenset({MatchKind.EXACT, MatchKind.NORMALISED})


@dataclass(frozen=True, slots=True)
class NormalisedChapter:
    """A chapter, alongside its single-line matching key and a map back to the file.

    The ``offsets`` array is what makes the review queue useful rather than merely
    correct: it turns a match position in the collapsed key back into a line number in
    the file a human actually opens to fix the quotation.

    Attributes:
        number: The chapter number.
        raw: The file contents, exactly as written by ``01_chapters.py``.
        norm: ``raw`` under :func:`~verne80.normalize.normalize_quote`.
        offsets: ``offsets[i]`` is the index in ``raw`` of the character at ``norm[i]``.
    """

    number: int
    raw: str
    norm: str
    offsets: tuple[int, ...]

    @classmethod
    def from_text(cls, number: int, raw: str) -> NormalisedChapter:
        r"""Build the normalised form and the offset map together.

        Args:
            number: The chapter number.
            raw: The chapter file contents.

        Returns:
            The prepared chapter.

        Contract:
            - ``len(offsets) == len(norm)``.
            - ``offsets`` is non-decreasing, and every entry indexes ``raw``. Not
              strictly increasing: ``…`` folds to three characters, which share the
              offset of the single character they came from.
            - ``norm == normalize_quote(raw)``.

        Examples:
            >>> chapter = NormalisedChapter.from_text(1, "a  b\nc")
            >>> chapter.norm
            'a b c'
            >>> chapter.line_of(4)
            2
        """
        norm_chars: list[str] = []
        offsets: list[int] = []
        for index, char in enumerate(raw):
            folded = normalize_quote(char)
            if not folded:
                # Whitespace or a zero-width character. A run of it becomes one space,
                # attributed to the first character of the run so the line number points
                # at where the text actually starts.
                if char.isspace() and norm_chars and norm_chars[-1] != " ":
                    norm_chars.append(" ")
                    offsets.append(index)
                continue
            norm_chars.extend(folded)
            offsets.extend([index] * len(folded))

        # normalize_quote also strips the ends and collapses dash runs; mirror that here
        # so norm and offsets stay in step with the canonical form.
        start = 0
        end = len(norm_chars)
        while start < end and norm_chars[start] == " ":
            start += 1
        while end > start and norm_chars[end - 1] == " ":
            end -= 1
        norm = "".join(norm_chars[start:end])
        trimmed = tuple(offsets[start:end])

        collapsed_norm, collapsed_offsets = _collapse_dash_runs(norm, trimmed)
        return cls(
            number=number, raw=raw, norm=collapsed_norm, offsets=collapsed_offsets
        )

    def line_of(self, norm_index: int) -> int:
        r"""Which line of the file a position in the normalised key falls on.

        Args:
            norm_index: An index into :attr:`norm`.

        Returns:
            The 1-based line number in :attr:`raw`.

        Contract:
            - Always in ``1..raw.count("\n") + 1``.
            - Clamps rather than raising for an out-of-range index.
        """
        if not self.offsets:
            return 1
        clamped = min(max(norm_index, 0), len(self.offsets) - 1)
        return self.raw.count("\n", 0, self.offsets[clamped]) + 1

    def raw_span(self, norm_start: int, norm_end: int) -> str:
        """The text of ``raw`` underlying a span of :attr:`norm`.

        Args:
            norm_start: Start index into :attr:`norm`.
            norm_end: End index into :attr:`norm`, exclusive.

        Returns:
            The corresponding slice of :attr:`raw`, whitespace-collapsed for display.
        """
        if not self.offsets or norm_start >= len(self.offsets):
            return ""
        first = self.offsets[min(norm_start, len(self.offsets) - 1)]
        last = self.offsets[min(max(norm_end - 1, 0), len(self.offsets) - 1)]
        return normalize_quote(self.raw[first : last + 1])


def _collapse_dash_runs(
    norm: str, offsets: tuple[int, ...]
) -> tuple[str, tuple[int, ...]]:
    """Collapse runs of hyphens, keeping the offset map aligned."""
    chars: list[str] = []
    kept: list[int] = []
    for index, char in enumerate(norm):
        if char == "-" and chars and chars[-1] == "-":
            continue
        chars.append(char)
        kept.append(offsets[index])
    return "".join(chars), tuple(kept)


@dataclass(frozen=True, slots=True)
class QuoteCheck:
    """The verdict on one evidence quotation.

    Attributes:
        ref: Which extraction field the quotation came from.
        kind: How well it matched.
        ratio: Similarity to the closest span, ``1.0`` for a clean match.
        best_span: The closest real text, when the quotation did not match cleanly.
        line_no: Where that text starts in ``chapter_NN.txt``.
    """

    ref: EvidenceRef
    kind: MatchKind
    ratio: float
    best_span: str | None = None
    line_no: int | None = None

    @property
    def passed(self) -> bool:
        """Whether this quotation counts as verified.

        Returns:
            True for an exact or normalised match, False otherwise.

        Examples:
            >>> ref = EvidenceRef(1, "time.evidence", "on the 2nd of October")
            >>> QuoteCheck(ref, MatchKind.NORMALISED, 1.0).passed
            True
            >>> QuoteCheck(ref, MatchKind.NEAR_MISS, 0.9).passed
            False
        """
        return self.kind in PASSING


def find_best_span(haystack: str, needle: str) -> tuple[float, int, int]:
    """Locate the span of ``haystack`` most similar to ``needle``.

    Used only to explain a failure, never to decide one. Stdlib ``difflib`` is enough:
    a chapter is about ten kilobytes and a quotation about a hundred characters, so the
    longest common block gives a centre and a short sweep around it gives the score.

    Args:
        haystack: The normalised chapter text.
        needle: The normalised quotation.

    Returns:
        A ``(ratio, start, end)`` triple, with the span snapped out to word boundaries.

    Contract:
        - ``0.0 <= ratio <= 1.0``.
        - If ``needle`` is a substring of ``haystack``, the ratio is ``1.0``.
        - An empty needle yields ``(0.0, 0, 0)``.
        - Never raises.

    Examples:
        >>> hay = "they mounted the elephant"
        >>> ratio, start, end = find_best_span(hay, "the elephant")
        >>> ratio
        1.0
        >>> hay[start:end]
        'the elephant'
    """
    if not needle or not haystack:
        return (0.0, 0, 0)

    matcher = difflib.SequenceMatcher(None, haystack, needle, autojunk=False)
    block = matcher.find_longest_match(0, len(haystack), 0, len(needle))
    if block.size == 0:
        return (0.0, 0, 0)

    centre = block.a - block.b
    best = (0.0, 0, 0)
    for shift in range(-24, 25, 6):
        start = min(max(centre + shift, 0), max(len(haystack) - 1, 0))
        end = min(start + len(needle), len(haystack))
        ratio = difflib.SequenceMatcher(None, haystack[start:end], needle).ratio()
        if ratio > best[0]:
            best = (ratio, start, end)

    ratio, start, end = best
    return (ratio, *_snap_to_words(haystack, start, end))


def _snap_to_words(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a span outwards to the nearest word boundaries."""
    while (
        start > 0
        and _WORD_EDGE.match(text[start - 1])
        and _WORD_EDGE.match(text[start])
    ):
        start -= 1
    while (
        end < len(text)
        and _WORD_EDGE.match(text[end - 1])
        and _WORD_EDGE.match(text[end])
    ):
        end += 1
    return start, end


def check_quote(ref: EvidenceRef, chapter: NormalisedChapter) -> QuoteCheck:
    r"""Decide whether one evidence quotation really appears in its chapter.

    The ladder, first hit winning:

    1. a raw substring of the chapter file — ``EXACT``;
    2. a substring once both sides are normalised — ``NORMALISED``, and where most real
       quotations land, because the chapter file is hard-wrapped and the quotation is
       not;
    3. a substring only after case folding — ``CASE_INSENSITIVE``, a warning: changed
       capitalisation is a change the model made;
    4. an ellipsis-joined quotation whose fragments all appear, in order — ``ELLIPSIS``;
    5. close to some real span — ``NEAR_MISS``;
    6. nothing like anything in the chapter — ``MISSING``.

    Args:
        ref: The quotation and where it came from.
        chapter: The prepared chapter to search.

    Returns:
        The verdict, carrying the closest real text and its line number when the match
        was not clean.

    Contract:
        - Total: never raises, for any pair of strings.
        - Any quotation that really is a substring of the chapter under
          typography folding returns ``EXACT`` or ``NORMALISED`` — the
          validator does not cry wolf.
          returns ``EXACT`` or ``NORMALISED`` — the validator does not cry wolf.
        - ``line_no`` is set whenever the quotation was located at all.
        - ``best_span`` is set whenever the match was not clean and something in the
          chapter resembled the quotation.

    Examples:
        >>> chapter = NormalisedChapter.from_text(
        ...     12, "They mounted upon\nthe elephant, and set out."
        ... )
        >>> ref = EvidenceRef(12, "transport[0].evidence", "mounted upon the elephant")
        >>> check_quote(ref, chapter).kind
        <MatchKind.NORMALISED: 'normalised'>

        An invented quotation is reported as missing, with the closest real text:

        >>> invented = EvidenceRef(
        ...     12, "money.amounts[0].evidence", "purchased for a great sum"
        ... )
        >>> check_quote(invented, chapter).kind
        <MatchKind.MISSING: 'missing'>
    """
    quote = ref.quote
    raw_position = chapter.raw.find(quote) if quote else -1
    if raw_position >= 0:
        line = chapter.raw.count("\n", 0, raw_position) + 1
        return QuoteCheck(ref, MatchKind.EXACT, 1.0, None, line)

    needle = normalize_quote(quote)
    if not needle:
        return QuoteCheck(ref, MatchKind.MISSING, 0.0)

    position = chapter.norm.find(needle)
    if position >= 0:
        return QuoteCheck(
            ref, MatchKind.NORMALISED, 1.0, None, chapter.line_of(position)
        )

    # Same rung, one more spelling: a quotation mark the model added at an edge to
    # make a fragment of dialogue look like speech. Stripped from the needle only —
    # the chapter keeps every mark it has.
    unquoted = strip_edge_quotes(needle)
    if unquoted and unquoted != needle:
        position = chapter.norm.find(unquoted)
        if position >= 0:
            return QuoteCheck(
                ref, MatchKind.NORMALISED, 1.0, None, chapter.line_of(position)
            )

    folded_position = match_key(chapter.raw).find(match_key(quote))
    if folded_position >= 0:
        return QuoteCheck(
            ref,
            MatchKind.CASE_INSENSITIVE,
            1.0,
            chapter.raw_span(folded_position, folded_position + len(needle)),
            chapter.line_of(folded_position),
        )

    ellipsis = _check_ellipsis(needle, chapter)
    if ellipsis is not None:
        return QuoteCheck(ref, MatchKind.ELLIPSIS, 1.0, None, ellipsis)

    ratio, start, end = find_best_span(chapter.norm, needle)
    span = chapter.raw_span(start, end) if ratio > 0 else None
    line = chapter.line_of(start) if ratio > 0 else None
    kind = MatchKind.NEAR_MISS if ratio >= NEAR_MISS_RATIO else MatchKind.MISSING
    return QuoteCheck(ref, kind, ratio, span, line)


def _check_ellipsis(needle: str, chapter: NormalisedChapter) -> int | None:
    """Return the first fragment's line number if an elided quotation checks out."""
    if "..." not in needle:
        return None
    fragments = [
        fragment
        for fragment in _ELLIPSIS_SPLIT.split(needle)
        if len(fragment) >= MIN_FRAGMENT
    ]
    if len(fragments) < 2:
        return None
    cursor = 0
    first: int | None = None
    for fragment in fragments:
        found = chapter.norm.find(fragment, cursor)
        if found < 0:
            return None
        if first is None:
            first = found
        cursor = found + len(fragment)
    return chapter.line_of(first or 0)


def check_chapter_quotes(
    extraction: ChapterExtraction, chapter: NormalisedChapter
) -> list[QuoteCheck]:
    """Check every evidence quotation in one extraction.

    Args:
        extraction: The parsed extraction.
        chapter: The prepared chapter it should be grounded in.

    Returns:
        One verdict per quotation, in extraction order.

    Contract:
        - The result has exactly ``len(extraction.evidence_items())`` entries.
        - Never raises.
    """
    return [check_quote(ref, chapter) for ref in extraction.evidence_items()]


def summarise(checks: Iterable[QuoteCheck]) -> Counter[MatchKind]:
    """Count verdicts by kind.

    Args:
        checks: The verdicts to count.

    Returns:
        A counter over :class:`MatchKind`.

    Examples:
        >>> ref = EvidenceRef(1, "time.evidence", "x")
        >>> summarise([QuoteCheck(ref, MatchKind.EXACT, 1.0)])[MatchKind.EXACT]
        1
    """
    return Counter(check.kind for check in checks)


def inline_diff(expected: str, actual: str) -> str:
    """Render the difference between a quotation and the closest real text.

    Reads like ``git diff --word-diff``: ``[-removed-]`` for what the quotation
    left out, ``{+added+}`` for what it added. Short enough to scan in a review
    queue without opening the chapter.
    ``{+added+}`` for what it added. Short enough to scan in a review queue without
    opening the chapter.

    Args:
        expected: The quotation as the model wrote it.
        actual: The closest real text from the chapter.

    Returns:
        A one-line diff.

    Contract:
        - Never raises.
        - Returns ``actual`` unchanged when the two are equal.

    Examples:
        >>> inline_diff("They mounted the elephant", "They mounted upon the elephant")
        'They mounted {+upon +}the elephant'
    """
    if expected == actual:
        return actual
    matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(expected[i1:i2])
        elif tag == "delete":
            parts.append(f"[-{expected[i1:i2]}-]")
        elif tag == "insert":
            parts.append(f"{{+{actual[j1:j2]}+}}")
        else:
            parts.append(f"[-{expected[i1:i2]}-]{{+{actual[j1:j2]}+}}")
    return "".join(parts)


def failing(checks: Sequence[QuoteCheck]) -> list[QuoteCheck]:
    """The verdicts a human needs to look at.

    Args:
        checks: All verdicts.

    Returns:
        Those that did not pass cleanly, worst first.

    Examples:
        >>> ref = EvidenceRef(1, "time.evidence", "x")
        >>> [c.kind for c in failing([
        ...     QuoteCheck(ref, MatchKind.EXACT, 1.0),
        ...     QuoteCheck(ref, MatchKind.MISSING, 0.2),
        ...     QuoteCheck(ref, MatchKind.NEAR_MISS, 0.9),
        ... ])]
        [<MatchKind.MISSING: 'missing'>, <MatchKind.NEAR_MISS: 'near_miss'>]
    """
    order = {
        MatchKind.MISSING: 0,
        MatchKind.NEAR_MISS: 1,
        MatchKind.CASE_INSENSITIVE: 2,
        MatchKind.ELLIPSIS: 3,
    }
    return sorted(
        (check for check in checks if not check.passed),
        key=lambda check: (order.get(check.kind, 9), check.ratio),
    )
